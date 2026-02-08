"""Cloud Tasks abstraction with protocol-based swappable implementations.

Production code uses ``CloudTasksQueue`` which wraps the synchronous
``google-cloud-tasks`` client in ``asyncio.to_thread`` so it never blocks the
event loop.  Tests use ``InMemoryTaskQueue`` which captures enqueued tasks for
assertion without requiring a Cloud Tasks emulator.
"""

from __future__ import annotations

import asyncio
import json
from typing import Protocol


class TaskQueue(Protocol):
    """Protocol for enqueuing HTTP POST tasks."""

    async def enqueue(self, url: str, payload: dict) -> str:
        """Enqueue an HTTP POST task with a JSON body.

        Returns a task identifier string.
        """
        ...


class CloudTasksQueue:
    """Production implementation backed by Google Cloud Tasks.

    The ``google.cloud.tasks_v2`` client is imported lazily so the module can
    be loaded without the GCP SDK installed (useful in tests).
    """

    def __init__(self, project: str, location: str, queue: str) -> None:
        from google.cloud import tasks_v2

        self._client = tasks_v2.CloudTasksClient()
        self._parent = self._client.queue_path(project, location, queue)

    async def enqueue(self, url: str, payload: dict) -> str:
        """Create an HTTP POST Cloud Task and return its name."""
        from google.cloud import tasks_v2

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=url,
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload).encode(),
            ),
        )
        response = await asyncio.to_thread(
            self._client.create_task,
            tasks_v2.CreateTaskRequest(parent=self._parent, task=task),
        )
        return response.name


class InMemoryTaskQueue:
    """Test double that records enqueued tasks for assertions."""

    def __init__(self) -> None:
        self.tasks: list[dict] = []

    async def enqueue(self, url: str, payload: dict) -> str:
        """Append task to the in-memory list and return a fake task name."""
        self.tasks.append({"url": url, "payload": payload})
        return f"fake-task-{len(self.tasks)}"
