"""Extract verbatim, substring-verified evidence from a candidate answer."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel

from evaluation.structured import complete_json

logger = logging.getLogger("aries.eval.evidence")


class EvidenceItem(BaseModel):
    quote: str
    demonstrates: str
    dimension: str


class EvidencePayload(BaseModel):
    items: list[EvidenceItem]


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["quote", "demonstrates", "dimension"],
                "properties": {
                    "quote": {"type": "string"},
                    "demonstrates": {"type": "string"},
                    "dimension": {"type": "string"},
                },
            },
        }
    },
}


def _verified(items: list[EvidenceItem], answer: str) -> list[EvidenceItem]:
    verified: list[EvidenceItem] = []
    lowered = answer.casefold()
    for item in items:
        quote = item.quote.strip().strip('"')
        if quote and quote.casefold() in lowered:
            verified.append(item.model_copy(update={"quote": quote}))
    return verified


async def extract_evidence(question: str, answer: str, competency: str) -> list[EvidenceItem]:
    try:
        payload = await complete_json(
            name="evidence_extraction",
            schema=SCHEMA,
            instructions=(
                "Extract at most three short verbatim quotes from the candidate answer. "
                "Every quote must be an exact contiguous substring. Explain only what the "
                "words demonstrate; do not infer personality, confidence, or honesty."
            ),
            input_text=(
                f"Competency: {competency}\nQuestion: {question}\n"
                f"Candidate answer: {answer}"
            ),
            max_tokens=500,
        )
        items = EvidencePayload.model_validate(payload).items
        verified = _verified(items, answer)
        if verified:
            return verified
    except Exception as exc:  # noqa: BLE001
        logger.warning("evidence extractor unavailable: %s", exc)

    fallback = answer.strip()[:220]
    return (
        [EvidenceItem(quote=fallback, demonstrates="Candidate response", dimension=competency)]
        if fallback
        else []
    )

