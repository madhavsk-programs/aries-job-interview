"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { sessionFetch } from "@/lib/livekit-client";

type Report = {
  status: string;
  summary: string;
  strengths: string[];
  improvements: string[];
  practice_plan: string[];
  dimensions: Record<string, number>;
  evidence: Array<{ id: string; turn_id: string | null; quote: string; demonstrates?: string; offset_ms: number }>;
  transcript: Array<{ id: string; turn_index: number; speaker: string; text: string; offset_ms: number }>;
  delivery: Record<string, string | number>;
  integrity_observations: Array<{ type: string; message: string; interpretation: string }>;
  disclaimer: string;
};

export default function ReportView({ sessionId }: { sessionId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await sessionFetch(sessionId, "report");
      if (!response.ok) throw new Error(await response.text());
      const payload = await response.json();
      if (payload.report === null) setStatus(payload.status || "pending");
      else { setReport(payload as Report); setStatus("complete"); }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Report unavailable.");
    }
  }, [sessionId]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (report || error) return;
    const timer = window.setInterval(() => { void load(); }, 2000);
    return () => window.clearInterval(timer);
  }, [report, error, load]);

  if (error) return <section className="report-card"><h1>Report unavailable</h1><p>{error}</p></section>;
  if (!report) return (
    <section className="report-card">
      <p className="kicker">REPORT STATUS</p><h1>{status === "loading" ? "Loading…" : "Feedback is being prepared."}</h1>
      <p className="lede">Your transcript, evidence, and delivery feedback are being finalized. This page updates automatically.</p>
    </section>
  );

  const turnIndex = new Map(report.transcript.map((turn) => [turn.id, turn.turn_index]));
  return (
    <div className="report-grid">
      <section className="report-card report-summary"><p className="kicker">CANDIDATE REPORT</p><h1>Your evidence, made useful.</h1><p className="lede">{report.summary}</p><p className="disclaimer">{report.disclaimer}</p></section>
      <section className="report-card"><h2>Rubric</h2>{Object.keys(report.dimensions).length ? <div className="metric-grid">{Object.entries(report.dimensions).map(([name, value]) => <div className="metric" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value.toFixed(2)}</strong></div>)}</div> : <p className="muted">Content scores were not captured for this interview.</p>}</section>
      <section className="report-card split-list"><div><h2>Strengths</h2>{report.strengths.length ? <ul>{report.strengths.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">No content strengths were produced.</p>}</div><div><h2>Next improvements</h2>{report.improvements.length ? <ul>{report.improvements.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">No content improvements were produced.</p>}</div></section>
      <section className="report-card"><h2>Evidence</h2>{report.evidence.length ? report.evidence.map((item) => <a className="evidence-row" href={`#turn-${turnIndex.get(item.turn_id || "") || ""}`} key={item.id}><blockquote>“{item.quote}”</blockquote><span>{item.demonstrates || "Supporting excerpt"} · {Math.round(item.offset_ms / 1000)}s</span></a>) : <p className="muted">No evidence excerpts were produced.</p>}</section>
      <section className="report-card"><h2>Delivery mechanics</h2><div className="metric-grid">{["pace_wpm", "filler_count", "pause_count", "longest_pause_ms"].map((key) => <div className="metric" key={key}><span>{key.replaceAll("_", " ")}</span><strong>{String(report.delivery[key] ?? "—")}</strong></div>)}</div></section>
      <section className="report-card"><h2>Practice plan</h2><ol>{report.practice_plan.map((item) => <li key={item}>{item}</li>)}</ol></section>
      <section className="report-card"><h2>Transcript replay</h2>{report.transcript.map((turn) => <div id={`turn-${turn.turn_index}`} className={`report-turn ${turn.speaker}`} key={turn.id}><span>{turn.speaker === "candidate" ? "A" : "Q"} · {Math.round(turn.offset_ms / 1000)}s</span><p>{turn.text}</p></div>)}</section>
      <p><Link className="secondary-action" href={`/review/${sessionId}`}>Open reviewer view</Link></p>
    </div>
  );
}
