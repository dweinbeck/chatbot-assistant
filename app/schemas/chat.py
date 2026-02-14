"""Chat request/response schemas and LLM output models.

Defines the API contract for the chat endpoint (ChatRequest, ChatResponse,
Citation) and the structured output schema for the Gemini API (LLMResponse,
LLMCitation).  The LLM-facing models intentionally have NO default values
for compatibility with google-genai ``response_schema``.
"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming chat question."""

    question: str = Field(min_length=1, max_length=1000)


class Citation(BaseModel):
    """A verified citation in the API response."""

    source: str = Field(description="Citation in owner/repo/path@sha:start_line-end_line format")
    relevance: str = Field(description="How this chunk relates to the answer")


class ChatResponse(BaseModel):
    """Structured chat response matching CHAT-06 contract."""

    answer: str
    citations: list[Citation]
    confidence: str = Field(description="low, medium, or high")


class LLMCitation(BaseModel):
    """Citation as returned by the LLM (simple, no defaults)."""

    source: str
    relevance: str


class LLMResponse(BaseModel):
    """Structured output schema for the Gemini API.

    Kept simple with NO default values for google-genai response_schema
    compatibility.  Use ``str | None`` for nullable fields.
    """

    answer: str
    citations: list[LLMCitation]
    needs_clarification: bool
    clarifying_question: str | None
