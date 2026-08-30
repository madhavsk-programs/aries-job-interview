"""State passed between LangGraph nodes for a single interview turn."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Action = Literal["probe", "clarify", "advance", "wrap_up"]


class TurnState(TypedDict, total=False):
    """One trip through fast_evaluate -> decide.

    Kept deliberately small: this object is constructed and consumed while the
    candidate is waiting in silence, so it carries the decision inputs and
    nothing else. Full-session material lives in Postgres.
    """

    # --- inputs -----------------------------------------------------------
    session_id: str
    turn_index: int
    competency: str
    question: str
    answer: str
    covered: list[str]
    remaining: list[str]
    probe_count: int

    # --- produced by fast_evaluate ---------------------------------------
    relevance: float
    depth: float
    needs_followup: bool
    reason: str
    probe_hint: str
    intent: str
    acknowledgement: str
    followup_question: str
    coaching_note: str
    eval_latency_ms: float

    # --- produced by decide ----------------------------------------------
    action: Action
    next_question: str
    next_competency: str
    next_question_type: str
    next_difficulty: int
    directive: str

    # --- Phase 3 ----------------------------------------------------------
    deep_scores: dict[str, Any]
    evidence: list[dict[str, Any]]
