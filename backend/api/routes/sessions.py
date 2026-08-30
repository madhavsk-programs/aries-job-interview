from datetime import timedelta
import re
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from livekit import api
from pydantic import BaseModel, Field

from config import settings
from db import repository
from evaluation.deep.report_synthesizer import synthesize_report
from local_ai import local_ai_status
from retrieval.planner import build_question_plan
from api.security import issue_session_token, require_session_access

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=80)
    participant_name: str = Field(default="Candidate", min_length=1, max_length=80)
    role_focus: str | None = Field(default=None, max_length=160)
    resume_text: str | None = Field(default=None, max_length=30_000)
    job_description: str | None = Field(default=None, max_length=30_000)
    # Structured mode is the public default. This also protects candidates
    # using a stale browser bundle that does not yet send the mode field.
    interview_mode: Literal["adaptive", "linkedin_scripted"] = "linkedin_scripted"


class CreateSessionResponse(BaseModel):
    session_id: str
    room_name: str
    server_url: str
    participant_token: str
    access_token: str
    interview_mode: Literal["adaptive", "linkedin_scripted"]
    competency_plan: list[dict[str, Any]]


class TurnResponse(BaseModel):
    turn_index: int
    speaker: str
    text: str
    offset_ms: int


class TranscriptResponse(BaseModel):
    session_id: str
    turns: list[TurnResponse]


@router.post("", response_model=CreateSessionResponse)
async def create_session(payload: CreateSessionRequest) -> CreateSessionResponse:
    session_id = payload.session_id or uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", session_id):
        raise HTTPException(status_code=422, detail="Invalid session id.")
    room_name = f"aries-{session_id}"
    participant_identity = f"candidate-{uuid4().hex[:12]}"

    ai_status = await local_ai_status()
    if not ai_status["ready"]:
        issues = "; ".join(str(item) for item in ai_status["issues"])
        raise HTTPException(
            status_code=503,
            detail=f"Local AI is not ready: {issues}. Run scripts\\setup-local-ai.ps1.",
        )

    plan = await build_question_plan(
        role_focus=payload.role_focus,
        resume_text=payload.resume_text,
        job_description=payload.job_description,
        interview_mode=payload.interview_mode,
        candidate_name=payload.participant_name,
    )

    # Recorded before the token is issued so the agent, which derives the same
    # session id from the room name, always finds a row to attach turns to.
    await repository.ensure_session(
        session_id=session_id,
        room_name=room_name,
        candidate_name=payload.participant_name,
        role_focus=payload.role_focus,
        resume_text=payload.resume_text,
        job_description=payload.job_description,
        competency_plan=plan.to_payload(),
    )

    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(participant_identity)
        .with_name(payload.participant_name)
        .with_ttl(timedelta(minutes=30))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(agent_name=settings.active_agent_name)
                ]
            )
        )
        .to_jwt()
    )

    return CreateSessionResponse(
        session_id=session_id,
        room_name=room_name,
        server_url=settings.livekit_url,
        participant_token=token,
        access_token=issue_session_token(session_id),
        interview_mode=payload.interview_mode,
        competency_plan=plan.to_payload(),
    )


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    session_id: str, _: None = Depends(require_session_access)
) -> TranscriptResponse:
    """Replay a persisted transcript.

    The live panel is fed over the data channel; this endpoint is for reloading
    a session after the fact, and is what the Phase 3 report page reads from.
    """

    if not settings.persistence_enabled:
        raise HTTPException(
            status_code=503,
            detail="Persistence is disabled; transcripts are not being stored.",
        )

    turns = await repository.load_transcript(session_id)
    return TranscriptResponse(
        session_id=session_id,
        turns=[
            TurnResponse(
                turn_index=turn.turn_index,
                speaker=turn.speaker,
                text=turn.text,
                offset_ms=turn.offset_ms,
            )
            for turn in turns
        ],
    )


@router.get("/{session_id}/report")
async def get_report(
    session_id: str, _: None = Depends(require_session_access)
) -> dict[str, Any]:
    session = await repository.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.report:
        return session.report
    return {"session_id": session_id, "status": session.status, "report": None}


@router.post("/{session_id}/report")
async def generate_report(
    session_id: str, _: None = Depends(require_session_access)
) -> dict[str, Any]:
    session = await repository.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return await synthesize_report(session_id)


@router.get("/{session_id}/review")
async def review_snapshot(
    session_id: str, _: None = Depends(require_session_access)
) -> dict[str, Any]:
    session = await repository.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    turns = await repository.load_transcript(session_id)
    scores = await repository.load_scores(session_id)
    return {
        "session_id": session_id,
        "status": session.status,
        "candidate_name": session.candidate_name,
        "role_focus": session.role_focus,
        "turns": [
            {
                "id": str(turn.id),
                "turn_index": turn.turn_index,
                "speaker": turn.speaker,
                "text": turn.text,
                "offset_ms": turn.offset_ms,
            }
            for turn in turns
        ],
        "scores": [
            {
                "turn_id": str(score.turn_id) if score.turn_id else None,
                "dimension": score.dimension,
                "value": score.value,
                "rationale": score.rationale,
                "evaluator": score.evaluator,
                "details": score.details or {},
            }
            for score in scores
        ],
        "delivery": session.delivery_metrics or {},
        "integrity_observations": session.integrity_observations or [],
        "report_ready": bool(session.report),
    }
