"""Centralized FastAPI dependencies for use with Depends()."""

from app.db.session import get_db_session
from app.services.task_queue import InMemoryTaskQueue, TaskQueue

_task_queue: TaskQueue = InMemoryTaskQueue()


def get_task_queue() -> TaskQueue:
    """Return the application task queue instance.

    Defaults to InMemoryTaskQueue for development and testing.
    Override via ``app.dependency_overrides[get_task_queue]`` for
    production (CloudTasksQueue) or test doubles.
    """
    return _task_queue


__all__ = ["get_db_session", "get_task_queue"]
