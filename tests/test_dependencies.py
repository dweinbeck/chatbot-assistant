"""Tests for the dependency initialization logic."""

from unittest.mock import patch

from app.dependencies import get_gemini_client, get_task_queue, init_production_deps


def test_init_production_deps_swaps_globals():
    """init_production_deps replaces InMemory doubles with GCP implementations."""
    with (
        patch("app.services.task_queue.CloudTasksQueue") as mock_ctq,
        patch("app.services.gemini_client.GeminiClient") as mock_gc,
    ):
        mock_ctq.return_value = mock_ctq
        mock_gc.return_value = mock_gc

        init_production_deps(
            gcp_project="test-project",
            gcp_location="us-central1",
            gemini_model="gemini-2.5-flash-lite",
            cloud_tasks_queue="indexing",
        )

        mock_ctq.assert_called_once_with("test-project", "us-central1", "indexing")
        mock_gc.assert_called_once_with("test-project", "us-central1", "gemini-2.5-flash-lite")

        assert get_task_queue() is mock_ctq
        assert get_gemini_client() is mock_gc
