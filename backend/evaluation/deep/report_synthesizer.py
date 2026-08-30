"""Evidence-grounded candidate report synthesis."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from db import repository


class Narrative(BaseModel):
    summary: str
    strengths: list[str]
    improvements: list[str]
    practice_plan: list[str]


def _build_narrative(
    score_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> Narrative:
    """Build report copy only from persisted evaluator outputs."""

    dimension_values: dict[str, list[float]] = {}
    for item in score_rows:
        dimension_values.setdefault(item["dimension"], []).append(float(item["value"]))
    averages = {
        name: sum(values) / len(values) for name, values in dimension_values.items()
    }

    if not averages:
        return Narrative(
            summary=(
                "The interview transcript was saved, but content evaluation was not "
                "captured for this session."
            ),
            strengths=[],
            improvements=["Run the content evaluators before treating this report as complete."],
            practice_plan=["Repeat or rebuild the evaluation from the saved transcript."],
        )

    technical = sorted(
        (item for item in score_rows if item["evaluator"] == "technical"),
        key=lambda item: float(item["value"]),
        reverse=True,
    )
    strongest_row = technical[0] if technical else max(
        score_rows, key=lambda item: float(item["value"])
    )
    weakest_row = technical[-1] if technical else min(
        score_rows, key=lambda item: float(item["value"])
    )
    strongest_competency = str(
        strongest_row.get("details", {}).get("competency")
        or strongest_row["dimension"]
    ).replace("_", " ")
    weakest_competency = str(
        weakest_row.get("details", {}).get("competency")
        or weakest_row["dimension"]
    ).replace("_", " ")

    strengths: list[str] = []
    for item in technical:
        label = str(item.get("details", {}).get("competency") or "answer").replace("_", " ")
        available = item.get("details", {}).get("strengths", [])
        if available:
            sentence = f"{label.capitalize()}: {str(available[0]).strip().rstrip('.')}."
            if sentence not in strengths:
                strengths.append(sentence)
        if len(strengths) == 3:
            break
    if not strengths:
        strengths.append(
            f"Your strongest scored area was {strongest_competency} "
            f"({float(strongest_row['value']):.2f})."
        )

    improvements: list[str] = []
    practice_plan: list[str] = []
    for item in reversed(technical):
        label = str(item.get("details", {}).get("competency") or "answer").replace("_", " ")
        for concept in item.get("details", {}).get("missing_concepts", [])[:1]:
            cleaned = str(concept).strip().rstrip(".")
            lowered = cleaned[:1].lower() + cleaned[1:]
            sentence = f"{label.capitalize()}: add {lowered}." if cleaned else ""
            if sentence and sentence not in improvements:
                improvements.append(sentence)
                practice_plan.append(
                    f"Re-answer the {label} question and explicitly address "
                    f"{lowered}."
                )
        if len(improvements) == 3:
            break
    if not improvements:
        improvements.append(
            f"Prioritize {weakest_competency}, currently your lowest scored content area "
            f"({float(weakest_row['value']):.2f})."
        )
        practice_plan.append(
            f"Re-answer one {weakest_competency} question with a concrete action and measurable result."
        )
    practice_plan.append("Compare each revised answer with its linked evidence excerpt.")

    return Narrative(
        summary=(
            f"Across {len(technical) or len(score_rows)} evaluated answers, your strongest "
            f"content area was {strongest_competency} ({float(strongest_row['value']):.2f}); "
            f"the clearest development area was {weakest_competency} "
            f"({float(weakest_row['value']):.2f}). Review the linked excerpts for context."
        ),
        strengths=strengths,
        improvements=improvements,
        practice_plan=practice_plan[:4],
    )


def _select_evidence(
    evidence_rows: list[dict[str, Any]], score_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Show one concise supporting quote per answer, preferring deep evidence."""

    evaluator_by_score = {item["id"]: item["evaluator"] for item in score_rows}
    ordered = sorted(
        evidence_rows,
        key=lambda item: (
            evaluator_by_score.get(item.get("score_id")) != "technical",
            not (30 <= len(str(item.get("quote") or "")) <= 180),
            item["offset_ms"],
        ),
    )
    selected: list[dict[str, Any]] = []
    seen_turns: set[str | None] = set()
    for item in ordered:
        turn_id = item.get("turn_id")
        if turn_id in seen_turns:
            continue
        seen_turns.add(turn_id)
        selected.append(item)
    return sorted(selected, key=lambda item: item["offset_ms"])


async def synthesize_report(session_id: str) -> dict[str, Any]:
    session = await repository.load_session(session_id)
    turns = await repository.load_transcript(session_id)
    scores = await repository.load_scores(session_id)
    evidence = await repository.load_evidence(session_id)
    delivery = (session.delivery_metrics if session else None) or {}
    observations = (session.integrity_observations if session else None) or []

    evidence_rows = [
        {
            "id": str(item.id),
            "turn_id": str(item.turn_id) if item.turn_id else None,
            "score_id": str(item.score_id) if item.score_id else None,
            "quote": item.quote,
            "offset_ms": item.offset_ms,
            "demonstrates": item.demonstrates,
        }
        for item in evidence
    ]
    score_rows = [
        {
            "id": str(item.id),
            "turn_id": str(item.turn_id) if item.turn_id else None,
            "dimension": item.dimension,
            "value": round(item.value, 3),
            "rationale": item.rationale,
            "evaluator": item.evaluator,
            "details": item.details or {},
        }
        for item in scores
    ]
    evidence_rows = _select_evidence(evidence_rows, score_rows)
    transcript_rows = [
        {
            "id": str(item.id),
            "turn_index": item.turn_index,
            "speaker": item.speaker,
            "text": item.text,
            "offset_ms": item.offset_ms,
        }
        for item in turns
    ]

    narrative = _build_narrative(score_rows, evidence_rows)

    dimension_values: dict[str, list[float]] = {}
    for item in scores:
        dimension_values.setdefault(item.dimension, []).append(item.value)
    dimensions = {
        name: round(sum(values) / len(values), 3)
        for name, values in dimension_values.items()
    }

    report = {
        "session_id": session_id,
        "status": "complete",
        "role_focus": session.role_focus if session else None,
        "summary": narrative.summary,
        "strengths": narrative.strengths,
        "improvements": narrative.improvements,
        "practice_plan": narrative.practice_plan,
        "dimensions": dimensions,
        "scores": score_rows,
        "evidence": evidence_rows,
        "delivery": delivery,
        "integrity_observations": observations,
        "transcript": transcript_rows,
        "disclaimer": (
            "This report is practice feedback, not a hiring verdict. Delivery metrics "
            "describe pace, fillers, and pauses only."
        ),
    }
    await repository.save_session_outputs(session_id, report=report)
    return report
