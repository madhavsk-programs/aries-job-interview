"use client";

import {
  ControlBar,
  LiveKitRoom,
  RoomAudioRenderer,
  StartAudio,
  useConnectionState,
  useRoomContext,
} from "@livekit/components-react";
import { ConnectionState, RoomEvent } from "livekit-client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import TranscriptPanel from "@/components/TranscriptPanel";
import {
  createVoiceSession,
  loadVoiceSession,
  type VoiceSession,
} from "@/lib/livekit-client";


type VoiceRoomProps = {
  sessionId: string;
};


function ConnectionSummary() {
  const connectionState = useConnectionState();
  const connected = connectionState === ConnectionState.Connected;

  return (
    <div className="connection-summary" aria-live="polite">
      <span className={connected ? "status-dot connected" : "status-dot"} />
      <span>{connected ? "Room connected" : connectionState}</span>
    </div>
  );
}


function FinishAnswerControl() {
  const room = useRoomContext();
  const connectionState = useConnectionState();
  const [status, setStatus] = useState<"ready" | "sending" | "empty" | "error" | "complete">("ready");

  useEffect(() => {
    const decoder = new TextDecoder();
    const onData = (payload: Uint8Array, _participant?: unknown, _kind?: unknown, topic?: string) => {
      if (topic !== "aries.turn_status") return;
      try {
        const message = JSON.parse(decoder.decode(payload)) as { status?: string };
        if (message.status === "processing") setStatus("sending");
        else if (message.status === "empty") setStatus("empty");
        else if (message.status === "error") setStatus("error");
        else if (message.status === "complete") setStatus("complete");
        else if (message.status === "committed") setStatus("ready");
      } catch {
        // A malformed status message must not interrupt the recording.
      }
    };

    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [room]);

  async function finishAnswer() {
    setStatus("sending");
    try {
      await room.localParticipant.publishData(
        new TextEncoder().encode(JSON.stringify({ action: "finish_answer" })),
        { reliable: true, topic: "aries.turn_control" },
      );
    } catch {
      setStatus("error");
    }
  }

  const disabled = connectionState !== ConnectionState.Connected || status === "sending" || status === "complete";
  const label = status === "sending"
    ? "Preparing next question…"
    : status === "complete"
      ? "Interview complete"
      : "Finish answer";

  return (
    <div className="finish-answer-wrap" aria-live="polite">
      <button className="finish-answer" type="button" onClick={finishAnswer} disabled={disabled}>
        {label}
      </button>
      <span>
        {status === "complete"
          ? "Select End interview & view report to prepare your feedback."
          : status === "empty"
          ? "No speech was detected. Speak, then try again."
          : status === "error"
            ? "Could not send the answer. Try again."
            : "Pause naturally. Click only after your complete answer."}
      </span>
    </div>
  );
}


function EndInterviewControl({ sessionId }: { sessionId: string }) {
  const room = useRoomContext();
  const router = useRouter();
  const [ending, setEnding] = useState(false);

  async function endInterview() {
    if (ending) return;
    setEnding(true);
    await room.disconnect();
    router.push(`/report/${sessionId}`);
  }

  return (
    <button className="secondary-action" type="button" onClick={endInterview} disabled={ending}>
      {ending ? "Finalizing…" : "End interview & view report"}
    </button>
  );
}


export default function VoiceRoom({ sessionId }: VoiceRoomProps) {
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const existing = loadVoiceSession(sessionId);
    const request = existing ? Promise.resolve(existing) : createVoiceSession(sessionId);
    request
      .then((createdSession) => {
        if (!controller.signal.aborted) {
          setSession(createdSession);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(
            reason instanceof Error ? reason.message : "Unable to start session.",
          );
        }
      });

    return () => controller.abort();
  }, [sessionId]);

  if (error) {
    return (
      <section className="voice-stage error-panel">
        <p className="kicker">CONNECTION ERROR</p>
        <h1>The voice session could not start.</h1>
        <p>{error}</p>
      </section>
    );
  }

  if (!session) {
    return (
      <section className="voice-stage loading-panel">
        <p>Preparing the interview room…</p>
      </section>
    );
  }

  // Old sessionStorage entries may not contain interview_mode. Treat them as
  // structured unless they explicitly identify themselves as adaptive.
  const structured = session.interview_mode !== "adaptive";

  return (
    <LiveKitRoom
      audio
      video={false}
      token={session.participant_token}
      serverUrl={session.server_url}
      connect
      className="voice-stage"
      data-lk-theme="default"
    >
      <ConnectionSummary />

      <TranscriptPanel
        sessionId={sessionId}
        accessToken={session.access_token}
        scripted={structured}
      />

      <div className="voice-controls">
        <ControlBar
          controls={{ microphone: true, camera: false, screenShare: false }}
          variation="minimal"
        />
        <FinishAnswerControl />
        <StartAudio label="Allow interview audio" />
        <EndInterviewControl sessionId={sessionId} />
      </div>

      <RoomAudioRenderer />
    </LiveKitRoom>
  );
}
