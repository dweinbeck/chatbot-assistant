"""GitHub REST API client for fetching raw file content at a specific commit SHA."""

import httpx

_GITHUB_HEADERS_BASE = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _auth_headers(token: str) -> dict[str, str]:
    """Build GitHub API headers with Bearer auth."""
    return {**_GITHUB_HEADERS_BASE, "Authorization": f"Bearer {token}"}


async def fetch_file_content(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str,
    ref: str,
    token: str,
) -> str | None:
    """Fetch raw file content from GitHub at the given commit SHA.

    Args:
        client: Shared httpx async client (for connection pooling).
        owner: Repository owner (user or organisation).
        repo: Repository name.
        path: File path within the repository.
        ref: Git ref -- typically a commit SHA.
        token: GitHub personal access token or installation token.

    Returns:
        The raw file content as a string, or None if the file was not found (404).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses other than 404.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = await client.get(url, params={"ref": ref}, headers=headers)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.text


async def get_repo_metadata(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    token: str,
) -> dict:
    """Fetch repository metadata (id, default_branch, etc.) from GitHub.

    Returns the parsed JSON response dict.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"
    resp = await client.get(url, headers=_auth_headers(token))
    resp.raise_for_status()
    return resp.json()


async def list_repo_files(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    ref: str,
    token: str,
) -> list[str]:
    """List all file paths in a repo using the Git Tree API (recursive).

    Returns a list of file paths (blobs only, no tree entries).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}"
    resp = await client.get(
        url,
        params={"recursive": "1"},
        headers=_auth_headers(token),
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["path"] for item in data.get("tree", []) if item.get("type") == "blob"]
