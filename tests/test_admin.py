"""Tests for the admin router endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.routers.admin import extract_text_from_html

# ---------------------------------------------------------------------------
# HTML text extraction
# ---------------------------------------------------------------------------


def test_extract_text_strips_script_and_style():
    """Script and style content is excluded from extracted text."""
    html = "<html><style>body{}</style><script>alert(1)</script><p>Hello</p></html>"
    assert extract_text_from_html(html) == "Hello"


def test_extract_text_joins_with_newlines():
    """Multiple text nodes are joined with newlines."""
    html = "<h1>Title</h1><p>Paragraph one</p><p>Paragraph two</p>"
    text = extract_text_from_html(html)
    assert "Title" in text
    assert "Paragraph one" in text
    assert "Paragraph two" in text


def test_extract_text_empty_html():
    """Empty HTML returns empty string."""
    assert extract_text_from_html("") == ""


# ---------------------------------------------------------------------------
# POST /admin/sync-repo
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sync_repo_enqueues_tasks(client, mock_task_queue):
    """sync-repo lists files, filters denylist, and enqueues index tasks."""
    with (
        patch("app.routers.admin.get_repo_metadata", new_callable=AsyncMock) as mock_meta,
        patch("app.routers.admin.list_repo_files", new_callable=AsyncMock) as mock_list,
    ):
        mock_meta.return_value = {"id": 42}
        mock_list.return_value = ["src/main.py", "README.md", "image.png"]

        resp = await client.post(
            "/admin/sync-repo",
            json={"owner": "dweinbeck", "repo": "test-repo", "ref": "main"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["repo_id"] == 42
    assert data["files_found"] == 3
    # image.png should be denied
    assert data["files_skipped_denylist"] == 1
    assert data["tasks_enqueued"] == 2
    assert len(mock_task_queue.tasks) == 2


@pytest.mark.anyio
async def test_sync_repo_all_denied(client, mock_task_queue):
    """When all files are denied, no tasks are enqueued."""
    with (
        patch("app.routers.admin.get_repo_metadata", new_callable=AsyncMock) as mock_meta,
        patch("app.routers.admin.list_repo_files", new_callable=AsyncMock) as mock_list,
    ):
        mock_meta.return_value = {"id": 99}
        mock_list.return_value = ["logo.png", "styles.min.css"]

        resp = await client.post(
            "/admin/sync-repo",
            json={"owner": "dweinbeck", "repo": "test-repo"},
        )

    data = resp.json()
    assert data["tasks_enqueued"] == 0
    assert data["files_skipped_denylist"] == 2


# ---------------------------------------------------------------------------
# POST /admin/ingest-url
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ingest_url_creates_chunks(client, mock_db_session):
    """ingest-url fetches HTML, extracts text, and creates chunks."""
    html = "<html><body><h1>Project</h1><p>Description here</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    mock_db_session.add = MagicMock()

    # Mock the execute to return no existing file
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = result_mock

    with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client_instance.get.return_value = mock_resp

        resp = await client.post(
            "/admin/ingest-url",
            json={
                "url": "https://dan-weinbeck.com/projects/personal-brand",
                "repo_owner": "dweinbeck",
                "repo_name": "personal-brand",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
    assert data["chunks_created"] >= 1


@pytest.mark.anyio
async def test_ingest_url_uses_custom_path(client, mock_db_session):
    """ingest-url respects an explicit path parameter."""
    html = "<html><body><p>Content</p></body></html>"

    mock_db_session.add = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = result_mock

    with patch("app.routers.admin.httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client_instance.get.return_value = mock_resp

        resp = await client.post(
            "/admin/ingest-url",
            json={
                "url": "https://example.com/about",
                "repo_owner": "dweinbeck",
                "repo_name": "test",
                "path": "custom/path.html",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ingested"
