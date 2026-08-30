"""Async engine and session factory.

The voice loop must survive a missing database: if Postgres is unreachable the
agent logs and keeps talking rather than dropping the call. Persistence is a
recording of the interview, not a precondition for it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config import settings
from db.models import Base

logger = logging.getLogger("aries.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            # LiveKit may execute consecutive jobs on different asyncio event
            # loops. A pooled asyncpg connection belongs to the loop that
            # created it, so reusing it in the next job raises "Future attached
            # to a different loop". NullPool gives every operation a fresh,
            # loop-local connection, which is appropriate for this local app.
            poolclass=NullPool,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession | None]:
    """Yield a session, or ``None`` when persistence is off or unreachable.

    Callers treat ``None`` as "skip the write" so a database outage degrades
    the recording instead of the interview.
    """

    if not settings.persistence_enabled:
        yield None
        return

    factory = get_session_factory()
    session: AsyncSession | None = None
    try:
        session = factory()
        yield session
        await session.commit()
    except Exception:  # noqa: BLE001 - persistence is best-effort by design
        logger.exception("database write failed; continuing without persistence")
        if session is not None:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001 - cleanup must not drop a call
                logger.debug("database rollback failed during cleanup", exc_info=True)
    finally:
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001 - cleanup must not drop a call
                logger.debug("database session close failed", exc_info=True)


async def init_models() -> None:
    """Create the pgvector extension and every table that does not exist yet."""

    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # ``create_all`` does not alter an existing development schema. These
        # additive statements keep pre-Phase-3 databases usable without asking
        # a user to drop their transcripts.
        for statement in (
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS resume_text TEXT",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS job_description TEXT",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS competency_plan JSONB",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS delivery_metrics JSONB",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS integrity_observations JSONB",
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS report JSONB",
            "ALTER TABLE questions ADD COLUMN IF NOT EXISTS role_family VARCHAR(80)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_turns_session_index ON turns (session_id, turn_index)",
        ):
            await conn.execute(text(statement))
    logger.info("database schema ready")


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
