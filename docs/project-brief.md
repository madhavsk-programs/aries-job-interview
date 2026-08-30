# ARIES-Voice project brief

## Product thesis

ARIES-Voice is not merely a chatbot with speech. It combines three capabilities:

1. **Adaptive competency coverage:** every next question is chosen from what the candidate just demonstrated or failed to demonstrate.
2. **Evidence-grounded scoring:** every final score points to a timestamped transcript quote and explains what that quote shows.
3. **Audio-derived delivery signals:** pace, filler frequency, and pause structure come from audio measurements and are never presented as personality, confidence, honesty, or trustworthiness judgments.

## Users and surfaces

- **Candidate:** configures and completes a practice interview, then receives an evidence-linked report.
- **Reviewer:** observes a live transcript and running evaluation signals without joining the candidate’s media experience.
- **Operator/developer:** inspects model calls, latency, failures, and branching decisions through traces.

## Intended system shape

```text
Realtime conversation
  -> fast synchronous evaluation
  -> decision node chooses probe / clarify / move on
  -> next spoken turn

Completed answer (in parallel)
  -> STAR evaluator
  -> technical-depth evaluator
  -> evidence extractor
  -> prosody measurements
  -> persisted evidence and report synthesis
```

Only the smallest decision payload belongs on the conversational critical path. Rich scoring and report work must run asynchronously.

## Build phases

### Phase 1 — voice loop

Build the WebRTC room, realtime interviewer, session-token endpoint, and microphone UI. Prove natural turn-taking and interruption before adding evaluation code.

### Phase 2 — adaptive loop

Add the interview state schema, fast evaluator, explicit decision graph, persistence, transcript display, and tracing. Prove that a weak or incomplete answer causes a relevant follow-up while a strong answer advances coverage.

### Phase 3 — evidence and reporting

Add deep evaluators, evidence extraction, audio measurements, question-bank retrieval, anomaly observations, reviewer dashboard, and the candidate report. Prove score-to-quote navigation end to end.

## Data boundaries

- Parse one resume and one job description directly into structured data.
- Use vector retrieval only for the reusable question bank.
- Store transcript segments with stable identifiers and timestamps so evidence links survive report regeneration.
- Treat integrity events as observations, never automated cheating verdicts.
- Report measured latency distributions (such as P50/P95), not guaranteed public latency claims.

## Demo-critical scenarios

1. The candidate interrupts an in-progress interviewer response and the response stops promptly.
2. The next question refers to a concrete detail from the candidate’s prior answer.
3. Selecting a report score navigates to the exact transcript moment and quote supporting it.

## Deferred directory map

The following areas should be added only in their corresponding phase:

```text
backend/
├── graph/                  # Phase 2
├── evaluation/             # Phase 2 and 3
├── db/                     # Phase 2
├── observability/          # Phase 2
├── retrieval/              # Phase 3
└── integrity/              # Phase 3

frontend/
├── components/TranscriptPanel.tsx  # Phase 2
├── app/setup/                       # Phase 3
├── app/dashboard/[sessionId]/       # Phase 3
└── app/report/[sessionId]/          # Phase 3
```

