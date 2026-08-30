"use client";

import { useRoomContext } from "@livekit/components-react";
import { RoomEvent } from "livekit-client";
import { useEffect, useMemo, useRef, useState } from "react";
import { apiBaseUrl } from "@/lib/livekit-client";

const TRANSCRIPT_TOPIC = "aries.transcript";

export type TranscriptTurn = {
  turn_index: number;
  speaker: "candidate" | "interviewer";
  text: string;
  offset_ms: number;
};

function formatOffset(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(total / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function isTurn(value: unknown): value is TranscriptTurn {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.turn_index === "number" &&
    (item.speaker === "candidate" || item.speaker === "interviewer") &&
    typeof item.text === "string" && typeof item.offset_ms === "number";
}

export default function TranscriptPanel({
  sessionId,
  accessToken,
  scripted = false,
}: {
  sessionId: string;
  accessToken: string;
  scripted?: boolean;
}) {
  const room = useRoomContext();
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${apiBaseUrl}/api/sessions/${sessionId}/transcript`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((payload: { turns?: unknown[] }) => {
        setTurns((payload.turns || []).filter(isTurn));
      })
      .catch(() => undefined);
  }, [sessionId, accessToken]);

  useEffect(() => {
    if (!room) {
      return;
    }

    const decoder = new TextDecoder();

    const onData = (payload: Uint8Array, _p?: unknown, _k?: unknown, topic?: string) => {
      if (topic !== TRANSCRIPT_TOPIC) {
        return;
      }

      let parsed: unknown;
      try {
        parsed = JSON.parse(decoder.decode(payload));
      } catch {
        return;
      }

      if (!isTurn(parsed)) return;
      const turn = parsed;
      // The agent may resend a turn on reconnect; index is authoritative.
      setTurns((current) => {
        if (current.some((existing) => existing.turn_index === turn.turn_index)) {
          return current;
        }
        return [...current, turn].sort((a, b) => a.turn_index - b.turn_index);
      });
    };

    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  // Defensive cleanup for older sessions: if silence detection produced
  // adjacent candidate fragments, present them as one complete answer box.
  const displayTurns = useMemo(() => turns.reduce<TranscriptTurn[]>((merged, turn) => {
    const previous = merged[merged.length - 1];
    if (previous?.speaker === "candidate" && turn.speaker === "candidate") {
      previous.text = `${previous.text.trim()} ${turn.text.trim()}`.trim();
      return merged;
    }
    merged.push({ ...turn });
    return merged;
  }, []), [turns]);

  return (
    <section className="transcript-panel" aria-label="Live transcript">
      <header className="transcript-head">
        <span>transcript</span>
        <span>{scripted ? "structured interview" : "complete answers"}</span>
      </header>

      <div className="transcript-body" ref={scrollRef}>
        {displayTurns.length === 0 ? (
          <p className="transcript-empty">
            {scripted
              ? "Wait for the first question, give your full answer, then click Finish answer."
              : "Waiting for the first turn. Speak once the interviewer greets you."}
          </p>
        ) : null}

        {displayTurns.map((turn) => (
          <div key={turn.turn_index} className={`transcript-turn ${turn.speaker}`}>
            <span className="turn-time">{formatOffset(turn.offset_ms)}</span>
            <div className="turn-content">
              <span className="turn-speaker">
                {turn.speaker === "interviewer" ? "Q" : "A"}
              </span>
              <p>{turn.text}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
