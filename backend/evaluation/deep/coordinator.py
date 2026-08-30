"""Parallel deep evaluation and persistence for a completed answer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from db import repository
from evaluation.deep.evidence_extractor import EvidenceItem, extract_evidence
from evaluation.deep.star_evaluator import StarEvaluation, evaluate_star
from evaluation.deep.technical_evaluator import TechnicalEvaluation, evaluate_technical
from observability.otel_setup import span


@dataclass(frozen=True)
class DeepTurnInput:
    session_id: str
    turn_id: UUID | None
    turn_index: int
    offset_ms: int
    competency: str
    question_type: str
    question: str
    answer: str


async def evaluate_turn(input: DeepTurnInput) -> dict[str, Any]:
    with span(
        "deep_evaluate",
        {"session_id": input.session_id, "turn_index": input.turn_index},
    ):
        star, technical, evidence = await asyncio.gather(
            evaluate_star(input.question, input.answer, input.question_type),
            evaluate_technical(input.question, input.answer, input.competency),
            extract_evidence(input.question, input.answer, input.competency),
        )

    technical_score_id = await repository.record_score(
        session_id=input.session_id,
        turn_id=input.turn_id,
        dimension="technical_depth",
        value=technical.score,
        rationale=technical.rationale,
        evaluator="technical",
        details={
            "competency": input.competency,
            "strengths": technical.strengths,
            "missing_concepts": technical.missing_concepts,
            "factual_caveat": technical.factual_caveat,
        },
    )
    if star.applicable:
        await repository.record_score(
            session_id=input.session_id,
            turn_id=input.turn_id,
            dimension="star_structure",
            value=star.score,
            rationale=star.rationale,
            evaluator="star",
            details={
                "situation": star.situation,
                "task": star.task,
                "action": star.action,
                "result": star.result,
                "missing_components": star.missing_components,
            },
        )

    for item in evidence:
        await repository.record_evidence(
            session_id=input.session_id,
            turn_id=input.turn_id,
            score_id=technical_score_id,
            quote=item.quote,
            offset_ms=input.offset_ms,
            demonstrates=item.demonstrates,
        )

    return {
        "turn_index": input.turn_index,
        "technical": technical.model_dump(),
        "star": star.model_dump() if star.applicable else None,
        "evidence": [item.model_dump() for item in evidence],
    }

