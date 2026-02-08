"""POST /chat endpoint with full RAG orchestration.

Orchestrates: retrieve -> compute confidence -> build context -> call LLM ->
verify citations -> return response.  Confidence scoring uses retrieval signals
only (chunk count + ts_rank_cd scores), never LLM self-assessment.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from app.db.session import get_db_session
from app.dependencies import get_gemini_client
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    Citation,
    LLMCitation,
    LLMResponse,
)
from app.services.gemini_client import SYSTEM_PROMPT, LLMClient
from app.services.retrieval import RetrievedChunk, retrieve_chunks

logger = logging.getLogger(__name__)


def compute_confidence(
    chunks: list[RetrievedChunk],
    min_chunks: int = 3,
    high_score_threshold: float = 0.1,
) -> str:
    """Derive confidence from retrieval signals (chunk count + top score).

    Uses retrieval metrics only -- never LLM self-assessment (CHAT-04).
    """
    if not chunks:
        return "low"

    has_enough_chunks = len(chunks) >= min_chunks
    has_high_score = chunks[0].score >= high_score_threshold

    if has_enough_chunks and has_high_score:
        return "high"
    if has_enough_chunks or has_high_score:
        return "medium"
    return "low"


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Format retrieved chunks into context string for the LLM.

    Each chunk header uses owner/repo/path@sha:line-range format, matching
    the SYSTEM_PROMPT's documented chunk header format.  The owner prefix
    is included for disambiguation across multiple repos with the same name.
    """
    parts: list[str] = []
    for chunk in chunks:
        header = (
            f"--- CHUNK: {chunk.repo_owner}/{chunk.repo_name}/"
            f"{chunk.path}@{chunk.commit_sha}:"
            f"{chunk.start_line}-{chunk.end_line} ---"
        )
        parts.append(f"{header}\n{chunk.content}")
    return "\n\n".join(parts)


def verify_citations(
    llm_citations: list[LLMCitation],
    chunks: list[RetrievedChunk],
) -> list[Citation]:
    """Mechanically verify LLM citations against actually-retrieved chunks.

    Drops any hallucinated citations whose source string does not match a
    retrieved chunk.  Citation source format:
    ``owner/repo/path@sha:start_line-end_line``.
    """
    valid_sources = {
        f"{c.repo_owner}/{c.repo_name}/{c.path}@{c.commit_sha}:"
        f"{c.start_line}-{c.end_line}"
        for c in chunks
    }
    return [
        Citation(source=cit.source, relevance=cit.relevance)
        for cit in llm_citations
        if cit.source in valid_sources
    ]


router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(
    request: ChatRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    llm_client: Annotated[LLMClient, Depends(get_gemini_client)],
) -> ChatResponse:
    """Answer a question using the RAG pipeline.

    Orchestration order:
    1. Retrieve relevant chunks from the knowledge base.
    2. Compute confidence from retrieval signals.
    3. Build context string from chunks.
    4. Call LLM with system prompt and context.
    5. Verify citations against retrieved chunks.
    6. Return structured response.
    """
    # 1. Retrieve chunks
    chunks = await retrieve_chunks(session, request.question)

    # 2. Handle empty retrieval
    if not chunks:
        return ChatResponse(
            answer=(
                "I don't know. Could you provide more details "
                "about what you're looking for?"
            ),
            citations=[],
            confidence="low",
        )

    # 3. Compute confidence from retrieval signals
    confidence = compute_confidence(chunks)

    # 4. Build context string
    context = build_context(chunks)

    # 5-6. Call LLM and parse response
    try:
        raw = await llm_client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_content=f"Context:\n{context}\n\nQuestion: {request.question}",
            response_schema=LLMResponse,
        )
        llm_response = LLMResponse.model_validate_json(raw)
    except Exception:
        logger.exception("LLM generation failed")
        return ChatResponse(
            answer=(
                "I'm sorry, I encountered an error processing your question. "
                "Please try again."
            ),
            citations=[],
            confidence="low",
        )

    # 7. Verify citations
    verified = verify_citations(llm_response.citations, chunks)

    # 8. Handle insufficient context (LLM says it doesn't know)
    if llm_response.needs_clarification:
        return ChatResponse(
            answer=llm_response.answer,
            citations=verified,
            confidence="low",
        )

    # 9. Handle no verified citations
    if not verified:
        return ChatResponse(
            answer=llm_response.answer,
            citations=verified,
            confidence="low",
        )

    # 10. Success
    return ChatResponse(
        answer=llm_response.answer,
        citations=verified,
        confidence=confidence,
    )
