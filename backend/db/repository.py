"""Narrow write helpers used by the agent and API.

Everything here is best-effort: a failed write is logged and swallowed by
``db_session`` so it can never interrupt a live interview.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import Evidence, InterviewSession, Question, Score, Turn
from db.session import db_session


async def ensure_session(
    session_id: str,
    room_name: str,
    candidate_name: str = "Candidate",
    role_focus: str | None = None,
    resume_text: str | None = None,
    job_description: str | None = None,
    competency_plan: list[dict] | None = None,
) -> None:
    async with db_session() as db:
        if db is None:
            return
        existing = await db.get(InterviewSession, session_id)
        if existing is None:
            db.add(
                InterviewSession(
                    id=session_id,
                    room_name=room_name,
                    candidate_name=candidate_name,
                    role_focus=role_focus,
                    resume_text=resume_text,
                    job_description=job_description,
                    competency_plan=competency_plan,
                    status="created",
                )
            )
        else:
            if role_focus:
                existing.role_focus = role_focus
            if resume_text:
                existing.resume_text = resume_text
            if job_description:
                existing.job_description = job_description
            if competency_plan:
                existing.competency_plan = competency_plan


async def load_session(session_id: str) -> InterviewSession | None:
    async with db_session() as db:
        if db is None:
            return None
        return await db.get(InterviewSession, session_id)


async def mark_session_status(session_id: str, status: str) -> None:
    async with db_session() as db:
        if db is None:
            return
        row = await db.get(InterviewSession, session_id)
        if row is None:
            return
        row.status = status
        if status in {"completed", "aborted"}:
            row.ended_at = datetime.now(timezone.utc)


async def record_turn(
    session_id: str,
    turn_index: int,
    speaker: str,
    text: str,
    offset_ms: int,
    duration_ms: int | None = None,
) -> UUID | None:
    """Persist one transcript turn and return its id for score linking."""

    async with db_session() as db:
        if db is None:
            return None
        statement = (
            pg_insert(Turn)
            .values(
                session_id=session_id,
                turn_index=turn_index,
                speaker=speaker,
                text=text,
                offset_ms=offset_ms,
                duration_ms=duration_ms,
            )
            .on_conflict_do_update(
                index_elements=["session_id", "turn_index"],
                set_={
                    "speaker": speaker,
                    "text": text,
                    "offset_ms": offset_ms,
                    "duration_ms": duration_ms,
                },
            )
            .returning(Turn.id)
        )
        return await db.scalar(statement)


async def record_score(
    session_id: str,
    dimension: str,
    value: float,
    rationale: str | None = None,
    evaluator: str = "fast",
    turn_id: UUID | None = None,
    details: dict | None = None,
) -> UUID | None:
    async with db_session() as db:
        if db is None:
            return None
        score = Score(
            session_id=session_id,
            turn_id=turn_id,
            dimension=dimension,
            value=value,
            rationale=rationale,
            evaluator=evaluator,
            details=details,
        )
        db.add(score)
        await db.flush()
        return score.id


async def record_evidence(
    session_id: str,
    quote: str,
    offset_ms: int,
    demonstrates: str | None = None,
    turn_id: UUID | None = None,
    score_id: UUID | None = None,
) -> None:
    async with db_session() as db:
        if db is None:
            return
        db.add(
            Evidence(
                session_id=session_id,
                turn_id=turn_id,
                score_id=score_id,
                quote=quote,
                offset_ms=offset_ms,
                demonstrates=demonstrates,
            )
        )


async def load_transcript(session_id: str) -> list[Turn]:
    async with db_session() as db:
        if db is None:
            return []
        result = await db.execute(
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index)
        )
        return list(result.scalars().all())
    return []


async def load_scores(session_id: str) -> list[Score]:
    async with db_session() as db:
        if db is None:
            return []
        result = await db.execute(
            select(Score).where(Score.session_id == session_id).order_by(Score.created_at)
        )
        return list(result.scalars().all())
    return []


async def load_evidence(session_id: str) -> list[Evidence]:
    async with db_session() as db:
        if db is None:
            return []
        result = await db.execute(
            select(Evidence)
            .where(Evidence.session_id == session_id)
            .order_by(Evidence.offset_ms)
        )
        return list(result.scalars().all())
    return []


async def save_session_outputs(
    session_id: str,
    *,
    delivery_metrics: dict | None = None,
    integrity_observations: list[dict] | None = None,
    report: dict | None = None,
) -> None:
    async with db_session() as db:
        if db is None:
            return
        row = await db.get(InterviewSession, session_id)
        if row is None:
            return
        if delivery_metrics is not None:
            row.delivery_metrics = delivery_metrics
        if integrity_observations is not None:
            row.integrity_observations = integrity_observations
        if report is not None:
            row.report = report


async def search_questions(
    embedding: list[float],
    *,
    limit: int = 8,
) -> list[Question]:
    """Nearest question-bank entries. Returns an empty list when DB is absent."""

    async with db_session() as db:
        if db is None:
            return []
        distance = Question.embedding.cosine_distance(embedding)
        result = await db.execute(
            select(Question)
            .where(Question.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        return list(result.scalars().all())
    return []
