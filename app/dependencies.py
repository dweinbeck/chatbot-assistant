"""Centralized FastAPI dependencies for use with Depends()."""

from app.db.session import get_db_session
from app.services.gemini_client import InMemoryLLMClient, LLMClient
from app.services.task_queue import InMemoryTaskQueue, TaskQueue

_task_queue: TaskQueue = InMemoryTaskQueue()
_gemini_client: LLMClient = InMemoryLLMClient()


def get_task_queue() -> TaskQueue:
    """Return the application task queue instance.

    Defaults to InMemoryTaskQueue for development and testing.
    Override via ``app.dependency_overrides[get_task_queue]`` for
    production (CloudTasksQueue) or test doubles.
    """
    return _task_queue


def get_gemini_client() -> LLMClient:
    """Return the application LLM client instance.

    Defaults to InMemoryLLMClient for development and testing.
    Override via ``app.dependency_overrides[get_gemini_client]`` for
    production (GeminiClient) or test doubles.
    """
    return _gemini_client


__all__ = ["get_db_session", "get_gemini_client", "get_task_queue"]
