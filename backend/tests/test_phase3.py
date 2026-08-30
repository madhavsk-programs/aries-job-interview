from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.security import issue_session_token, verify_session_token
from evaluation.deep.evidence_extractor import EvidenceItem, _verified
from evaluation.deep.report_synthesizer import _build_narrative, _select_evidence
from evaluation.deep.star_evaluator import evaluate_star
from evaluation.deep.technical_evaluator import evaluate_technical
from evaluation.prosody import AudioDeliveryMonitor
from integrity.monitor import build_observations
from retrieval.question_bank import QuestionPlan


class PhaseThreeTests(unittest.TestCase):
    def test_evidence_must_be_exact_substring(self) -> None:
        answer = "I used a token bucket in Redis and measured saturation."
        items = [
            EvidenceItem(
                quote="token bucket in Redis",
                demonstrates="concrete design",
                dimension="system_design",
            ),
            EvidenceItem(
                quote="invented claim",
                demonstrates="nothing",
                dimension="system_design",
            ),
        ]
        self.assertEqual([item.quote for item in _verified(items, answer)], ["token bucket in Redis"])

    def test_session_token_is_scoped(self) -> None:
        token = issue_session_token("session-one")
        verify_session_token(token, "session-one")
        with self.assertRaises(HTTPException):
            verify_session_token(token, "session-two")

    def test_question_plan_round_trip(self) -> None:
        plan = QuestionPlan()
        restored = QuestionPlan.from_payload(plan.to_payload())
        self.assertEqual(restored.to_payload(), plan.to_payload())

    def test_integrity_is_observation_only(self) -> None:
        observations = build_observations({"longest_pause_ms": 6200, "word_count": 10})
        self.assertTrue(observations)
        text = " ".join(str(item) for item in observations).lower()
        self.assertNotIn("cheating verdict", text)
        self.assertIn("no cause or intent", text)

    def test_delivery_labels_use_transcript_counts(self) -> None:
        monitor = AudioDeliveryMonitor()
        monitor.add_transcript("Um, I used Redis, you know, for the shared state.")
        metrics = monitor.snapshot()
        self.assertGreater(metrics["word_count"], 0)
        self.assertEqual(metrics["filler_count"], 2)
        self.assertIn("do not infer", metrics["disclaimer"])

    def test_report_copy_comes_from_evaluator_details(self) -> None:
        scores = [
            {
                "id": "score-1",
                "evaluator": "technical",
                "dimension": "technical_depth",
                "value": 0.7,
                "details": {
                    "competency": "quality",
                    "strengths": ["Simulated provider failures"],
                    "missing_concepts": ["Latency thresholds"],
                },
            }
        ]

        narrative = _build_narrative(scores, [])

        self.assertEqual(narrative.strengths, ["Quality: Simulated provider failures."])
        self.assertEqual(narrative.improvements, ["Quality: add latency thresholds."])
        self.assertNotIn("collaboration", " ".join(narrative.improvements).lower())

    def test_report_selects_one_deep_quote_per_turn(self) -> None:
        scores = [
            {"id": "fast", "evaluator": "fast"},
            {"id": "deep", "evaluator": "technical"},
        ]
        evidence = [
            {"id": "a", "turn_id": "turn-1", "score_id": "fast", "quote": "fallback", "offset_ms": 10},
            {"id": "b", "turn_id": "turn-1", "score_id": "deep", "quote": "I simulated provider failures and verified route selection.", "offset_ms": 10},
        ]

        selected = _select_evidence(evidence, scores)

        self.assertEqual([item["id"] for item in selected], ["b"])


class DeepEvaluatorScaleTests(unittest.IsolatedAsyncioTestCase):
    async def test_technical_score_accepts_zero_to_ten_model_output(self) -> None:
        with patch(
            "evaluation.deep.technical_evaluator.complete_json",
            new=AsyncMock(
                return_value={
                    "score": 7,
                    "rationale": "Concrete mechanisms were described.",
                    "strengths": ["Named a verification step"],
                    "missing_concepts": [],
                    "factual_caveat": "Not externally verified.",
                }
            ),
        ):
            result = await evaluate_technical("Question", "Answer", "quality")

        self.assertEqual(result.score, 0.7)

    async def test_star_scores_accept_zero_to_ten_model_output(self) -> None:
        with patch(
            "evaluation.deep.star_evaluator.complete_json",
            new=AsyncMock(
                return_value={
                    "applicable": False,
                    "situation": 6,
                    "task": 5,
                    "action": 8,
                    "result": 7,
                    "rationale": "All four elements were present.",
                    "missing_components": [],
                }
            ),
        ):
            result = await evaluate_star("Question", "Answer", "behavioral")

        self.assertAlmostEqual(result.score, 0.65)
        self.assertTrue(result.applicable)


if __name__ == "__main__":
    unittest.main()
