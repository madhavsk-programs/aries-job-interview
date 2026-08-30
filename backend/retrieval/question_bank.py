"""Competency-ordered question source.

This module owns the fallback bank and the coverage-aware plan abstraction.
``retrieval.planner`` fills the same plan from pgvector results matched against
the role, job description, and resume, with this bank as its offline fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BankQuestion:
    competency: str
    text: str
    difficulty: int = 2
    question_type: str = "technical"

    def to_dict(self) -> dict:
        return {
            "competency": self.competency,
            "text": self.text,
            "difficulty": self.difficulty,
            "question_type": self.question_type,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BankQuestion":
        return cls(
            competency=str(payload.get("competency", "general")),
            text=str(payload.get("text", "Tell me about your relevant experience.")),
            difficulty=max(1, min(3, int(payload.get("difficulty", 2)))),
            question_type=str(payload.get("question_type", "technical")),
        )


STATIC_BANK: list[BankQuestion] = [
    BankQuestion(
        competency="role_framing",
        question_type="opening",
        difficulty=1,
        text="To start: what role are you practising for, and what does your day-to-day look like in it?",
    ),
    BankQuestion(
        competency="system_design",
        difficulty=2,
        text="Walk me through how you would design a rate limiter for a public API.",
    ),
    BankQuestion(
        competency="debugging",
        difficulty=3,
        text="Describe the hardest bug you have personally tracked down. How did you isolate it?",
    ),
    BankQuestion(
        competency="data_modelling",
        difficulty=2,
        text="How would you model a system where one user can belong to many organisations with different roles in each?",
    ),
    BankQuestion(
        competency="ownership",
        question_type="behavioural",
        difficulty=2,
        text="Tell me about a time you shipped something that broke in production. What did you do?",
    ),
    BankQuestion(
        competency="collaboration",
        question_type="behavioural",
        difficulty=2,
        text="Tell me about a technical decision where you disagreed with a teammate. How did it resolve?",
    ),
    BankQuestion(
        competency="tradeoffs",
        difficulty=3,
        text="Give me a case where you chose the slower or less elegant solution on purpose. What made it the right call?",
    ),
]


@dataclass
class QuestionPlan:
    """Tracks which competencies have been covered in this session."""

    questions: list[BankQuestion] = field(default_factory=lambda: list(STATIC_BANK))
    asked: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: list[dict] | None) -> "QuestionPlan":
        questions = [BankQuestion.from_dict(item) for item in (payload or [])]
        return cls(questions=questions or list(STATIC_BANK))

    def to_payload(self) -> list[dict]:
        return [question.to_dict() for question in self.questions]

    @property
    def competencies(self) -> list[str]:
        return [q.competency for q in self.questions]

    @property
    def remaining(self) -> list[BankQuestion]:
        return [q for q in self.questions if q.competency not in self.asked]

    @property
    def exhausted(self) -> bool:
        return not self.remaining

    def current_competency(self) -> str:
        return self.asked[-1] if self.asked else "role_framing"

    def next_question(self, prefer_harder: bool = False) -> BankQuestion | None:
        """Return the next uncovered question and mark its competency asked.

        ``prefer_harder`` is set when the previous answer was strong: coverage
        stays in order, but a strong candidate is moved onto the harder of the
        remaining items rather than the next one in the list.
        """

        remaining = self.remaining
        if not remaining:
            return None
        if prefer_harder:
            choice = max(remaining, key=lambda q: q.difficulty)
        else:
            choice = remaining[0]
        self.asked.append(choice.competency)
        return choice
