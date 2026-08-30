"""Off-critical-path technical depth evaluation."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from evaluation.structured import complete_json

logger = logging.getLogger("aries.eval.technical")


class TechnicalEvaluation(BaseModel):
    score: float = Field(ge=0, le=1)
    rationale: str
    strengths: list[str]
    missing_concepts: list[str]
    factual_caveat: str


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "rationale", "strengths", "missing_concepts", "factual_caveat"],
    "properties": {
        "score": {"type": "number"},
        "rationale": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "missing_concepts": {"type": "array", "items": {"type": "string"}},
        "factual_caveat": {"type": "string"},
    },
}


async def evaluate_technical(
    question: str,
    answer: str,
    competency: str,
) -> TechnicalEvaluation:
    try:
        payload = await complete_json(
            name="technical_evaluation",
            schema=SCHEMA,
            instructions=(
                "Evaluate the substantive depth of an interview answer. Reward concrete "
                "mechanisms, constraints, tradeoffs, examples, and the candidate's own "
                "actions. List important missing concepts, but do not claim that factual "
                "statements were externally verified. This is a noisy speech-to-text "
                "transcript: never penalize grammar, phrasing, fluency, articulation, or "
                "likely transcription mistakes. Score only recoverable technical substance. "
                "Never evaluate delivery or identity."
            ),
            input_text=(
                f"Competency: {competency}\nQuestion: {question}\n"
                f"Candidate answer: {answer}"
            ),
        )
        score = payload.get("score")
        if isinstance(score, (int, float)) and 1 < score <= 10:
            payload = {**payload, "score": score / 10}
        return TechnicalEvaluation.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("technical evaluator unavailable: %s", exc)
        return TechnicalEvaluation(
            score=0.5,
            rationale=f"Technical evaluation unavailable ({type(exc).__name__}).",
            strengths=[],
            missing_concepts=[],
            factual_caveat="No external factual verification was performed.",
        )
