"""Build a diverse interview plan directly from the candidate's goal and résumé."""

from __future__ import annotations

import re

from retrieval.question_bank import BankQuestion, QuestionPlan


KNOWN_SKILLS = (
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Next.js",
    "Node.js",
    "SQL",
    "PostgreSQL",
    "MongoDB",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "GCP",
    "Machine Learning",
    "Deep Learning",
    "PyTorch",
    "TensorFlow",
    "LangChain",
    "LLM",
)


def _linkedin_software_developer_questions(candidate_name: str | None) -> list[BankQuestion]:
    """The fixed sequence used when recording the polished LinkedIn interview."""

    name = _clean_anchor(candidate_name or "Candidate", 80)
    return [
        BankQuestion(
            competency="introduction",
            question_type="linkedin_scripted",
            difficulty=1,
            text=(
                f"Welcome, {name}. Please introduce yourself and tell us what kind "
                "of role you are looking for."
            ),
        ),
        BankQuestion(
            competency="motivation",
            question_type="linkedin_scripted",
            difficulty=1,
            text=(
                "Your resume contains substantial AI and machine-learning work. "
                "Why are you targeting a Software Developer role?"
            ),
        ),
        BankQuestion(
            competency="project_depth",
            question_type="linkedin_scripted",
            difficulty=2,
            text="Which project best demonstrates your software-development ability?",
        ),
        BankQuestion(
            competency="problem_solving",
            question_type="linkedin_scripted",
            difficulty=2,
            text="Tell me about a technical challenge you handled and how you approached it.",
        ),
        BankQuestion(
            competency="quality",
            question_type="linkedin_scripted",
            difficulty=2,
            text="How do you know whether a system you build is actually working well?",
        ),
        BankQuestion(
            competency="system_design",
            question_type="linkedin_scripted",
            difficulty=3,
            text="How would you approach designing a reliable backend for a new product?",
        ),
        BankQuestion(
            competency="learning",
            question_type="linkedin_scripted",
            difficulty=2,
            text=(
                "What demonstrates your ability to learn and work through unfamiliar "
                "problems?"
            ),
        ),
        BankQuestion(
            competency="role_fit",
            question_type="linkedin_scripted",
            difficulty=1,
            text="What opportunity are you looking for next?",
        ),
    ]


def _clean_anchor(value: str, limit: int = 110) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -•\t\r\n\"'")
    return value[:limit].rstrip(" ,.;:-")


def _section_first_line(text: str, heading: str) -> str:
    match = re.search(
        rf"(?im)^{re.escape(heading)}:\s*\n\s*([^\n]+)",
        text,
    )
    return _clean_anchor(match.group(1)) if match else ""


def _skill_anchor(resume_text: str) -> str:
    skills_line = _section_first_line(resume_text, "Key skills")
    if skills_line:
        return _clean_anchor(re.split(r"[,|;]", skills_line)[0], 45)

    lowered = resume_text.lower()
    return next(
        (skill for skill in KNOWN_SKILLS if skill.lower() in lowered),
        "your core technical stack",
    )


def _design_question(role: str) -> str:
    lowered = role.lower()
    if "ai" in lowered or "machine learning" in lowered or "ml " in f"{lowered} ":
        return (
            "How would you design and monitor an AI feature from model inference "
            "through production feedback and failure handling?"
        )
    if "front" in lowered or "react" in lowered:
        return (
            "How would you design a responsive frontend that remains fast and "
            "reliable as its data and user traffic grow?"
        )
    if "data" in lowered:
        return (
            "How would you design a reliable data pipeline with validation, "
            "reprocessing, and production monitoring?"
        )
    return (
        f"For a {role} role, how would you design a production service that "
        "stays reliable as usage and data volume grow?"
    )


def _diagnostic_question(role: str) -> str:
    lowered = role.lower()
    if "ai" in lowered or "machine learning" in lowered or "ml " in f"{lowered} ":
        return (
            "Imagine an AI feature works in testing but its production answer quality "
            "suddenly drops. How would you investigate the cause step by step?"
        )
    if "front" in lowered or "react" in lowered:
        return (
            "Imagine a page becomes slow only for production users. How would you "
            "isolate whether the cause is rendering, networking, or the backend?"
        )
    if "data" in lowered:
        return (
            "Imagine a production data pipeline starts producing incomplete records. "
            "How would you locate the failure and recover safely?"
        )
    return (
        f"Imagine a production issue relevant to a {role} role appears only under "
        "real traffic. How would you investigate it step by step?"
    )


async def build_question_plan(
    *,
    role_focus: str | None,
    resume_text: str | None,
    job_description: str | None,
    interview_mode: str = "adaptive",
    candidate_name: str | None = None,
) -> QuestionPlan:
    """Create seven unique competencies with explicit résumé and goal anchors.

    Vector search previously only reordered a generic seven-question bank and
    could return ``role_framing`` twice. This builder guarantees diversity and
    makes the supplied interview goal visible in the actual question text.
    """

    if interview_mode == "linkedin_scripted":
        return QuestionPlan(questions=_linkedin_software_developer_questions(candidate_name))

    role = _clean_anchor(role_focus or "role matching your background", 80)
    article = "an" if role[:1].lower() in "aeiou" else "a"
    resume = resume_text or ""
    skill = _skill_anchor(f"{resume}\n{job_description or ''}")
    experience = _section_first_line(resume, "Experience highlights")
    opening_text = (
        f'Your résumé mentions "{experience}". What did you personally own, '
        "and what result came from your work?"
        if experience
        else (
            f"You are targeting {article} {role} position. Which project or achievement "
            "from your background best demonstrates that you are ready for it?"
        )
    )

    questions = [
        BankQuestion(
            competency="resume_alignment",
            question_type="opening",
            difficulty=1,
            text=opening_text,
        ),
        BankQuestion(
            competency="technical_depth",
            difficulty=2,
            text=(
                f"Your background mentions {skill}. What is the most technically "
                "demanding way you used it, including the trade-off you made?"
            ),
        ),
        BankQuestion(
            competency="problem_solving",
            difficulty=2,
            text=_diagnostic_question(role),
        ),
        BankQuestion(
            competency="system_design",
            difficulty=3,
            text=_design_question(role),
        ),
        BankQuestion(
            competency="decision_making",
            difficulty=3,
            text=(
                f"For a {role} role, describe how you would choose between two viable "
                "technical approaches when time, quality, and maintainability conflict."
            ),
        ),
        BankQuestion(
            competency="collaboration",
            question_type="behavioural",
            difficulty=2,
            text=(
                "Tell me about a disagreement during a technical project and the "
                "specific action you took to reach a decision."
            ),
        ),
        BankQuestion(
            competency="ownership",
            question_type="behavioural",
            difficulty=2,
            text=(
                "Tell me about a result that did not meet expectations and what you "
                "personally changed afterward."
            ),
        ),
    ]
    return QuestionPlan(questions=questions)
