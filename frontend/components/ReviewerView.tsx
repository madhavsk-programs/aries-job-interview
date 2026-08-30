"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { sessionFetch } from "@/lib/livekit-client";

type Snapshot = {
  status: string; candidate_name: string; role_focus?: string;
  turns: Array<{ id: string; turn_index: number; speaker: string; text: string; offset_ms: number }>;
  scores: Array<{ turn_id: string | null; dimension: string; value: number; evaluator: string; rationale?: string }>;
  report_ready: boolean;
};

export default function ReviewerView({ sessionId }: { sessionId: string }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const response = await sessionFetch(sessionId, "review");
      if (!response.ok) throw new Error(await response.text());
      setSnapshot(await response.json() as Snapshot);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Reviewer data unavailable."); }
  }, [sessionId]);
  useEffect(() => { void load(); const timer = setInterval(() => void load(), 2000); return () => clearInterval(timer); }, [load]);
  const byTurn = useMemo(() => {
    const grouped = new Map<string, Snapshot["scores"]>();
    snapshot?.scores.forEach((score) => { if (score.turn_id) grouped.set(score.turn_id, [...(grouped.get(score.turn_id) || []), score]); });
    return grouped;
  }, [snapshot]);
  if (error) return <section className="report-card"><h1>Reviewer view unavailable</h1><p>{error}</p></section>;
  if (!snapshot) return <section className="report-card"><h1>Loading live review…</h1></section>;
  return <div className="review-layout"><aside className="review-sidebar"><p className="kicker">LIVE REVIEW</p><h2>{snapshot.candidate_name}</h2><p>{snapshot.role_focus || "General interview"}</p><span className="status-pill">{snapshot.status}</span><p>{snapshot.scores.length} scores · {snapshot.turns.length} turns</p></aside><section className="report-card"><h1>Evidence timeline</h1>{snapshot.turns.map((turn) => <div className={`report-turn ${turn.speaker}`} key={turn.id}><span>{turn.speaker} · {Math.round(turn.offset_ms / 1000)}s</span><p>{turn.text}</p>{(byTurn.get(turn.id) || []).map((score, index) => <div className="review-score" key={`${score.dimension}-${index}`}><strong>{score.dimension.replaceAll("_", " ")} {score.value.toFixed(2)}</strong><small>{score.evaluator}</small><p>{score.rationale}</p></div>)}</div>)}</section></div>;
}
