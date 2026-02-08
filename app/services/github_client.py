"""GitHub REST API client for fetching raw file content at a specific commit SHA."""

import httpx


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
