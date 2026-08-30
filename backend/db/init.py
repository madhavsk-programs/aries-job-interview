"""Create the schema and seed the question bank.

    python -m db.init          create extension + tables, seed questions
    python -m db.init --drop   drop everything first (destructive)

Idempotent: safe to re-run.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from sqlalchemy import func, select, text

from db.models import Base, EMBEDDING_DIM, Question
from db.session import dispose_engine, get_engine, get_session_factory, init_models
from retrieval.question_bank import STATIC_BANK
from config import settings
from evaluation.structured import embed_texts

logger = logging.getLogger("aries.db.init")


async def migrate_question_embedding_dimension() -> bool:
    """Resize only derived question vectors when the local model dimension changes."""

    engine = get_engine()
    async with engine.begin() as conn:
        current = await conn.scalar(
            text(
                """
                SELECT a.atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'questions'
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """
            )
        )
        if current is None or int(current) == EMBEDDING_DIM:
            return False
        # Embeddings are reproducible derived data. Clearing them avoids an
        # invalid dimensional cast; the backfill below recreates them locally.
        await conn.execute(text("UPDATE questions SET embedding = NULL"))
        await conn.execute(
            text(
                f"ALTER TABLE questions ALTER COLUMN embedding "
                f"TYPE vector({EMBEDDING_DIM}) USING NULL::vector({EMBEDDING_DIM})"
            )
        )
        return True


async def seed_questions() -> int:
    """Load the static bank into Postgres if the table is empty.

    Embeddings stay NULL; Phase 3 backfills them when retrieval is wired.
    """

    factory = get_session_factory()
    async with factory() as db:
        existing = await db.scalar(select(func.count()).select_from(Question))
        if existing:
            return 0
        for item in STATIC_BANK:
            db.add(
                Question(
                    competency=item.competency,
                    question_type=item.question_type,
                    difficulty=item.difficulty,
                    text=item.text,
                )
            )
        await db.commit()
        return len(STATIC_BANK)


async def backfill_question_embeddings() -> int:
    """Embed any unindexed questions so setup can perform pgvector retrieval."""

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Question).where(Question.embedding.is_(None)))
        rows = list(result.scalars().all())
        if not rows:
            return 0
        try:
            embeddings = await embed_texts(
                [f"{row.competency} {row.question_type} {row.text}" for row in rows]
            )
        except Exception as exc:
            logger.warning("question embedding backfill skipped: %s", exc)
            return 0
        for row, embedding in zip(rows, embeddings, strict=True):
            row.embedding = embedding
        await db.commit()
        return len(rows)


async def main() -> None:
    if "--drop" in sys.argv:
        print("dropping all ARIES tables...")
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    await init_models()
    print("schema ready")
    migrated = await migrate_question_embedding_dimension()
    if migrated:
        print(f"question embedding dimension migrated to {EMBEDDING_DIM}")

    seeded = await seed_questions()
    print(f"seeded {seeded} questions" if seeded else "question bank already populated")
    embedded = await backfill_question_embeddings()
    print(f"embedded {embedded} questions" if embedded else "question embeddings already ready or skipped")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
