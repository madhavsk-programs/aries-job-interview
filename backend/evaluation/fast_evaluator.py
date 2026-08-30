"""The one evaluation that is allowed to sit on the conversational critical path.

Everything here is budgeted in milliseconds. It answers exactly one question --
"what should the interviewer do next?" -- and nothing else. Rubric scoring,
evidence extraction and STAR analysis are deliberately excluded; they run in the
deep path where latency does not matter.
"""

from __future__ import annotations

import logging
import re
import time

from pydantic import BaseModel, Field

from config import settings
from evaluation.structured import complete_json
from observability.otel_setup import span

logger = logging.getLogger("aries.eval.fast")


class FastEvaluation(BaseModel):
    """Minimum decision payload. Anything richer belongs off the critical path."""

    relevance: float = Field(ge=0.0, le=1.0)
    depth: float = Field(ge=0.0, le=1.0)
    needs_followup: bool
    action: str  # probe | clarify | advance
    reason: str
    probe_hint: str = ""
    intent: str = "answer"  # answer | no_answer
    acknowledgement: str = ""
    followup_question: str = ""
    coaching_note: str = ""

    @property
    def label(self) -> str:
        if self.depth >= 0.7:
            return "strong"
        if self.depth >= 0.4:
            return "partial"
        return "thin"


SYSTEM_PROMPT = """You are the routing evaluator inside a live voice interview.
You are on the critical path: the interviewer is silent until you answer, so be
decisive and brief.

Given the question asked and the candidate's spoken answer, judge:
- relevance: did the answer address the question that was actually asked?
- depth: did it include concrete specifics (mechanisms, trade-offs, numbers,
  named tools, the candidate's own actions) rather than generalities?

Then choose exactly one action:
- "probe"   -> the answer is on-topic but under-specified; go deeper on it.
- "clarify" -> the answer was off-topic, contradictory, or too short to read.
- "advance" -> the competency is adequately demonstrated; move to a new area.

probe_hint: when action is probe or clarify, one short phrase naming the exact
thing to ask about, drawn from words the candidate actually used. Empty
otherwise.

Also write the candidate-facing conversational material:
- acknowledgement: one short, neutral sentence spoken directly to the person
  using "you" or "your". Never say "the candidate", invent a detail, or give a score.
- followup_question: always provide one possible short, natural follow-up based
  on the candidate's actual words. It may be used even when the answer is good.
- coaching_note: empty for a normal answer.
- intent: "answer".

Judge the substance of the answer only. Never judge accent, fluency,
personality, confidence, or honesty."""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "relevance",
        "depth",
        "needs_followup",
        "action",
        "reason",
        "probe_hint",
        "intent",
        "acknowledgement",
        "followup_question",
        "coaching_note",
    ],
    "properties": {
        "relevance": {"type": "number"},
        "depth": {"type": "number"},
        "needs_followup": {"type": "boolean"},
        "action": {"type": "string", "enum": ["probe", "clarify", "advance"]},
        "reason": {"type": "string"},
        "probe_hint": {"type": "string"},
        "intent": {"type": "string", "enum": ["answer", "no_answer"]},
        "acknowledgement": {"type": "string"},
        "followup_question": {"type": "string"},
        "coaching_note": {"type": "string"},
    },
}


def _fallback(reason: str) -> FastEvaluation:
    """On any failure, keep the conversation moving rather than stalling it."""

    return FastEvaluation(
        relevance=0.5,
        depth=0.5,
        needs_followup=False,
        action="advance",
        reason=reason,
        probe_hint="",
        acknowledgement="Thanks—that gives me useful context.",
    )


def _is_no_answer(answer: str) -> bool:
    normalized = re.sub(r"[^a-z0-9' ]", " ", answer.lower())
    normalized = " ".join(normalized.split())
    patterns = (
        r"\bi(?: still| really| honestly)? (?:do not|don't) know\b",
        r"\bi have no idea\b",
        r"\bi(?:'m| am) not sure\b",
        r"\bi cannot answer\b",
        r"\bi can't answer\b",
        r"\bi don't remember\b",
        r"\bno idea\b",
        r"\bnot sure how to answer\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _coaching_for(competency: str) -> tuple[str, str]:
    guidance = {
        "resume_alignment": (
            "A good answer can use any project you remember clearly: your task, your contribution, and its result.",
            "Choose one project you know well—what did you personally build or improve?",
        ),
        "technical_depth": (
            "Start with one tool, the problem it solved, and one technical choice you made.",
            "Pick one technology you used often—what specific task did you use it for?",
        ),
        "problem_solving": (
            "A useful structure is the problem, your first diagnostic step, the change you made, and how you verified it.",
            "Think of one bug or obstacle—what was the first step you took to investigate it?",
        ),
        "system_design": (
            "Start with requirements, then name the main components, data flow, failure handling, and monitoring.",
            "Starting with one user request, which major components should it pass through?",
        ),
        "decision_making": (
            "Choose a real trade-off between two approaches and explain the constraint that decided it.",
            "Can you name one choice between two approaches and what made you choose one?",
        ),
        "collaboration": (
            "Use a specific disagreement, what you said or did, and how the team reached a decision.",
            "Can you recall one small disagreement and what you personally did next?",
        ),
        "ownership": (
            "Describe the result, what you owned, and the concrete change you made afterward.",
            "Can you recall one result you wanted to improve and what you changed next?",
        ),
    }
    return guidance.get(
        competency,
        (
            "Break the answer into the situation, your action, and the result.",
            "What is one small example you can use to answer this question?",
        ),
    )


def _apply_consistency_guardrails(
    evaluation: FastEvaluation, answer: str
) -> FastEvaluation:
    """Correct internally contradictory outputs from compact local models."""

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+#.-]*", answer)
    reason = evaluation.reason.lower()
    vague_reason = any(
        marker in reason
        for marker in (
            "lacks specific",
            "lack specific",
            "without specific",
            "too general",
            "general approach",
            "vague",
            "under-specified",
        )
    )
    specificity_terms = {
        "baseline",
        "because",
        "cache",
        "canary",
        "database",
        "deployed",
        "implemented",
        "latency",
        "measured",
        "metric",
        "monitored",
        "privacy",
        "rollback",
        "schema",
        "tested",
        "threshold",
        "tracked",
        "trade-off",
        "versioned",
        "microservice",
        "microservices",
        "github",
        "fastapi",
        "aws",
        "api",
        "apis",
        "accuracy",
        "authentication",
        "kubernetes",
        "terraform",
        "docker",
        "fallback",
        "failure",
        "failover",
        "health",
        "logging",
        "ocr",
        "postgresql",
        "react",
        "records",
        "recovery",
        "simulated",
        "sql",
        "tesseract",
        "traffic",
    }
    answer_terms = {word.lower() for word in words}
    specificity_score = len(answer_terms & specificity_terms) + int(
        bool(re.search(r"\b\d+(?:\.\d+)?%?\b", answer))
    )

    if len(words) < 8:
        return evaluation.model_copy(
            update={
                "depth": min(evaluation.depth, 0.15),
                "needs_followup": True,
                "action": "clarify",
                "probe_hint": "what you personally did",
            }
        )

    # Do not let a compact model demand arbitrary named products when the
    # answer already contains several concrete mechanisms and verification
    # details. This was the source of needless repeated probing.
    if len(words) >= 28 and specificity_score >= 4 and evaluation.relevance >= 0.5:
        return evaluation.model_copy(
            update={
                "depth": max(evaluation.depth, 0.72),
                "needs_followup": False,
                "action": "advance",
                "reason": "Answer includes multiple concrete mechanisms and verification details.",
                "probe_hint": "",
            }
        )

    if len(words) < 20 or vague_reason:
        hint = evaluation.probe_hint.strip()
        if not hint or len(hint.split()) > 12:
            hint = "the specific steps you personally took"
        return evaluation.model_copy(
            update={
                "depth": min(evaluation.depth, 0.35),
                "needs_followup": True,
                "action": "probe" if evaluation.relevance >= 0.35 else "clarify",
                "probe_hint": hint,
            }
        )

    if evaluation.action == "advance" and evaluation.depth < 0.45:
        return evaluation.model_copy(
            update={
                "needs_followup": True,
                "action": "probe",
                "probe_hint": evaluation.probe_hint or "the implementation details",
            }
        )
    return evaluation


def _normalize_score_scale(payload: dict) -> dict:
    """Accept the occasional 0–10 score emitted by small local models."""

    normalized = dict(payload)
    for field in ("relevance", "depth"):
        value = normalized.get(field)
        if isinstance(value, (int, float)) and 1 < value <= 10:
            normalized[field] = value / 10
    return normalized


async def evaluate_answer(
    question: str,
    answer: str,
    competency: str = "general",
) -> tuple[FastEvaluation, float]:
    """Score one answer. Returns the evaluation and its wall-clock latency in ms."""

    if _is_no_answer(answer):
        coaching_note, easier_question = _coaching_for(competency)
        return (
            FastEvaluation(
                relevance=0.1,
                depth=0.05,
                needs_followup=True,
                action="clarify",
                reason="Candidate explicitly said they do not know the answer.",
                probe_hint="",
                intent="no_answer",
                acknowledgement="That’s completely okay.",
                coaching_note=coaching_note,
                followup_question=easier_question,
            ),
            0.0,
        )

    if len(answer.strip()) < 12:
        return (
            FastEvaluation(
                relevance=0.2,
                depth=0.1,
                needs_followup=True,
                action="clarify",
                reason="Answer too short to assess.",
                probe_hint="ask the candidate to expand",
                acknowledgement="I only caught a very short answer.",
                followup_question="Could you expand on that with one example?",
            ),
            0.0,
        )

    started = time.perf_counter()
    with span(
        "fast_evaluate",
        {"competency": competency, "model": settings.ollama_fast_model},
    ):
        try:
            payload = await complete_json(
                name="fast_evaluation",
                schema=RESPONSE_SCHEMA,
                instructions=SYSTEM_PROMPT,
                input_text=(
                    f"Competency under test: {competency}\n"
                    f"Question asked: {question}\n"
                    f"Candidate answer (transcribed speech): {answer}"
                ),
                max_tokens=320,
                model=settings.ollama_fast_model,
            )
            evaluation = _apply_consistency_guardrails(
                FastEvaluation.model_validate(_normalize_score_scale(payload)), answer
            )
            if "candidate" in evaluation.acknowledgement.casefold():
                evaluation = evaluation.model_copy(
                    update={"acknowledgement": "That gives me useful context about your work."}
                )
        except Exception as exc:  # noqa: BLE001 - never stall the interview
            logger.warning("fast evaluator failed, advancing: %s", exc)
            evaluation = _apply_consistency_guardrails(
                _fallback(f"evaluator unavailable ({type(exc).__name__})"), answer
            )

    latency_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "fast_evaluate action=%s depth=%.2f latency=%.0fms",
        evaluation.action,
        evaluation.depth,
        latency_ms,
    )
    return evaluation, latency_ms
