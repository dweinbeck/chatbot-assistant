"""Async database engine and session factory initialization."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_engine(database_url: str) -> None:
    """Create the async engine and session factory.

    Args:
        database_url: PostgreSQL connection string using asyncpg driver.
    """
    global engine, async_session_factory  # noqa: PLW0603

    engine = create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
        echo=False,
    )

    async_session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def dispose_engine() -> None:
    """Dispose the async engine, closing all connections."""
    global engine, async_session_factory  # noqa: PLW0603

    if engine is not None:
        await engine.dispose()
        engine = None
        async_session_factory = None
