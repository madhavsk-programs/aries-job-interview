"""SQLAlchemy models for interview sessions, transcripts, scores and evidence.

The schema is written once, in Phase 2, so that Phase 3 (deep evaluators,
evidence extraction, question-bank retrieval) can be added without a migration
that rewrites the transcript tables.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


class InterviewSession(Base):
    """One interview run. Keyed by the same id the frontend routes on."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    room_name: Mapped[str] = mapped_column(String(120), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(120), default="Candidate")
    role_focus: Mapped[str | None] = mapped_column(String(160), default=None)
    status: Mapped[str] = mapped_column(String(24), default="created")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    resume_text: Mapped[str | None] = mapped_column(Text, default=None)
    job_description: Mapped[str | None] = mapped_column(Text, default=None)
    competency_plan: Mapped[list | None] = mapped_column(JSONB, default=None)
    delivery_metrics: Mapped[dict | None] = mapped_column(JSONB, default=None)
    integrity_observations: Mapped[list | None] = mapped_column(JSONB, default=None)
    report: Mapped[dict | None] = mapped_column(JSONB, default=None)

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Turn.turn_index",
    )
    scores: Mapped[list["Score"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Turn(Base):
    """A single spoken turn, by either side of the conversation.

    ``offset_ms`` is measured from session start, which is what makes a score
    clickable back to the exact transcript moment that produced it.
    """

    __tablename__ = "turns"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False)  # interviewer|candidate
    text: Mapped[str] = mapped_column(Text, nullable=False)
    offset_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[InterviewSession] = relationship(back_populates="turns")
    scores: Mapped[list["Score"]] = relationship(
        back_populates="turn", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", name="uq_turns_session_index"),
        Index("ix_turns_session_index", "session_id", "turn_index"),
    )


class Score(Base):
    """One rubric dimension scored against one turn.

    ``evaluator`` records which path produced it ("fast" on the critical path,
    "star"/"technical" off it) so latency analysis can separate the two.
    """

    __tablename__ = "scores"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), default=None
    )
    dimension: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    evaluator: Mapped[str] = mapped_column(String(24), default="fast")
    details: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[InterviewSession] = relationship(back_populates="scores")
    turn: Mapped[Turn | None] = relationship(back_populates="scores")


class Evidence(Base):
    """A verbatim quote that justifies a score. Phase 3 populates this."""

    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("turns.id", ondelete="CASCADE"), default=None
    )
    score_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scores.id", ondelete="CASCADE"), default=None
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    offset_ms: Mapped[int] = mapped_column(Integer, default=0)
    demonstrates: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Question(Base):
    """Question bank. ``embedding`` stays NULL until Phase 3 wires retrieval."""

    __tablename__ = "questions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    competency: Mapped[str] = mapped_column(String(64), nullable=False)
    question_type: Mapped[str] = mapped_column(String(24), default="technical")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    role_family: Mapped[str | None] = mapped_column(String(80), default=None)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), default=None
    )

    __table_args__ = (Index("ix_questions_competency", "competency"),)
