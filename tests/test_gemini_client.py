"""Tests for the Gemini client abstraction and chat schemas.

All tests are mock-based -- no real Gemini API calls are made.
Tests cover InMemoryLLMClient behaviour, LLMResponse parsing,
ChatRequest validation, ChatResponse structure, and SYSTEM_PROMPT content.
"""

import json

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest, ChatResponse, Citation, LLMResponse
from app.services.gemini_client import SYSTEM_PROMPT, InMemoryLLMClient

# ---------------------------------------------------------------------------
# InMemoryLLMClient tests (async)
# ---------------------------------------------------------------------------


async def test_in_memory_client_returns_default_response() -> None:
    """Default canned response is valid JSON parseable as LLMResponse."""
    client = InMemoryLLMClient()
    result = await client.generate(
        system_prompt="sys", user_content="hello", response_schema=LLMResponse
    )

    # Must be valid JSON
    parsed = json.loads(result)
    assert parsed["answer"] == "test answer"
    assert parsed["citations"] == []
    assert parsed["needs_clarification"] is False
    assert parsed["clarifying_question"] is None

    # Must be parseable as LLMResponse
    llm_resp = LLMResponse.model_validate_json(result)
    assert llm_resp.answer == "test answer"
    assert llm_resp.citations == []
    assert llm_resp.needs_clarification is False
    assert llm_resp.clarifying_question is None


async def test_in_memory_client_captures_calls() -> None:
    """Each generate() call is recorded with its arguments."""
    client = InMemoryLLMClient()

    await client.generate(
        system_prompt="prompt-a", user_content="content-a", response_schema=LLMResponse
    )
    await client.generate(
        system_prompt="prompt-b", user_content="content-b", response_schema=LLMResponse
    )

    assert len(client.calls) == 2
    assert client.calls[0]["system_prompt"] == "prompt-a"
    assert client.calls[0]["user_content"] == "content-a"
    assert client.calls[1]["system_prompt"] == "prompt-b"
    assert client.calls[1]["user_content"] == "content-b"


async def test_in_memory_client_custom_response() -> None:
    """Setting client.response changes the returned value."""
    custom = json.dumps(
        {
            "answer": "custom answer",
            "citations": [{"source": "owner/repo/file.py@abc123:1-10", "relevance": "defines X"}],
            "needs_clarification": False,
            "clarifying_question": None,
        }
    )
    client = InMemoryLLMClient()
    client.response = custom

    result = await client.generate(
        system_prompt="sys", user_content="hello", response_schema=LLMResponse
    )
    assert result == custom

    llm_resp = LLMResponse.model_validate_json(result)
    assert llm_resp.answer == "custom answer"
    assert len(llm_resp.citations) == 1
    assert llm_resp.citations[0].source == "owner/repo/file.py@abc123:1-10"


# ---------------------------------------------------------------------------
# LLMResponse parsing tests (sync)
# ---------------------------------------------------------------------------


def test_llm_response_parses_valid_json() -> None:
    """A well-formed JSON string parses into LLMResponse with correct fields."""
    raw = json.dumps(
        {
            "answer": "The function sorts a list using quicksort.",
            "citations": [
                {"source": "acme/tools/sort.py@def456:12-30", "relevance": "sort implementation"},
                {"source": "acme/tools/utils.py@def456:1-5", "relevance": "helper import"},
            ],
            "needs_clarification": False,
            "clarifying_question": None,
        }
    )
    resp = LLMResponse.model_validate_json(raw)
    assert resp.answer == "The function sorts a list using quicksort."
    assert len(resp.citations) == 2
    assert resp.citations[0].source == "acme/tools/sort.py@def456:12-30"
    assert resp.citations[1].relevance == "helper import"
    assert resp.needs_clarification is False
    assert resp.clarifying_question is None


def test_llm_response_with_clarification() -> None:
    """LLMResponse correctly handles the clarification case."""
    raw = json.dumps(
        {
            "answer": "I don't know based on the provided context.",
            "citations": [],
            "needs_clarification": True,
            "clarifying_question": "Which module are you asking about?",
        }
    )
    resp = LLMResponse.model_validate_json(raw)
    assert resp.needs_clarification is True
    assert resp.clarifying_question == "Which module are you asking about?"
    assert resp.citations == []


# ---------------------------------------------------------------------------
# ChatRequest validation tests (sync)
# ---------------------------------------------------------------------------


def test_chat_request_validates_question_length() -> None:
    """ChatRequest enforces min_length=1 and max_length=1000."""
    # Empty string should fail
    with pytest.raises(ValidationError):
        ChatRequest(question="")

    # Over 1000 chars should fail
    with pytest.raises(ValidationError):
        ChatRequest(question="x" * 1001)

    # Valid question should succeed
    req = ChatRequest(question="What does the UserService class do?")
    assert req.question == "What does the UserService class do?"

    # Exactly 1000 chars should succeed (boundary)
    req_max = ChatRequest(question="y" * 1000)
    assert len(req_max.question) == 1000


# ---------------------------------------------------------------------------
# ChatResponse structure tests (sync)
# ---------------------------------------------------------------------------


def test_chat_response_structure() -> None:
    """ChatResponse serializes with the CHAT-06 contract keys."""
    resp = ChatResponse(
        answer="The function sorts a list.",
        citations=[
            Citation(source="acme/tools/sort.py@abc:1-10", relevance="sort impl"),
        ],
        confidence="high",
    )
    assert resp.answer == "The function sorts a list."
    assert resp.confidence == "high"
    assert len(resp.citations) == 1

    dumped = resp.model_dump()
    assert set(dumped.keys()) == {"answer", "citations", "confidence"}
    assert isinstance(dumped["citations"], list)
    assert dumped["citations"][0]["source"] == "acme/tools/sort.py@abc:1-10"


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT content tests (sync)
# ---------------------------------------------------------------------------


def test_system_prompt_contains_grounding_rules() -> None:
    """SYSTEM_PROMPT includes the key grounding, citation, and fallback rules."""
    assert "ONLY" in SYSTEM_PROMPT
    assert "I don't know" in SYSTEM_PROMPT
    assert "CHUNK:" in SYSTEM_PROMPT
    assert "clarifying question" in SYSTEM_PROMPT
    # Citation format reference
    assert "owner" in SYSTEM_PROMPT or "repo" in SYSTEM_PROMPT
    assert "start_line" in SYSTEM_PROMPT or "line" in SYSTEM_PROMPT
