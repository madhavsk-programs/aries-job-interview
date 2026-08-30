from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from evaluation.conversation import (
    answer_candidate_request,
    classify_candidate_request,
)
from evaluation.fast_evaluator import evaluate_answer
from graph.nodes import decide
from retrieval.question_bank import QuestionPlan


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def test_repeat_and_clarification_are_not_scored_as_answers(self) -> None:
        self.assertEqual(classify_candidate_request("Could you repeat that?"), "repeat")
        self.assertEqual(
            classify_candidate_request("What do you mean by production feedback?"),
            "clarification",
        )
        self.assertEqual(
            classify_candidate_request("What is a dead letter queue?"),
            "clarification",
        )
        self.assertEqual(
            classify_candidate_request("I would begin with the API requirements."),
            "answer",
        )

    async def test_repeat_request_repeats_the_current_question(self) -> None:
        reply = await answer_candidate_request(
            request="repeat",
            current_question="How would you monitor this service?",
            candidate_text="Please repeat that.",
        )

        self.assertEqual(reply, "Of course. How would you monitor this service?")

    async def test_clarification_request_is_answered_and_rephrased(self) -> None:
        with patch(
            "evaluation.conversation.complete_json",
            new=AsyncMock(
                return_value={
                    "reply": "I’m asking how you would observe failures after deployment. In simpler terms, which signals would tell you the feature is unhealthy?"
                }
            ),
        ):
            reply = await answer_candidate_request(
                request="clarification",
                current_question="How would you monitor the production feedback loop?",
                candidate_text="What do you mean by feedback loop?",
            )

        self.assertIn("after deployment", reply)
        self.assertNotIn("ACTION", reply)

    async def test_i_do_not_know_gets_coaching_then_an_easier_question(self) -> None:
        evaluation, latency_ms = await evaluate_answer(
            "How would you design and monitor an AI feature?",
            "I don't know the answer.",
            "system_design",
        )
        state = {
            "action": evaluation.action,
            "depth": evaluation.depth,
            "competency": "system_design",
            "probe_count": 0,
            "probe_hint": evaluation.probe_hint,
            "intent": evaluation.intent,
            "acknowledgement": evaluation.acknowledgement,
            "followup_question": evaluation.followup_question,
            "coaching_note": evaluation.coaching_note,
        }
        result = decide(state, QuestionPlan())

        self.assertEqual(latency_ms, 0)
        self.assertEqual(result["action"], "clarify")
        self.assertIn("completely okay", result["directive"])
        self.assertIn("major components", result["directive"])

    async def test_second_i_do_not_know_moves_to_a_different_area(self) -> None:
        evaluation, _ = await evaluate_answer(
            "Which components would the request pass through?",
            "I still don't know.",
            "system_design",
        )
        state = {
            "action": evaluation.action,
            "depth": evaluation.depth,
            "competency": "system_design",
            "probe_count": 1,
            "intent": evaluation.intent,
            "acknowledgement": evaluation.acknowledgement,
        }
        result = decide(state, QuestionPlan())

        self.assertEqual(result["action"], "advance")
        self.assertIn("move to a different area", result["directive"])
        self.assertTrue(result["next_question"])


if __name__ == "__main__":
    unittest.main()
