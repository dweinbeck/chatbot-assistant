"""End-to-end tests for POST /chat covering full RAG orchestration.

Tests cover: success with citations, empty retrieval, insufficient context,
hallucinated citation dropping, confidence levels (high/medium/low),
question validation, and LLM error handling.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from app.services.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from httpx import AsyncClient

    from app.services.gemini_client import InMemoryLLMClient

_DEFAULT_SHA = "abc1234567890123456789012345678901234567"


def _make_chunk(
    id: int = 1,  # noqa: A002
    repo_owner: str = "testowner",
    repo_name: str = "testrepo",
    path: str = "src/main.py",
    commit_sha: str = _DEFAULT_SHA,
    start_line: int = 1,
    end_line: int = 10,
    content: str = "def hello():\n    return 'world'",
    score: float = 0.5,
) -> RetrievedChunk:
    """Build a RetrievedChunk with sensible defaults for testing."""
    return RetrievedChunk(
        id=id,
        repo_owner=repo_owner,
        repo_name=repo_name,
        path=path,
        commit_sha=commit_sha,
        start_line=start_line,
        end_line=end_line,
        content=content,
        score=score,
    )


def _citation_source(chunk: RetrievedChunk) -> str:
    """Build the citation source string for a chunk (owner/repo/path@sha:start-end)."""
    return (
        f"{chunk.repo_owner}/{chunk.repo_name}/{chunk.path}"
        f"@{chunk.commit_sha}:{chunk.start_line}-{chunk.end_line}"
    )


def _llm_response_json(
    answer: str = "test answer",
    citations: list[dict] | None = None,
    needs_clarification: bool = False,
    clarifying_question: str | None = None,
) -> str:
    """Build a valid LLMResponse JSON string."""
    return json.dumps({
        "answer": answer,
        "citations": citations or [],
        "needs_clarification": needs_clarification,
        "clarifying_question": clarifying_question,
    })


# ---------- Test 1: Success with citations ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_success_with_citations(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """POST /chat with matching chunks returns answer with verified citations."""
    chunks = [
        _make_chunk(id=1, path="src/main.py", score=0.5),
        _make_chunk(id=2, path="src/utils.py", start_line=5, end_line=15, score=0.3),
        _make_chunk(id=3, path="src/helpers.py", start_line=20, end_line=30, score=0.2),
    ]
    mock_retrieve.return_value = chunks

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "defines hello function"},
        {"source": _citation_source(chunks[1]), "relevance": "utility helper"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="The hello function returns 'world'.",
        citations=citations,
    )

    response = await client.post("/chat", json={"question": "How does hello work?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "The hello function returns 'world'."
    assert len(data["citations"]) == 2
    assert data["confidence"] == "high"


# ---------- Test 2a: Empty DB suggests sync ----------


@pytest.mark.anyio
@patch("app.routers.chat.has_any_chunks", new_callable=AsyncMock)
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_empty_db_suggests_sync(
    mock_retrieve: AsyncMock,
    mock_has_chunks: AsyncMock,
    client: AsyncClient,
) -> None:
    """POST /chat with empty database suggests syncing a repo."""
    mock_retrieve.return_value = []
    mock_has_chunks.return_value = False

    response = await client.post("/chat", json={"question": "What is foo?"})

    assert response.status_code == 200
    data = response.json()
    assert "No repositories have been indexed" in data["answer"]
    assert "/admin/sync-repo" in data["answer"]
    assert data["confidence"] == "low"
    assert data["citations"] == []


# ---------- Test 2b: No match suggests rephrase ----------


@pytest.mark.anyio
@patch("app.routers.chat.has_any_chunks", new_callable=AsyncMock)
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_no_match_suggests_rephrase(
    mock_retrieve: AsyncMock,
    mock_has_chunks: AsyncMock,
    client: AsyncClient,
) -> None:
    """POST /chat with indexed data but no match suggests rephrasing."""
    mock_retrieve.return_value = []
    mock_has_chunks.return_value = True

    response = await client.post("/chat", json={"question": "What is foo?"})

    assert response.status_code == 200
    data = response.json()
    assert "couldn't find relevant content" in data["answer"]
    assert "rephrasing" in data["answer"]
    assert data["confidence"] == "low"
    assert data["citations"] == []


# ---------- Test 3: Insufficient context / clarification ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_insufficient_context_clarification(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """When LLM needs clarification, response has low confidence."""
    chunks = [_make_chunk(id=1, score=0.05)]
    mock_retrieve.return_value = chunks

    mock_gemini_client.response = _llm_response_json(
        answer="I don't know. What specific function are you asking about?",
        needs_clarification=True,
        clarifying_question="What specific function?",
    )

    response = await client.post("/chat", json={"question": "How does it work?"})

    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == "low"
    assert "I don't know" in data["answer"]


# ---------- Test 4: Hallucinated citations dropped ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_drops_hallucinated_citations(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """Hallucinated citations (not matching any chunk) are dropped."""
    chunks = [
        _make_chunk(id=1, path="src/main.py", score=0.5),
        _make_chunk(id=2, path="src/utils.py", start_line=5, end_line=15, score=0.3),
        _make_chunk(id=3, path="src/extra.py", start_line=1, end_line=5, score=0.2),
    ]
    mock_retrieve.return_value = chunks

    hallucinated_source = f"testowner/testrepo/src/fake.py@{_DEFAULT_SHA}:1-10"
    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "real citation 1"},
        {"source": _citation_source(chunks[1]), "relevance": "real citation 2"},
        {"source": hallucinated_source, "relevance": "hallucinated"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="The code does X.",
        citations=citations,
    )

    response = await client.post("/chat", json={"question": "What does main do?"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["citations"]) == 2
    sources = [c["source"] for c in data["citations"]]
    assert hallucinated_source not in sources


# ---------- Test 5: Confidence high ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_confidence_high(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """High confidence when >= 3 chunks and top score >= 0.1."""
    chunks = [
        _make_chunk(id=i, path=f"src/file{i}.py", start_line=i, end_line=i + 5, score=s)
        for i, s in [(1, 0.15), (2, 0.12), (3, 0.08), (4, 0.05)]
    ]
    mock_retrieve.return_value = chunks

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "relevant"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="Here is the answer.", citations=citations,
    )

    response = await client.post("/chat", json={"question": "What is it?"})

    assert response.status_code == 200
    assert response.json()["confidence"] == "high"


# ---------- Test 6: Confidence medium (enough chunks, low score) ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_confidence_medium_enough_chunks(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """Medium confidence when >= 3 chunks but top score < 0.1."""
    chunks = [
        _make_chunk(id=i, path=f"src/file{i}.py", start_line=i, end_line=i + 5, score=s)
        for i, s in [(1, 0.05), (2, 0.04), (3, 0.03)]
    ]
    mock_retrieve.return_value = chunks

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "relevant"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="Answer.", citations=citations,
    )

    response = await client.post("/chat", json={"question": "What is it?"})

    assert response.status_code == 200
    assert response.json()["confidence"] == "medium"


# ---------- Test 7: Confidence medium (high score, few chunks) ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_confidence_medium_high_score(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """Medium confidence when < 3 chunks but top score >= 0.1."""
    chunks = [
        _make_chunk(id=1, path="src/main.py", score=0.2),
        _make_chunk(id=2, path="src/utils.py", start_line=5, end_line=15, score=0.15),
    ]
    mock_retrieve.return_value = chunks

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "relevant"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="Answer.", citations=citations,
    )

    response = await client.post("/chat", json={"question": "What is it?"})

    assert response.status_code == 200
    assert response.json()["confidence"] == "medium"


# ---------- Test 8: Confidence low ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_confidence_low(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """Low confidence when < 3 chunks and top score < 0.1."""
    chunks = [_make_chunk(id=1, score=0.05)]
    mock_retrieve.return_value = chunks

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "relevant"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="Maybe.", citations=citations,
    )

    response = await client.post("/chat", json={"question": "What is it?"})

    assert response.status_code == 200
    assert response.json()["confidence"] == "low"


# ---------- Test 9: Question validation ----------


@pytest.mark.anyio
async def test_chat_question_validation(client: AsyncClient) -> None:
    """Empty and overly long questions are rejected with 422."""
    # Empty question
    response = await client.post("/chat", json={"question": ""})
    assert response.status_code == 422

    # Question exceeding max_length
    response = await client.post("/chat", json={"question": "x" * 1001})
    assert response.status_code == 422


# ---------- Test 10: LLM error returns graceful response ----------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_llm_error_returns_graceful_response(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """LLM errors produce a graceful response, not a 500."""
    chunks = [
        _make_chunk(id=1, score=0.5),
        _make_chunk(id=2, path="src/utils.py", start_line=5, end_line=15, score=0.3),
        _make_chunk(id=3, path="src/helpers.py", start_line=20, end_line=30, score=0.2),
    ]
    mock_retrieve.return_value = chunks

    # Invalid JSON will cause model_validate_json to fail
    mock_gemini_client.response = "not valid json at all"

    response = await client.post("/chat", json={"question": "What is it?"})

    assert response.status_code == 200
    data = response.json()
    assert "sorry" in data["answer"].lower() or "error" in data["answer"].lower()
    assert data["confidence"] == "low"
    assert data["citations"] == []
