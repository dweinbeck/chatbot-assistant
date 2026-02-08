"""Tests for the InMemoryTaskQueue test double."""

import pytest

from app.services.task_queue import InMemoryTaskQueue


@pytest.mark.asyncio
async def test_in_memory_queue_enqueue() -> None:
    """Enqueuing a single task stores it with correct url and payload."""
    queue = InMemoryTaskQueue()
    task_name = await queue.enqueue(
        "https://example.com/tasks/index-file",
        {"repo_id": 1, "path": "src/main.py"},
    )

    assert task_name == "fake-task-1"
    assert len(queue.tasks) == 1
    assert queue.tasks[0]["url"] == "https://example.com/tasks/index-file"
    assert queue.tasks[0]["payload"] == {"repo_id": 1, "path": "src/main.py"}


@pytest.mark.asyncio
async def test_in_memory_queue_multiple_enqueue() -> None:
    """Enqueuing multiple tasks assigns sequential fake names."""
    queue = InMemoryTaskQueue()
    names = []
    for i in range(3):
        name = await queue.enqueue(
            f"https://example.com/tasks/{i}",
            {"index": i},
        )
        names.append(name)

    assert names == ["fake-task-1", "fake-task-2", "fake-task-3"]
    assert len(queue.tasks) == 3


@pytest.mark.asyncio
async def test_in_memory_queue_starts_empty() -> None:
    """A freshly created queue has no tasks."""
    queue = InMemoryTaskQueue()

    assert queue.tasks == []
