from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from evaluation.fast_evaluator import evaluate_answer


class FastEvaluatorGuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_to_ten_scores_are_normalized(self) -> None:
        payload = {
            "relevance": 9,
            "depth": 8,
            "needs_followup": False,
            "action": "advance",
            "reason": "Detailed and specific.",
            "probe_hint": "",
        }
        answer = (
            "I deployed a canary, measured latency and task accuracy against a "
            "baseline, added privacy-safe failure logs, and automatically rolled "
            "back whenever either agreed production threshold was crossed."
        )
        with patch(
            "evaluation.fast_evaluator.complete_json",
            new=AsyncMock(return_value=payload),
        ):
            result, _ = await evaluate_answer("How did you operate it?", answer)

        self.assertEqual(result.relevance, 0.9)
        self.assertEqual(result.depth, 0.8)

    async def test_vague_answer_cannot_receive_perfect_advance(self) -> None:
        payload = {
            "relevance": 1.0,
            "depth": 1.0,
            "needs_followup": False,
            "action": "advance",
            "reason": "A general approach that lacks specific mechanisms.",
            "probe_hint": "",
        }
        with patch(
            "evaluation.fast_evaluator.complete_json",
            new=AsyncMock(return_value=payload),
        ):
            result, _ = await evaluate_answer(
                "How did you solve it?",
                "I would try different things and solve the problem creatively.",
                "problem_solving",
            )

        self.assertEqual(result.action, "probe")
        self.assertLessEqual(result.depth, 0.35)
        self.assertTrue(result.needs_followup)

    async def test_detailed_consistent_advance_is_preserved(self) -> None:
        payload = {
            "relevance": 0.95,
            "depth": 0.85,
            "needs_followup": False,
            "action": "advance",
            "reason": "Concrete implementation, monitoring, and trade-offs.",
            "probe_hint": "",
        }
        answer = (
            "I versioned the model and schema, deployed a five percent canary, "
            "tracked latency and task accuracy, and rolled back automatically "
            "when either metric crossed its agreed threshold in production."
        )
        with patch(
            "evaluation.fast_evaluator.complete_json",
            new=AsyncMock(return_value=payload),
        ):
            result, _ = await evaluate_answer(
                "How did you operate the AI feature?", answer, "system_design"
            )

        self.assertEqual(result.action, "advance")
        self.assertEqual(result.depth, 0.85)

    async def test_concrete_answer_overrides_an_unreasonably_harsh_probe(self) -> None:
        payload = {
            "relevance": 0.8,
            "depth": 0.5,
            "needs_followup": True,
            "action": "probe",
            "reason": "It lacks specific named monitoring products.",
            "probe_hint": "name a product",
        }
        answer = (
            "I versioned the model and schema, deployed a canary, tracked latency "
            "and quality against a baseline, protected failure logs for privacy, "
            "tested the rollback path, and rolled back whenever the agreed "
            "production threshold was crossed."
        )
        with patch(
            "evaluation.fast_evaluator.complete_json",
            new=AsyncMock(return_value=payload),
        ):
            result, _ = await evaluate_answer("How did you operate it?", answer)

        self.assertEqual(result.action, "advance")
        self.assertGreaterEqual(result.depth, 0.72)


if __name__ == "__main__":
    unittest.main()
