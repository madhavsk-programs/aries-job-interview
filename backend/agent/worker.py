"""LiveKit agent entrypoint.

Owns the realtime session and the wiring between it and everything else: the
adaptive turn graph (via tools), transcript persistence, and the data-channel
push that lets the browser render the transcript and its scores live.
"""

from __future__ import annotations

import logging
import asyncio
import json

from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, cli
from livekit.plugins import openai, silero

from agent.interviewer_agent import InterviewerAgent
from agent.tools import SessionRuntime
from agent.tools import TURN_STATUS_TOPIC
from config import settings
from db import repository
from observability.otel_setup import setup_tracing
from retrieval.question_bank import QuestionPlan

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aries.worker")

server = AgentServer()


def _session_id_from_room(room_name: str) -> str:
    """Rooms are named ``aries-{session_id}`` by the token endpoint."""

    return room_name[len("aries-"):] if room_name.startswith("aries-") else room_name


@server.rtc_session(agent_name=settings.active_agent_name)
async def interview_session(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    setup_tracing("aries-voice-agent")

    session_id = _session_id_from_room(ctx.room.name)
    await repository.ensure_session(session_id=session_id, room_name=ctx.room.name)
    stored_session = await repository.load_session(session_id)
    plan = QuestionPlan.from_payload(
        stored_session.competency_plan if stored_session else None
    )
    runtime = SessionRuntime(session_id=session_id, room=ctx.room, plan=plan)
    runtime.prosody.attach(ctx.room)
    scripted_mode = bool(
        plan.questions and plan.questions[0].question_type == "linkedin_scripted"
    )

    # The conversational path is entirely local. Speaches performs STT/TTS and
    # Ollama handles adaptive decisions. Turns are committed explicitly from
    # the browser so a natural pause never splits one candidate answer.
    vad = silero.VAD.load(
        min_speech_duration=0.12,
        min_silence_duration=0.65,
        prefix_padding_duration=0.25,
        activation_threshold=0.5,
    )
    session = AgentSession(
        stt=openai.STT(
            model=settings.speech_stt_model,
            language="en",
            base_url=settings.speech_base_url,
            api_key=settings.speech_api_key,
            use_realtime=False,
        ),
        # Follow-up control is performed in InterviewerAgent and the graph. The
        # local model supplies acknowledgement/follow-up wording but cannot
        # skip scoring, leak an action label, or repeat a covered competency.
        llm=None,
        tts=openai.TTS(
            model=settings.speech_tts_model,
            voice=settings.speech_tts_voice,
            base_url=settings.speech_base_url,
            api_key=settings.speech_api_key,
            response_format="wav",
        ),
        vad=vad,
        turn_handling={
            "turn_detection": "manual",
            "endpointing": {"min_delay": 0.65, "max_delay": 1.5},
            "interruption": {
                "enabled": True,
                "mode": "vad",
                "min_duration": 0.35,
                "resume_false_interruption": True,
            },
            "preemptive_generation": {"enabled": False},
        },
    )

    _wire_events(session, runtime)
    _wire_manual_turn_control(ctx, session, runtime)

    logger.info("starting interview session=%s room=%s", session_id, ctx.room.name)
    await session.start(
        agent=InterviewerAgent(runtime=runtime),
        room=ctx.room,
    )
    await repository.mark_session_status(session_id, "in_progress")

    async def _on_shutdown() -> None:
        await runtime.finalize()
        await runtime.prosody.close()

    ctx.add_shutdown_callback(_on_shutdown)

    # Seed the first competency so the opening question is already part of the
    # plan rather than improvised, and coverage tracking starts correct.
    opening = runtime.plan.next_question()
    if opening is not None:
        runtime.current_question = opening.text
        runtime.current_competency = opening.competency
        runtime.current_question_type = opening.question_type
        runtime.current_difficulty = opening.difficulty

    opening_text = (
        runtime.current_question
        if scripted_mode
        else (
            "Welcome to your practice interview. You can interrupt me at any time. "
            f"{runtime.current_question}"
        )
    )
    session.say(opening_text, allow_interruptions=True)


def _wire_manual_turn_control(
    ctx: JobContext, session: AgentSession, runtime: SessionRuntime
) -> None:
    """Commit one complete recorded answer only when the candidate requests it."""

    commit_lock = asyncio.Lock()

    async def _commit_answer() -> None:
        if commit_lock.locked():
            return
        async with commit_lock:
            if runtime.interview_complete:
                await runtime.publish(TURN_STATUS_TOPIC, {"status": "complete"})
                return
            await runtime.publish(TURN_STATUS_TOPIC, {"status": "processing"})
            try:
                transcript = await session.commit_user_turn(
                    transcript_timeout=3.0,
                    stt_flush_duration=0.4,
                )
                await runtime.publish(
                    TURN_STATUS_TOPIC,
                    {"status": "committed" if transcript.strip() else "empty"},
                )
            except Exception as exc:
                logger.warning("manual turn commit failed: %s", exc)
                await runtime.publish(
                    TURN_STATUS_TOPIC,
                    {"status": "error", "message": "The answer could not be sent."},
                )

    @ctx.room.on("data_received")
    def _on_data(packet) -> None:
        if getattr(packet, "topic", None) != "aries.turn_control":
            return
        try:
            payload = json.loads(packet.data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if payload.get("action") == "finish_answer":
            asyncio.create_task(_commit_answer())


def _wire_events(session: AgentSession, runtime: SessionRuntime) -> None:
    """Attach transcript capture and turn-taking diagnostics.

    Event handlers synchronously snapshot turn identity; persistence remains
    asynchronous so it cannot hold up the audio path.
    """

    @session.on("conversation_item_added")
    def _on_item(event) -> None:
        item = event.item
        if getattr(item, "role", None) != "assistant":
            return
        text = getattr(item, "text_content", None)
        if callable(text):
            text = text()
        if not text:
            content = getattr(item, "content", None) or []
            text = " ".join(part for part in content if isinstance(part, str))
        text = (text or "").strip()
        if not text:
            return
        runtime.capture_interviewer_turn(text)

    @session.on("user_state_changed")
    def _on_user_state(event) -> None:
        state = str(getattr(event, "new_state", "")).lower()
        if state.endswith("speaking"):
            runtime.prosody.begin_candidate_turn()
        elif state.endswith("listening") or state.endswith("away"):
            runtime.prosody.end_candidate_turn()

    @session.on("overlapping_speech")
    def _on_overlap(event) -> None:
        # This is the barge-in vs backchannel distinction, surfaced for the
        # Phase 1 acceptance check and for latency debugging.
        logger.info(
            "overlapping_speech interruption=%s detection_delay=%sms",
            getattr(event, "is_interruption", None),
            getattr(event, "detection_delay", None),
        )

    @session.on("agent_false_interruption")
    def _on_false_interruption(event) -> None:
        logger.info("false interruption (backchannel); resumed=%s", getattr(event, "resumed", None))

    @session.on("error")
    def _on_error(event) -> None:
        logger.error("session error: %s", getattr(event, "error", event))


if __name__ == "__main__":
    cli.run_app(server)
