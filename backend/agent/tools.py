"""Realtime tools and reliable per-interview turn lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine
from uuid import UUID

from livekit import rtc

from db import repository
from evaluation.deep.coordinator import DeepTurnInput, evaluate_turn
from evaluation.deep.report_synthesizer import synthesize_report
from evaluation.conversation import (
    answer_candidate_request,
    classify_candidate_request,
)
from evaluation.fast_evaluator import evaluate_answer
from evaluation.prosody import AudioDeliveryMonitor
from graph.graph import build_turn_graph
from graph.state import TurnState
from integrity.monitor import build_observations
from observability.otel_setup import span
from retrieval.question_bank import QuestionPlan

logger = logging.getLogger("aries.tools")

EVAL_TOPIC = "aries.eval"
DEEP_EVAL_TOPIC = "aries.deep_eval"
TRANSCRIPT_TOPIC = "aries.transcript"
REPORT_TOPIC = "aries.report"
TURN_STATUS_TOPIC = "aries.turn_status"

GUIDED_FOLLOWUP_COMPETENCIES = {
    "project_depth",
    "problem_solving",
    "quality",
    "system_design",
}

GUIDED_FOLLOWUP_FALLBACKS = {
    "project_depth": "What part of that project was the hardest to make reliable?",
    "problem_solving": "How did you verify that your solution actually fixed the problem?",
    "quality": "Which metric mattered most in that example, and why?",
    "system_design": "What would you build first if you had to deliver an initial version quickly?",
}


@dataclass
class CandidateTurn:
    text: str
    turn_index: int
    offset_ms: int
    question: str
    competency: str
    question_type: str
    difficulty: int
    turn_id: UUID | None = None
    persist_task: asyncio.Task[UUID | None] | None = None
    scored: bool = False
    directive: str = ""


@dataclass
class SessionRuntime:
    session_id: str
    room: rtc.Room
    plan: QuestionPlan = field(default_factory=QuestionPlan)
    started_at: float = field(default_factory=time.monotonic)
    prosody: AudioDeliveryMonitor = field(default_factory=AudioDeliveryMonitor)

    current_question: str = ""
    current_competency: str = "role_framing"
    current_question_type: str = "opening"
    current_difficulty: int = 1
    turn_index: int = 0
    last_candidate_turn: CandidateTurn | None = None
    probe_counts: dict[str, int] = field(default_factory=dict)
    candidate_turns: list[CandidateTurn] = field(default_factory=list)
    interview_complete: bool = False

    _tasks: set[asyncio.Task[Any]] = field(default_factory=set, init=False, repr=False)
    _deep_tasks: set[asyncio.Task[Any]] = field(default_factory=set, init=False, repr=False)
    _score_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _finalize_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _finalized: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = build_turn_graph(self.plan)

    def offset_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def _next_index(self) -> int:
        self.turn_index += 1
        return self.turn_index

    def _spawn(
        self, coroutine: Coroutine[Any, Any, Any], *, deep: bool = False
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        target = self._deep_tasks if deep else self._tasks
        target.add(task)
        def _finished(completed: asyncio.Task[Any]) -> None:
            target.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error(
                    "background interview task failed: %s",
                    error,
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(_finished)
        return task

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        try:
            await self.room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"), reliable=True, topic=topic
            )
        except Exception as exc:  # UI updates must never affect the interview
            logger.debug("publish on %s failed: %s", topic, exc)

    async def _persist_turn(
        self, *, index: int, speaker: str, text: str, offset_ms: int
    ) -> UUID | None:
        turn_id = await repository.record_turn(
            session_id=self.session_id,
            turn_index=index,
            speaker=speaker,
            text=text,
            offset_ms=offset_ms,
        )
        await self.publish(
            TRANSCRIPT_TOPIC,
            {
                "speaker": speaker,
                "text": text,
                "offset_ms": offset_ms,
                "turn_index": index,
                "turn_id": str(turn_id) if turn_id else None,
            },
        )
        return turn_id

    def capture_candidate_turn(self, text: str) -> CandidateTurn:
        """Snapshot a final transcript synchronously before any tool can score it."""

        normalized = " ".join(text.split())
        previous = self.last_candidate_turn
        if previous and not previous.scored and normalized == " ".join(previous.text.split()):
            return previous

        turn = CandidateTurn(
            text=text,
            turn_index=self._next_index(),
            offset_ms=self.offset_ms(),
            question=self.current_question or "(opening question)",
            competency=self.current_competency,
            question_type=self.current_question_type,
            difficulty=self.current_difficulty,
        )
        self.last_candidate_turn = turn
        self.candidate_turns.append(turn)
        self.prosody.add_transcript(text)
        turn.persist_task = self._spawn(
            self._persist_turn(
                index=turn.turn_index,
                speaker="candidate",
                text=text,
                offset_ms=turn.offset_ms,
            )
        )
        return turn

    def capture_interviewer_turn(self, text: str) -> None:
        index = self._next_index()
        self._spawn(
            self._persist_turn(
                index=index,
                speaker="interviewer",
                text=text,
                offset_ms=self.offset_ms(),
            )
        )

    async def _run_deep(self, turn: CandidateTurn) -> None:
        try:
            evaluation_type = (
                "behavioral"
                if turn.competency in {"problem_solving", "learning"}
                else "technical"
            )
            result = await evaluate_turn(
                DeepTurnInput(
                    session_id=self.session_id,
                    turn_id=turn.turn_id,
                    turn_index=turn.turn_index,
                    offset_ms=turn.offset_ms,
                    competency=turn.competency,
                    question_type=evaluation_type,
                    question=turn.question,
                    answer=turn.text,
                )
            )
            await self.publish(DEEP_EVAL_TOPIC, result)
        except Exception as exc:  # deep work stays off the audio path
            logger.warning("deep evaluation failed for turn %s: %s", turn.turn_index, exc)

    async def _evaluate_guided_interview(self) -> None:
        """Run richer evaluators after audio ends, without adding voice latency."""

        core_turns = [
            turn
            for turn in self.candidate_turns
            if turn.scored
            and turn.turn_id is not None
            and turn.question_type == "linkedin_scripted"
        ]
        if not core_turns:
            return

        semaphore = asyncio.Semaphore(2)

        async def _evaluate(turn: CandidateTurn) -> None:
            async with semaphore:
                await self._run_deep(turn)

        await asyncio.gather(*(_evaluate(turn) for turn in core_turns))

    async def _record_guided_evaluation(
        self,
        *,
        turn: CandidateTurn,
        depth: float,
        relevance: float,
        reason: str,
        action: str,
        latency_ms: float,
    ) -> None:
        """Persist useful report data without another model call during speech."""

        score_id = await repository.record_score(
            session_id=self.session_id,
            dimension="answer_depth",
            value=depth,
            rationale=reason,
            evaluator="fast",
            turn_id=turn.turn_id,
            details={
                "relevance": relevance,
                "action": action,
                "competency": turn.competency,
                "latency_ms": round(latency_ms, 1),
            },
        )
        quote = turn.text.strip()[:220]
        if quote:
            await repository.record_evidence(
                session_id=self.session_id,
                turn_id=turn.turn_id,
                score_id=score_id,
                quote=quote,
                offset_ms=turn.offset_ms,
                demonstrates=f"Response evidence for {turn.competency.replace('_', ' ')}",
            )

    async def finalize(self) -> dict[str, Any] | None:
        async with self._finalize_lock:
            if self._finalized:
                session = await repository.load_session(self.session_id)
                return session.report if session else None
            self._finalized = True

            pending = list(self._tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            pending_deep = list(self._deep_tasks)
            if pending_deep:
                await asyncio.gather(*pending_deep, return_exceptions=True)

            await self._evaluate_guided_interview()

            delivery = self.prosody.snapshot()
            observations = build_observations(delivery)
            await repository.save_session_outputs(
                self.session_id,
                delivery_metrics=delivery,
                integrity_observations=observations,
            )
            report = await synthesize_report(self.session_id)
            await repository.mark_session_status(self.session_id, "completed")
            await self.publish(REPORT_TOPIC, {"status": "complete", "session_id": self.session_id})
            return report

    async def score_latest_answer(self, candidate_answer: str) -> str:
        """Evaluate one complete answer and return the exact safe text to speak."""

        async with self._score_lock:
            turn = self.capture_candidate_turn(candidate_answer.strip())
            if turn.scored and turn.directive:
                return turn.directive

            if turn.persist_task:
                turn.turn_id = await turn.persist_task

            candidate_request = classify_candidate_request(turn.text)
            if candidate_request != "answer":
                turn.directive = await answer_candidate_request(
                    request=candidate_request,
                    current_question=turn.question,
                    candidate_text=turn.text,
                )
                turn.scored = True
                await self.publish(
                    EVAL_TOPIC,
                    {
                        "turn_index": turn.turn_index,
                        "competency": turn.competency,
                        "action": candidate_request,
                        "reason": "Candidate requested interviewer clarification.",
                        "quote": turn.text[:220],
                        "offset_ms": turn.offset_ms,
                        "latency_ms": 0,
                    },
                )
                return turn.directive

            # Guided recording mode keeps the prepared core sequence but allows
            # one grounded follow-up on the topics where conversation adds value.
            if turn.question_type in {"linkedin_scripted", "linkedin_followup"}:
                started = time.perf_counter()
                evaluation, _ = await evaluate_answer(
                    question=turn.question,
                    answer=turn.text,
                    competency=turn.competency,
                )
                total_ms = (time.perf_counter() - started) * 1000
                is_followup = turn.question_type == "linkedin_followup"
                should_followup = not is_followup and (
                    turn.competency in GUIDED_FOLLOWUP_COMPETENCIES
                    or evaluation.action in {"probe", "clarify"}
                )

                acknowledgement = " ".join(evaluation.acknowledgement.split()[:20]).strip()
                if should_followup:
                    followup = " ".join(evaluation.followup_question.split()[:28]).strip()
                    if not followup:
                        followup = GUIDED_FOLLOWUP_FALLBACKS.get(
                            turn.competency,
                            "Could you give me one concrete detail about how you approached that?",
                        )
                    self.probe_counts[turn.competency] = 1
                    self.current_question = followup
                    self.current_question_type = "linkedin_followup"
                    turn.directive = " ".join(
                        part for part in (acknowledgement, evaluation.coaching_note, followup) if part
                    )
                    action = "probe" if evaluation.intent == "answer" else "clarify"
                else:
                    next_question = self.plan.next_question(prefer_harder=False)
                    if next_question is None:
                        turn.directive = (
                            "Thank you, Madhav. That concludes the interview. I appreciate "
                            "the detail you shared about your work and engineering approach."
                        )
                        action = "wrap_up"
                        self.interview_complete = True
                        self._spawn(
                            self.publish(TURN_STATUS_TOPIC, {"status": "complete"})
                        )
                    else:
                        self.current_question = next_question.text
                        self.current_competency = next_question.competency
                        self.current_question_type = next_question.question_type
                        self.current_difficulty = next_question.difficulty
                        turn.directive = " ".join(
                            part for part in (acknowledgement, next_question.text) if part
                        )
                        action = "advance"

                depth = float(evaluation.depth)
                relevance = float(evaluation.relevance)
                turn.scored = True
                await self._record_guided_evaluation(
                    turn=turn,
                    depth=depth,
                    relevance=relevance,
                    reason=evaluation.reason,
                    action=action,
                    latency_ms=total_ms,
                )
                self._spawn(
                    self.publish(
                        EVAL_TOPIC,
                        {
                            "turn_index": turn.turn_index,
                            "competency": turn.competency,
                            "relevance": round(relevance, 2),
                            "depth": round(depth, 2),
                            "action": action,
                            "reason": evaluation.reason,
                            "quote": turn.text[:220],
                            "offset_ms": turn.offset_ms,
                            "latency_ms": round(total_ms, 1),
                        },
                    )
                )
                logger.info(
                    "guided_answer action=%s depth=%.2f total=%.0fms",
                    action,
                    depth,
                    total_ms,
                )
                return turn.directive

            started = time.perf_counter()
            with span(
                "turn_graph",
                {
                    "session_id": self.session_id,
                    "competency": turn.competency,
                    "turn_index": turn.turn_index,
                },
            ):
                state: TurnState = await self.graph.ainvoke(
                    {
                        "session_id": self.session_id,
                        "turn_index": turn.turn_index,
                        "competency": turn.competency,
                        "question": turn.question,
                        "answer": turn.text,
                        "covered": list(self.plan.asked),
                        "remaining": [q.competency for q in self.plan.remaining],
                        "probe_count": self.probe_counts.get(turn.competency, 0),
                    }
                )

            total_ms = (time.perf_counter() - started) * 1000
            action = state.get("action", "advance")
            if action in {"probe", "clarify"}:
                self.probe_counts[turn.competency] = self.probe_counts.get(turn.competency, 0) + 1
            elif action == "advance" and state.get("next_question"):
                self.current_question = state["next_question"]
                self.current_competency = state.get("next_competency", "general")
                self.current_question_type = state.get("next_question_type", "technical")
                self.current_difficulty = int(state.get("next_difficulty", 2))

            depth = float(state.get("depth", 0.0))
            relevance = float(state.get("relevance", 0.0))
            turn.scored = True
            turn.directive = state.get("directive", "Let's move to the next question.")

            self._spawn(
                repository.record_score(
                    session_id=self.session_id,
                    dimension="answer_depth",
                    value=depth,
                    rationale=state.get("reason"),
                    evaluator="fast",
                    turn_id=turn.turn_id,
                    details={
                        "relevance": relevance,
                        "action": action,
                        "competency": turn.competency,
                        "latency_ms": round(total_ms, 1),
                    },
                )
            )
            self._spawn(
                self.publish(
                    EVAL_TOPIC,
                    {
                        "turn_index": turn.turn_index,
                        "competency": turn.competency,
                        "relevance": round(relevance, 2),
                        "depth": round(depth, 2),
                        "action": action,
                        "reason": state.get("reason", ""),
                        "quote": turn.text[:220],
                        "offset_ms": turn.offset_ms,
                        "latency_ms": round(total_ms, 1),
                    },
                )
            )
            self._spawn(self._run_deep(turn), deep=True)
            logger.info("score_answer action=%s depth=%.2f total=%.0fms", action, depth, total_ms)
            return turn.directive
