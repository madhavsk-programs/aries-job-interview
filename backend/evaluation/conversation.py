"""Candidate-intent handling that should not be treated as an interview answer."""

from __future__ import annotations

import re
from typing import Literal

from evaluation.structured import complete_json

CandidateRequest = Literal["answer", "repeat", "clarification"]

_REPEAT_PATTERNS = (
    "repeat the question",
    "repeat that",
    "say that again",
    "come again",
    "couldn't hear",
    "could not hear",
)

_CLARIFICATION_PATTERNS = (
    "what do you mean",
    "what does that mean",
    "what is meant by",
    "can you explain",
    "could you explain",
    "can you clarify",
    "could you clarify",
    "are you asking",
    "do you mean",
    "can you give an example",
)

_DIRECT_QUESTION = re.compile(
    r"^(?:what (?:is|are|was|were|does)|why (?:is|are|do|does)|"
    r"how (?:do|does|can|could|would|should)|can you|could you|would you|"
    r"is there|are there)\b"
)


def classify_candidate_request(text: str) -> CandidateRequest:
    """Recognize requests that should be answered, not scored as answers."""

    normalized = re.sub(r"\s+", " ", text.lower()).strip(" .?!")
    if any(pattern in normalized for pattern in _REPEAT_PATTERNS):
        return "repeat"
    if any(pattern in normalized for pattern in _CLARIFICATION_PATTERNS):
        return "clarification"
    if _DIRECT_QUESTION.search(normalized):
        return "clarification"
    return "answer"


_REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply"],
    "properties": {"reply": {"type": "string"}},
}

_CLARIFICATION_PROMPT = """You are a supportive professional interviewer.
The candidate has asked for clarification about the current interview question.
Explain only what the question is asking in one short sentence. Do not reveal a
model answer and do not evaluate the candidate. Then restate the original
question in simpler language. The complete reply must be under 55 words and
must never contain internal labels such as ACTION, SCORE, or PROBE."""


def _safe_reply(text: str, fallback: str) -> str:
    cleaned = re.sub(r"(?i)\b(?:ACTION|SCORE|PROBE)\s*:\s*", "", text)
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return fallback
    return " ".join(cleaned.split()[:55])


async def answer_candidate_request(
    *, request: CandidateRequest, current_question: str, candidate_text: str
) -> str:
    """Answer a repeat/clarification request while keeping the current topic."""

    question = current_question or "Tell me about a project you know well."
    if request == "repeat":
        return f"Of course. {question}"

    fallback = (
        "I’m asking you to explain your own approach, the choices you made, "
        f"and the result. In simpler terms: {question}"
    )
    try:
        payload = await complete_json(
            name="candidate_question_clarification",
            schema=_REPLY_SCHEMA,
            instructions=_CLARIFICATION_PROMPT,
            input_text=(
                f"Original interview question: {question}\n"
                f"Candidate's clarification request: {candidate_text}"
            ),
            max_tokens=100,
        )
        return _safe_reply(str(payload.get("reply", "")), fallback)
    except Exception:
        return fallback
