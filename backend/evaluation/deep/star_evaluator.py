"""Off-critical-path STAR structure evaluation."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from evaluation.structured import complete_json

logger = logging.getLogger("aries.eval.star")


class StarEvaluation(BaseModel):
    applicable: bool
    situation: float = Field(ge=0, le=1)
    task: float = Field(ge=0, le=1)
    action: float = Field(ge=0, le=1)
    result: float = Field(ge=0, le=1)
    rationale: str
    missing_components: list[str]

    @property
    def score(self) -> float:
        if not self.applicable:
            return 0.0
        return (self.situation + self.task + self.action + self.result) / 4


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "applicable", "situation", "task", "action", "result",
        "rationale", "missing_components",
    ],
    "properties": {
        "applicable": {"type": "boolean"},
        "situation": {"type": "number"},
        "task": {"type": "number"},
        "action": {"type": "number"},
        "result": {"type": "number"},
        "rationale": {"type": "string"},
        "missing_components": {"type": "array", "items": {"type": "string"}},
    },
}


async def evaluate_star(question: str, answer: str, question_type: str) -> StarEvaluation:
    if question_type not in {"behavioral", "behavioural"}:
        return StarEvaluation(
            applicable=False,
            situation=0,
            task=0,
            action=0,
            result=0,
            rationale="STAR is not applied to this question type.",
            missing_components=[],
        )
    try:
        payload = await complete_json(
            name="star_evaluation",
            schema=SCHEMA,
            instructions=(
                "Evaluate only the structure of a behavioral interview answer using "
                "Situation, Task, Action, Result. Do not judge accent, personality, "
                "confidence, honesty, or identity. Scores are 0 to 1."
            ),
            input_text=f"Question: {question}\nCandidate answer: {answer}",
        )
        normalized = dict(payload)
        normalized["applicable"] = True
        for field in ("situation", "task", "action", "result"):
            value = normalized.get(field)
            if isinstance(value, (int, float)) and 1 < value <= 10:
                normalized[field] = value / 10
        return StarEvaluation.model_validate(normalized)
    except Exception as exc:  # noqa: BLE001
        logger.warning("STAR evaluator unavailable: %s", exc)
        return StarEvaluation(
            applicable=True,
            situation=0.5,
            task=0.5,
            action=0.5,
            result=0.5,
            rationale=f"STAR evaluation unavailable ({type(exc).__name__}).",
            missing_components=[],
        )
