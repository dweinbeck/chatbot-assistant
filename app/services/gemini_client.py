"""Gemini LLM client abstraction with protocol-based swappable implementations.

Production code uses ``GeminiClient`` which wraps the ``google-genai`` SDK's
native async API (``client.aio.models.generate_content``).  Tests use
``InMemoryLLMClient`` which captures calls and returns configurable canned
responses without requiring the GCP SDK or network access.

The ``google.genai`` import is lazy so this module loads without the SDK
installed -- following the same pattern established in ``task_queue.py``.
"""

from __future__ import annotations

from typing import Protocol

SYSTEM_PROMPT = """\
You are a code knowledge assistant. You answer questions about code \
repositories using ONLY the provided code context.

RULES:
1. ONLY use information from the provided code chunks to answer. \
Never invent code or facts.
2. For each claim in your answer, cite the source using the exact format \
from the chunk header: owner/repo/path@sha:start_line-end_line
3. If the provided context does not contain enough information to answer \
the question, respond with "I don't know" and ask ONE clarifying question.
4. Keep answers concise and technical.
5. Use the citation format exactly as shown in each chunk's metadata header.

Each code chunk is provided with a header line:
--- CHUNK: {owner}/{repo}/{path}@{sha}:{start_line}-{end_line} ---
"""


class LLMClient(Protocol):
    """Protocol for LLM generation with structured output."""

    async def generate(self, system_prompt: str, user_content: str, response_schema: type) -> str:
        """Generate a response given a system prompt, user content, and schema.

        Returns the raw JSON string from the LLM.
        """
        ...


class GeminiClient:
    """Production Gemini client using google-genai SDK.

    Uses lazy imports so the module loads without the GCP SDK installed.
    Uses ``client.aio`` for native async support (no ``asyncio.to_thread``).
    """

    def __init__(self, project: str, location: str, model: str) -> None:
        from google import genai

        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model

    async def generate(self, system_prompt: str, user_content: str, response_schema: type) -> str:
        """Generate structured JSON via Gemini, returning the raw text."""
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=0.0,
            ),
        )
        return response.text


class InMemoryLLMClient:
    """Test double that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.response: str = (
            '{"answer":"test answer","citations":[],'
            '"needs_clarification":false,"clarifying_question":null}'
        )

    async def generate(self, system_prompt: str, user_content: str, response_schema: type) -> str:
        """Append call details and return the canned response."""
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_content": user_content,
                "response_schema": response_schema,
            }
        )
        return self.response
