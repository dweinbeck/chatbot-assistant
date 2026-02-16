"""Repository row management for FK integrity.

Ensures a ``Repo`` row exists before creating ``KBFile`` or ``KBChunk``
records that reference it via foreign key.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Repo


async def get_or_create_repo(
    session: AsyncSession,
    repo_id: int,
    owner: str,
    name: str,
) -> Repo:
    """Return an existing Repo row or create one and flush to get its ID.

    Looks up by primary key first, then by the (owner, name) unique
    constraint to handle cases where the same repo was previously
    created with a different ID (e.g. synthetic ID from ingest-url
    vs real GitHub ID from sync-repo).
    """
    result = await session.execute(select(Repo).where(Repo.id == repo_id))
    repo = result.scalar_one_or_none()
    if repo is not None:
        return repo

    # Check by owner+name in case the repo exists with a different ID
    result = await session.execute(
        select(Repo).where(Repo.owner == owner, Repo.name == name)
    )
    repo = result.scalar_one_or_none()
    if repo is not None:
        return repo

    repo = Repo(id=repo_id, owner=owner, name=name)
    session.add(repo)
    await session.flush()
    return repo
