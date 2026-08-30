"""Extract text from resume PDFs and turn it into editable setup fields."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from evaluation.structured import complete_json

logger = logging.getLogger("aries.resume")

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 15
MAX_RESUME_CHARS = 30_000


class ResumeParseError(ValueError):
    """Raised when an uploaded file cannot provide usable resume text."""


@dataclass(frozen=True)
class ExtractedResume:
    text: str
    page_count: int


PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidate_name",
        "suggested_role",
        "professional_summary",
        "skills",
        "experience_highlights",
        "education",
    ],
    "properties": {
        "candidate_name": {"type": "string"},
        "suggested_role": {"type": "string"},
        "professional_summary": {"type": "string"},
        "skills": {
            "type": "array",
            "maxItems": 30,
            "items": {"type": "string"},
        },
        "experience_highlights": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string"},
        },
        "education": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string"},
        },
    },
}


def extract_pdf_text(data: bytes) -> ExtractedResume:
    """Extract bounded text from an in-memory PDF without storing the upload."""

    if not data.startswith(b"%PDF-"):
        raise ResumeParseError("The selected file is not a valid PDF.")
    if len(data) > MAX_PDF_BYTES:
        raise ResumeParseError("The PDF is larger than the 5 MB limit.")

    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ResumeParseError("The PDF could not be opened.") from exc

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 - pypdf exposes backend errors
            raise ResumeParseError("Password-protected PDFs are not supported.") from exc
        if not unlocked:
            raise ResumeParseError("Password-protected PDFs are not supported.")

    page_count = len(reader.pages)
    if page_count == 0:
        raise ResumeParseError("The PDF has no pages.")
    if page_count > MAX_PDF_PAGES:
        raise ResumeParseError(f"The PDF has more than {MAX_PDF_PAGES} pages.")

    page_text: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one corrupt page should not crash the API
            logger.warning("resume page text extraction failed: %s", exc)
            text = ""
        normalized = _normalize_text(text)
        if normalized:
            page_text.append(normalized)

    resume_text = "\n\n".join(page_text).strip()
    if len(resume_text) < 40:
        raise ResumeParseError(
            "No readable text was found. Use a text-based PDF instead of a scanned image."
        )
    return ExtractedResume(text=resume_text[:MAX_RESUME_CHARS], page_count=page_count)


async def parse_resume_profile(text: str) -> tuple[dict, str]:
    """Return structured fields plus the parser source (Ollama or fallback)."""

    try:
        profile = await complete_json(
            name="resume_profile",
            schema=PROFILE_SCHEMA,
            instructions=(
                "Extract interview-setup information from the supplied resume text. "
                "Use only facts supported by the resume. candidate_name should contain "
                "only the person's name. suggested_role should be their most likely target "
                "role based on recent titles and skills, not an invented seniority. Keep the "
                "summary under 80 words. Deduplicate skills. Each experience or education "
                "item must be a concise factual phrase. Return empty strings or arrays when "
                "the resume does not support a field."
            ),
            input_text=text,
            max_tokens=1_100,
        )
        return _clean_profile(profile), "ollama"
    except Exception as exc:  # noqa: BLE001 - upload should remain useful during quota issues
        logger.warning("Ollama resume parsing unavailable; using local fallback: %s", exc)
        return _fallback_profile(text), "local-fallback"


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def _clean_profile(profile: dict) -> dict:
    def clean_list(key: str, limit: int) -> list[str]:
        raw = profile.get(key)
        if not isinstance(raw, list):
            return []
        unique: list[str] = []
        seen: set[str] = set()
        for value in raw:
            item = str(value).strip()
            marker = item.casefold()
            if item and marker not in seen:
                seen.add(marker)
                unique.append(item[:240])
        return unique[:limit]

    return {
        "candidate_name": str(profile.get("candidate_name") or "").strip()[:80],
        "suggested_role": str(profile.get("suggested_role") or "").strip()[:160],
        "professional_summary": str(profile.get("professional_summary") or "").strip()[:1_500],
        "skills": clean_list("skills", 30),
        "experience_highlights": clean_list("experience_highlights", 8),
        "education": clean_list("education", 6),
    }


def _fallback_profile(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    name = ""
    for line in lines[:8]:
        words = line.split()
        lowered = line.casefold()
        if (
            2 <= len(words) <= 5
            and "@" not in line
            and not re.search(r"\d", line)
            and lowered not in {"resume", "curriculum vitae", "cv"}
        ):
            name = line[:80]
            break

    role_words = (
        "engineer", "developer", "designer", "manager", "analyst", "consultant",
        "architect", "scientist", "specialist", "administrator", "intern",
    )
    role = next(
        (line[:160] for line in lines[:20] if any(word in line.casefold() for word in role_words)),
        "",
    )

    known_skills = [
        "Python", "Java", "JavaScript", "TypeScript", "React", "Next.js", "Node.js",
        "SQL", "PostgreSQL", "MongoDB", "Redis", "Docker", "Kubernetes", "AWS",
        "Azure", "GCP", "Git", "FastAPI", "Django", "Spring", "C++", "C#",
        "Machine Learning", "Data Analysis", "REST APIs", "GraphQL",
    ]
    lowered_text = text.casefold()
    skills = [skill for skill in known_skills if skill.casefold() in lowered_text]
    summary = re.sub(r"\s+", " ", text).strip()[:700]
    return {
        "candidate_name": name,
        "suggested_role": role,
        "professional_summary": summary,
        "skills": skills,
        "experience_highlights": [],
        "education": [],
    }
