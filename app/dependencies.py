"""Centralized FastAPI dependencies for use with Depends()."""

from app.db.session import get_db_session
from app.services.gemini_client import InMemoryLLMClient, LLMClient
from app.services.task_queue import InMemoryTaskQueue, TaskQueue

_task_queue: TaskQueue = InMemoryTaskQueue()
_gemini_client: LLMClient = InMemoryLLMClient()


def init_production_deps(
    gcp_project: str,
    gcp_location: str,
    gemini_model: str,
    cloud_tasks_queue: str,
) -> None:
    """Swap InMemory test doubles for real GCP-backed implementations.

    Uses lazy imports so the module loads without GCP SDKs installed.
    """
    global _task_queue, _gemini_client  # noqa: PLW0603

    from app.services.gemini_client import GeminiClient
    from app.services.task_queue import CloudTasksQueue

    _task_queue = CloudTasksQueue(gcp_project, gcp_location, cloud_tasks_queue)
    _gemini_client = GeminiClient(gcp_project, gcp_location, gemini_model)


def get_task_queue() -> TaskQueue:
    """Return the application task queue instance.

    Defaults to InMemoryTaskQueue for development and testing.
    Swapped to production implementations by ``init_production_deps()``.
    """
    return _task_queue


def get_gemini_client() -> LLMClient:
    """Return the application LLM client instance.

    Defaults to InMemoryLLMClient for development and testing.
    Swapped to production implementations by ``init_production_deps()``.
    """
    return _gemini_client


__all__ = [
    "get_db_session",
    "get_gemini_client",
    "get_task_queue",
    "init_production_deps",
]
