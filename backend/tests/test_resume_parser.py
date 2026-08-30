from __future__ import annotations

import unittest
from unittest.mock import patch

from resume.parser import (
    ResumeParseError,
    _clean_profile,
    _fallback_profile,
    extract_pdf_text,
)


class _FakePage:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _FakeReader:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages
        self.is_encrypted = False


class ResumeParserTests(unittest.TestCase):
    def test_rejects_non_pdf_content(self) -> None:
        with self.assertRaisesRegex(ResumeParseError, "not a valid PDF"):
            extract_pdf_text(b"not a resume")

    @patch("resume.parser.PdfReader")
    def test_extracts_and_normalizes_pdf_text(self, reader: unittest.mock.Mock) -> None:
        reader.return_value = _FakeReader([
            _FakePage("Maya  Rao\n\nSoftware Engineer"),
            _FakePage("Python   FastAPI\nBuilt reliable APIs"),
        ])

        extracted = extract_pdf_text(b"%PDF-1.7 fake test content")

        self.assertEqual(extracted.page_count, 2)
        self.assertIn("Maya Rao", extracted.text)
        self.assertIn("Python FastAPI", extracted.text)

    @patch("resume.parser.PdfReader")
    def test_rejects_image_only_pdf(self, reader: unittest.mock.Mock) -> None:
        reader.return_value = _FakeReader([_FakePage("")])
        with self.assertRaisesRegex(ResumeParseError, "No readable text"):
            extract_pdf_text(b"%PDF-1.7 image only")

    def test_local_fallback_finds_basic_profile(self) -> None:
        profile = _fallback_profile(
            "Maya Rao\nBackend Engineer\nPython, FastAPI, PostgreSQL and Docker"
        )

        self.assertEqual(profile["candidate_name"], "Maya Rao")
        self.assertEqual(profile["suggested_role"], "Backend Engineer")
        self.assertEqual(profile["skills"], ["Python", "SQL", "PostgreSQL", "Docker", "FastAPI"])

    def test_clean_profile_deduplicates_and_bounds_values(self) -> None:
        profile = _clean_profile({
            "candidate_name": " Maya Rao ",
            "suggested_role": "Backend Engineer",
            "professional_summary": "Builds APIs.",
            "skills": ["Python", "python", "FastAPI"],
            "experience_highlights": ["Built APIs", "Built APIs"],
            "education": ["B.Tech"],
        })

        self.assertEqual(profile["candidate_name"], "Maya Rao")
        self.assertEqual(profile["skills"], ["Python", "FastAPI"])
        self.assertEqual(profile["experience_highlights"], ["Built APIs"])


if __name__ == "__main__":
    unittest.main()
