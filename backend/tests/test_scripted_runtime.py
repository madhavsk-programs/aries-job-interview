from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agent.tools import SessionRuntime
from evaluation.fast_evaluator import FastEvaluation
from retrieval.planner import build_question_plan


class _LocalParticipant:
    async def publish_data(self, *_args, **_kwargs) -> None:
        return None


class _Room:
    local_participant = _LocalParticipant()


class _ForbiddenGraph:
    async def ainvoke(self, _state):
        raise AssertionError("scripted recording mode must not wait for the adaptive model")


class GuidedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def _runtime(self) -> SessionRuntime:
        plan = await build_question_plan(
            role_focus="Software Developer",
            resume_text=None,
            job_description=None,
            interview_mode="linkedin_scripted",
            candidate_name="Madhav",
        )
        runtime = SessionRuntime(session_id="scripted-test", room=_Room(), plan=plan)  # type: ignore[arg-type]
        runtime.graph = _ForbiddenGraph()
        opening = plan.next_question()
        assert opening is not None
        runtime.current_question = opening.text
        runtime.current_competency = opening.competency
        runtime.current_question_type = opening.question_type
        runtime.current_difficulty = opening.difficulty
        return runtime

    async def test_core_answer_advances_in_prepared_order(self) -> None:
        runtime = await self._runtime()
        evaluation = FastEvaluation(
            relevance=0.9,
            depth=0.8,
            needs_followup=False,
            action="advance",
            reason="Concrete introduction.",
            acknowledgement="That gives me a clear picture of your background.",
            followup_question="Which part of software development interests you most?",
        )

        with (
            patch("agent.tools.evaluate_answer", new=AsyncMock(return_value=(evaluation, 10.0))),
            patch("agent.tools.repository.record_turn", new=AsyncMock(return_value=None)),
            patch("agent.tools.repository.record_score", new=AsyncMock(return_value=None)),
            patch("agent.tools.repository.record_evidence", new=AsyncMock(return_value=None)),
        ):
            reply = await runtime.score_latest_answer(
                "I am a computer-science student targeting software development roles."
            )
            await asyncio.gather(*list(runtime._tasks))

        self.assertEqual(
            reply,
            "That gives me a clear picture of your background. Your resume contains "
            "substantial AI and machine-learning work. "
            "Why are you targeting a Software Developer role?",
        )
        self.assertEqual(runtime.current_competency, "motivation")
        self.assertEqual(runtime.plan.asked, ["introduction", "motivation"])

    async def test_project_answer_gets_one_grounded_followup_then_advances(self) -> None:
        runtime = await self._runtime()
        runtime.plan.asked = ["introduction", "motivation", "project_depth"]
        project = runtime.plan.questions[2]
        runtime.current_question = project.text
        runtime.current_competency = project.competency
        runtime.current_question_type = project.question_type
        runtime.current_difficulty = project.difficulty
        first_evaluation = FastEvaluation(
            relevance=0.9,
            depth=0.8,
            needs_followup=False,
            action="advance",
            reason="The answer names concrete architecture.",
            acknowledgement="The verification step is a useful reliability detail.",
            followup_question="How did you reduce false positive review comments?",
        )
        second_evaluation = FastEvaluation(
            relevance=0.9,
            depth=0.75,
            needs_followup=False,
            action="advance",
            reason="The follow-up was answered directly.",
            acknowledgement="That explains the trade-off clearly.",
            followup_question="",
        )

        with (
            patch(
                "agent.tools.evaluate_answer",
                new=AsyncMock(side_effect=[(first_evaluation, 10.0), (second_evaluation, 10.0)]),
            ),
            patch("agent.tools.repository.record_turn", new=AsyncMock(return_value=None)),
            patch("agent.tools.repository.record_score", new=AsyncMock(return_value=None)),
            patch("agent.tools.repository.record_evidence", new=AsyncMock(return_value=None)),
        ):
            followup = await runtime.score_latest_answer(
                "I built five services and cross-checked each proposed comment against the code."
            )
            next_question = await runtime.score_latest_answer(
                "I required each finding to cite the changed line before it could be posted."
            )
            await asyncio.gather(*list(runtime._tasks))

        self.assertEqual(
            followup,
            "The verification step is a useful reliability detail. "
            "How did you reduce false positive review comments?",
        )
        self.assertIn("Tell me about a technical challenge", next_question)
        self.assertEqual(runtime.probe_counts["project_depth"], 1)
        self.assertEqual(runtime.current_competency, "problem_solving")


if __name__ == "__main__":
    unittest.main()
