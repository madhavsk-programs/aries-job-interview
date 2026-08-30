# ARIES-Voice

A voice-native interview practice and screening system. The product promise is
a natural spoken interview whose next question is chosen from the answer before
it, and whose scores each point back at the transcript moment that produced them.

**Setup, API keys and every manual step: [SETUP.md](SETUP.md).**

Current state: **all three planned phases are implemented.** Live voice,
adaptive questioning, durable evidence, deep evaluators, delivery mechanics,
question retrieval, reviewer dashboard, and candidate reporting are wired as
one end-to-end application. AI inference is local: Ollama handles language and
embeddings, Faster-Whisper handles transcription, and Kokoro handles speech.
No commercial model API key or paid account is required.

The setup flow also accepts a PDF resume and automatically fills the editable
name, target role, skills, summary, experience, and education fields through
local Ollama. Files are parsed in memory rather than stored by the application.

## Architecture

```text
Browser microphone
    -> LiveKit room over WebRTC (VAD, turn detection, barge-in)
    -> Python LiveKit agent
    -> Local Silero VAD + Faster-Whisper STT
    -> Guarded conversational graph + local Qwen 3 4B evaluator
    -> Local Kokoro TTS
         |
         |  candidate finishes an answer -> one deterministic graph decision
         v
    LangGraph: fast_evaluate --> decide --> spoken next move
         |
         +-- background: STAR + technical + exact-quote evidence
         +-- candidate audio: pace + filler + pause mechanics
         v
    Postgres + pgvector --> personalized plan + report + reviewer replay
         +
    data channel --> live transcript with inline evidence markers
```

The split that shapes everything: choosing the next question needs a score, so
*some* evaluation must be synchronous — but only the minimum. `fast_evaluate`
is one compact structured call and is the sole evaluation on the conversational
critical path. STAR scoring, technical depth, evidence extraction and audio
delivery measurement all run outside that path.

The branching lives in `decide`, a real graph node, so the adaptive behaviour is
inspectable and testable on its own (`python -m tests.test_decide`) rather than
buried in a prompt.

## Repository layout

```text
aries-voice/
├── backend/
│   ├── agent/
│   │   ├── interviewer_agent.py   persona + tool protocol
│   │   ├── tools.py               turn scoring, persistence, SessionRuntime
│   │   └── worker.py              LiveKit entrypoint, transcript capture
│   ├── graph/
│   │   ├── state.py               TurnState
│   │   ├── nodes.py               fast_evaluate, decide (+ Phase 3 stubs)
│   │   └── graph.py               StateGraph wiring
│   ├── evaluation/
│   │   ├── fast_evaluator.py      the one on-critical-path LLM call
│   │   ├── deep/                  STAR, technical, evidence, report synthesis
│   │   └── prosody.py             microphone-derived delivery mechanics
│   ├── retrieval/                 plan + pgvector question retrieval
│   ├── integrity/                 observation-only signal monitor
│   ├── db/                        models, async session, repository, init
│   ├── observability/otel_setup.py OTLP -> Langfuse
│   ├── resume/                    bounded PDF text + local profile parsing
│   ├── api/                       resume, session, replay, review, report APIs
│   └── tests/test_decide.py       offline policy tests, no keys needed
├── frontend/
│   ├── app/                       setup, interview, report, reviewer routes
│   ├── components/
│   │   ├── VoiceRoom.tsx          LiveKit room, mic controls
│   │   └── TranscriptPanel.tsx    live transcript + evidence markers
│   └── lib/livekit-client.ts
├── docker-compose.yml             Postgres + local speech services
├── scripts/setup-local-ai.ps1     one-time model download and warmup
└── docs/project-brief.md          product model, phases, guardrails
```

## Run

See [SETUP.md](SETUP.md) for the full path. Short version, once configured:

```powershell
scripts\setup-local-ai.ps1                                       # local services/models
cd backend; .venv\Scripts\Activate.ps1; python -m db.init         # schema, once
```

Then three terminals:

```powershell
cd backend;  .venv\Scripts\Activate.ps1; uvicorn api.main:app --reload --port 8000
cd backend;  .venv\Scripts\Activate.ps1; python -m agent.worker dev
cd frontend; npm run dev
```

Open <http://localhost:3000>.

The agent worker is a separate process from the API and is the one most often
forgotten — without it the browser joins a room where nobody is listening.

## Guardrails

These are product constraints, enforced in the prompts and in the schema:

- The integrity monitor reports observations. It never returns a cheating
  verdict.
- Pace, fillers and pauses are delivery signals. They are never used to infer
  confidence, personality, honesty or trustworthiness.
- The interviewer never tells the candidate their score, or that they are being
  scored, during the interview.
- No latency claim is stated as a guarantee. Per-turn evaluation latency is
  measured and recorded on every score row (`details.latency_ms`); report it as
  measured P50/P95.
- Persistence is best-effort. A database outage degrades the recording, never
  the interview.

## Product phases

1. Natural realtime voice loop with interruption handling.
2. Adaptive competency graph, durable transcript, scores, and tracing.
3. Personalized planning, deep evaluation, exact evidence, audio delivery
   mechanics, observation-only integrity signals, dashboards, and reporting.
