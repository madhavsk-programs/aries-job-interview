"""Graph nodes.

The split that matters is between ``fast_evaluate``/``decide`` -- which run
while the candidate is waiting -- and ``deep_evaluate``/``final_report``, which
must never touch the conversational critical path.
"""

from __future__ import annotations

import re

from evaluation.fast_evaluator import evaluate_answer
from graph.state import TurnState
from retrieval.question_bank import QuestionPlan

# Depth at or above this counts as demonstrating the competency well enough to
# move on even when the evaluator asked for a follow-up.
STRONG_DEPTH = 0.7


async def fast_evaluate(state: TurnState) -> TurnState:
    """Score the answer just given. This is the only synchronous LLM hop."""

    evaluation, latency_ms = await evaluate_answer(
        question=state.get("question", ""),
        answer=state.get("answer", ""),
        competency=state.get("competency", "general"),
    )
    return {
        "relevance": evaluation.relevance,
        "depth": evaluation.depth,
        "needs_followup": evaluation.needs_followup,
        "reason": evaluation.reason,
        "probe_hint": evaluation.probe_hint,
        "intent": evaluation.intent,
        "acknowledgement": evaluation.acknowledgement,
        "followup_question": evaluation.followup_question,
        "coaching_note": evaluation.coaching_note,
        "action": evaluation.action,  # provisional; decide() may override
        "eval_latency_ms": latency_ms,
    }


def _clean_spoken(text: str, *, max_words: int = 40) -> str:
    text = re.sub(
        r"(?i)\b(?:ACTION|SCORE|PROBE)\s*:\s*", "", text or ""
    )
    return " ".join(text.split()[:max_words]).strip()


def _directive(
    action: str,
    hint: str,
    question: str,
    competency: str,
    *,
    acknowledgement: str = "",
    followup_question: str = "",
    coaching_note: str = "",
    intent: str = "answer",
) -> str:
    """Return the exact candidate-facing sentence to speak next.

    Control labels used to be returned to the conversational model here. A
    small local model could read those labels aloud (``ACTION: PROBE``), so the
    graph now produces speech-safe text and the worker speaks it directly.
    """

    acknowledgement = _clean_spoken(acknowledgement, max_words=24)
    followup_question = _clean_spoken(followup_question, max_words=32)
    coaching_note = _clean_spoken(coaching_note, max_words=34)

    if action == "clarify" and intent == "no_answer":
        return " ".join(
            part
            for part in (
                acknowledgement or "That’s completely okay.",
                coaching_note,
                followup_question,
            )
            if part
        )
    if action == "clarify":
        target = hint or "what they actually meant"
        followup = followup_question or f"Could you clarify {target} with one concrete example?"
        return " ".join(part for part in (acknowledgement, followup) if part)
    if action == "probe":
        target = hint or "the most specific thing they mentioned"
        followup = followup_question or f"Could you go one level deeper on {target}?"
        return " ".join(part for part in (acknowledgement, followup) if part)
    if action == "wrap_up":
        return "Thank you—that completes the interview. Your report is being generated now."
    transition = (
        "No problem—we’ll move to a different area."
        if intent == "no_answer"
        else acknowledgement
    )
    return " ".join(part for part in (transition, question) if part)


def decide(state: TurnState, plan: QuestionPlan) -> TurnState:
    """Turn a score into the interviewer's next move.

    This is the node the whole 'adaptive' claim rests on, so the policy is
    explicit and inspectable rather than buried in a prompt:

    * thin or off-topic answer -> clarify
    * on-topic but shallow, and this competency has not been probed -> probe
    * otherwise -> advance, and a strong answer skips ahead to a harder item
    """

    action = state.get("action", "advance")
    depth = state.get("depth", 0.5)
    competency = state.get("competency", "general")

    # A strong answer is never worth another probe, whatever the evaluator said.
    if action == "probe" and depth >= STRONG_DEPTH:
        action = "advance"

    # One focused follow-up is useful; an unlimited series is an interview
    # dead-end. After one probe/clarification on the competency, advance.
    if action in {"probe", "clarify"} and state.get("probe_count", 0) >= 1:
        action = "advance"

    if action in {"probe", "clarify"}:
        return {
            "action": action,
            "next_question": "",
            "next_competency": competency,
            "next_question_type": "",
            "next_difficulty": 0,
            "directive": _directive(
                action,
                state.get("probe_hint", ""),
                "",
                competency,
                acknowledgement=state.get("acknowledgement", ""),
                followup_question=state.get("followup_question", ""),
                coaching_note=state.get("coaching_note", ""),
                intent=state.get("intent", "answer"),
            ),
        }

    question = plan.next_question(prefer_harder=depth >= STRONG_DEPTH)
    if question is None:
        return {
            "action": "wrap_up",
            "next_question": "",
            "next_competency": "",
            "next_question_type": "",
            "next_difficulty": 0,
            "directive": _directive("wrap_up", "", "", ""),
        }

    return {
        "action": "advance",
        "next_question": question.text,
        "next_competency": question.competency,
        "next_question_type": question.question_type,
        "next_difficulty": question.difficulty,
        "directive": _directive(
            "advance",
            "",
            question.text,
            question.competency,
            acknowledgement=state.get("acknowledgement", ""),
            intent=state.get("intent", "answer"),
        ),
    }
