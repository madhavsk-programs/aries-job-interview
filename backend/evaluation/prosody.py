"""Audio-derived communication delivery measurements.

This module deliberately reports observable delivery mechanics only. It never
maps audio to confidence, personality, honesty, competence, or trustworthiness.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

from livekit import rtc

logger = logging.getLogger("aries.prosody")

FILLER_PATTERN = re.compile(
    r"\b(?:um+|uh+|erm+|hmm+|like|you\s+know|sort\s+of|kind\s+of)\b",
    re.IGNORECASE,
)


def _label(value: float, good: tuple[float, float], moderate: tuple[float, float]) -> str:
    if good[0] <= value <= good[1]:
        return "Good"
    if moderate[0] <= value <= moderate[1]:
        return "Moderate"
    return "Needs work"


@dataclass
class AudioDeliveryMonitor:
    """Consumes the candidate microphone track and measures voiced/pause time."""

    silence_threshold: float = 0.018
    minimum_pause_ms: float = 250.0
    active: bool = False
    voiced_ms: float = 0.0
    active_silence_ms: float = 0.0
    pause_durations_ms: list[float] = field(default_factory=list)
    long_pause_durations_ms: list[float] = field(default_factory=list)
    word_count: int = 0
    filler_count: int = 0
    transcript_turns: int = 0

    _stream: rtc.AudioStream | None = field(default=None, init=False, repr=False)
    _stream_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _speech_seen_in_turn: bool = field(default=False, init=False, repr=False)

    def attach(self, room: rtc.Room) -> None:
        room.on("track_subscribed", self._on_track_subscribed)
        for participant in room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._on_track_subscribed(publication.track, publication, participant)

    def begin_candidate_turn(self) -> None:
        self.active = True
        self.active_silence_ms = 0.0
        self._speech_seen_in_turn = False

    def end_candidate_turn(self) -> None:
        self._finish_pause()
        self.active = False
        self._speech_seen_in_turn = False

    def add_transcript(self, text: str) -> None:
        words = re.findall(r"\b[\w'-]+\b", text)
        self.word_count += len(words)
        self.filler_count += len(FILLER_PATTERN.findall(text))
        self.transcript_turns += 1

    def _on_track_subscribed(self, track, publication, participant) -> None:
        if getattr(track, "kind", None) != rtc.TrackKind.KIND_AUDIO:
            return
        if self._stream_task and not self._stream_task.done():
            return
        self._stream = rtc.AudioStream(track)
        self._stream_task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        if self._stream is None:
            return
        try:
            async for event in self._stream:
                if self.active:
                    self.ingest_frame(event.frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - analytics must not affect audio
            logger.warning("prosody audio stream stopped: %s", exc)

    def ingest_frame(self, frame: rtc.AudioFrame) -> None:
        samples = frame.data
        if len(samples) == 0:
            return
        mean_square = sum(int(sample) * int(sample) for sample in samples) / len(samples)
        rms = math.sqrt(mean_square) / 32768.0
        duration_ms = frame.duration * 1000.0

        if rms >= self.silence_threshold:
            if self.active_silence_ms >= self.minimum_pause_ms and self._speech_seen_in_turn:
                self._record_pause(self.active_silence_ms)
            self.active_silence_ms = 0.0
            self.voiced_ms += duration_ms
            self._speech_seen_in_turn = True
        elif self._speech_seen_in_turn:
            self.active_silence_ms += duration_ms

    def _record_pause(self, duration_ms: float) -> None:
        self.pause_durations_ms.append(round(duration_ms, 1))
        if duration_ms >= 3000:
            self.long_pause_durations_ms.append(round(duration_ms, 1))

    def _finish_pause(self) -> None:
        if self.active_silence_ms >= self.minimum_pause_ms and self._speech_seen_in_turn:
            self._record_pause(self.active_silence_ms)
        self.active_silence_ms = 0.0

    def snapshot(self) -> dict[str, Any]:
        self._finish_pause()
        included_pause_ms = sum(min(value, 3000.0) for value in self.pause_durations_ms)
        speaking_window_minutes = max((self.voiced_ms + included_pause_ms) / 60000.0, 1 / 60)
        wpm = self.word_count / speaking_window_minutes
        filler_rate = (self.filler_count / max(self.word_count, 1)) * 100
        average_pause = (
            sum(self.pause_durations_ms) / len(self.pause_durations_ms)
            if self.pause_durations_ms
            else 0.0
        )
        return {
            "source": "candidate microphone audio + synchronized transcript",
            "word_count": self.word_count,
            "speaking_time_ms": round(self.voiced_ms + included_pause_ms),
            "pace_wpm": round(wpm, 1),
            "pace_label": _label(wpm, (110, 175), (85, 205)),
            "filler_count": self.filler_count,
            "filler_rate_percent": round(filler_rate, 2),
            "filler_label": _label(filler_rate, (0, 2.5), (0, 5.0)),
            "pause_count": len(self.pause_durations_ms),
            "average_pause_ms": round(average_pause),
            "longest_pause_ms": round(max(self.pause_durations_ms, default=0.0)),
            "pause_label": _label(average_pause, (0, 900), (0, 1600)),
            "disclaimer": (
                "Delivery mechanics only; these measurements do not infer "
                "confidence, personality, honesty, or trustworthiness."
            ),
        }

    async def close(self) -> None:
        self.end_candidate_turn()
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
        if self._stream is not None:
            await self._stream.aclose()
        self._stream_task = None
        self._stream = None

