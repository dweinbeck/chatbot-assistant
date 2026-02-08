"""Database session dependency for FastAPI routes."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session.

    Commits on success, rolls back on exception.

    Raises:
        RuntimeError: If the session factory has not been initialized.
    """
    if async_session_factory is None:
        msg = "Database session factory not initialized. Call init_engine() first."
        raise RuntimeError(msg)

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
