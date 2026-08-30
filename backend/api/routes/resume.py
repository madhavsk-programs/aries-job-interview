"""Resume upload endpoint used to prefill the interview setup form."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from resume.parser import MAX_PDF_BYTES, ResumeParseError, extract_pdf_text, parse_resume_profile

router = APIRouter(prefix="/resume", tags=["resume"])


class ResumeParseResponse(BaseModel):
    filename: str
    page_count: int
    resume_text: str
    candidate_name: str
    suggested_role: str
    professional_summary: str
    skills: list[str]
    experience_highlights: list[str]
    education: list[str]
    parser: str


@router.post("/parse", response_model=ResumeParseResponse)
async def parse_resume(file: UploadFile = File(...)) -> ResumeParseResponse:
    filename = (file.filename or "resume.pdf").strip()[:180]
    content_type = (file.content_type or "").casefold()
    if content_type not in {"application/pdf", "application/x-pdf", ""}:
        raise HTTPException(status_code=415, detail="Upload a PDF resume.")

    data = await file.read(MAX_PDF_BYTES + 1)
    await file.close()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The PDF is larger than the 5 MB limit.",
        )

    try:
        extracted = extract_pdf_text(data)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    profile, parser_source = await parse_resume_profile(extracted.text)
    return ResumeParseResponse(
        filename=filename,
        page_count=extracted.page_count,
        resume_text=extracted.text,
        parser=parser_source,
        **profile,
    )
