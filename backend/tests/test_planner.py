from __future__ import annotations

import unittest

from retrieval.planner import build_question_plan


class PersonalizedPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_is_diverse_and_uses_resume_and_goal(self) -> None:
        plan = await build_question_plan(
            role_focus="AI Engineer",
            resume_text=(
                "Key skills:\nPython, FastAPI, PyTorch\n\n"
                "Experience highlights:\nBuilt a document intelligence pipeline\n"
            ),
            job_description="Build and monitor production AI systems.",
        )

        self.assertEqual(len(plan.questions), 7)
        competencies = [question.competency for question in plan.questions]
        self.assertEqual(len(competencies), len(set(competencies)))
        self.assertNotIn("role_framing", competencies)

        text = "\n".join(question.text for question in plan.questions)
        self.assertIn("AI Engineer", text)
        self.assertIn("Python", text)
        self.assertIn("document intelligence pipeline", text)
        self.assertIn("AI feature", text)
        self.assertIn("production answer quality", text)
        self.assertEqual(len({question.text for question in plan.questions}), 7)

        resume_anchored = [
            question
            for question in plan.questions
            if "résumé" in question.text or "Python" in question.text
        ]
        self.assertEqual(len(resume_anchored), 2)

    async def test_raw_resume_still_finds_a_known_skill(self) -> None:
        plan = await build_question_plan(
            role_focus="Backend Engineer",
            resume_text="Created APIs with FastAPI and PostgreSQL.",
            job_description=None,
        )

        self.assertIn("FastAPI", plan.questions[1].text)

    async def test_linkedin_mode_uses_only_the_fixed_recording_sequence(self) -> None:
        plan = await build_question_plan(
            role_focus="Software Developer",
            resume_text="Python, FastAPI, React",
            job_description=None,
            interview_mode="linkedin_scripted",
            candidate_name="Madhav Khurana",
        )

        self.assertEqual(len(plan.questions), 8)
        self.assertTrue(
            all(question.question_type == "linkedin_scripted" for question in plan.questions)
        )
        self.assertEqual(
            plan.questions[0].text,
            "Welcome, Madhav Khurana. Please introduce yourself and tell us what kind of role you are looking for.",
        )
        self.assertEqual(
            plan.questions[-1].text,
            "What opportunity are you looking for next?",
        )


if __name__ == "__main__":
    unittest.main()
