from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from backend.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

async_session_maker = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

Base = declarative_base()

# ---------------------------------------------------------------------------
# Dependency injection helper
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession and commits on success."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Table initialisation
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Create all tables defined in the metadata (idempotent)."""
    # Import models here so that their classes are registered on Base.metadata
    # before we call create_all.
    import backend.knowledge.models  # noqa: F401  # side-effect import

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
