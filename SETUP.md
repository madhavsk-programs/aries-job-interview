# ARIES-Voice — setup and manual steps

Everything a fresh machine needs. Items marked **YOU** cannot be automated —
they need an account or a click in someone else's dashboard. This setup is
designed for local AI plus the LiveKit free tier and does not require a card.

---

## 1. Accounts and credentials

| # | Service | What you need | Cost | Required for |
|---|---|---|---|---|
| 1 | **LiveKit Cloud** | Project URL, API key, API secret | Free tier is enough for development | Phase 1 — all voice |
| 2 | **Local AI** | Native Ollama + Dockerized Faster-Whisper and Kokoro | Free, no account | Voice + evaluation |
| 3 | **Postgres 17 + pgvector** | Local container | Free | Phase 2 storage |
| 4 | **Langfuse Cloud** | Public key + secret key | Free tier (hobby) | Optional — tracing |

### 1.1 LiveKit — **YOU**

1. Sign up at <https://cloud.livekit.io> and create a project.
2. Go to **Settings → Keys → Create key**.
3. Copy three values into `backend/.env`:
   - `LIVEKIT_URL` — looks like `wss://yourproject-xxxxxx.livekit.cloud`
   - `LIVEKIT_API_KEY` — starts with `API`
   - `LIVEKIT_API_SECRET`

The secret is shown once. If you lose it, make a new key.

> The API key and secret stay on the server. The browser only ever receives a
> short-lived (30 min) JWT minted by `POST /api/sessions`. Never put LiveKit
> credentials in `frontend/.env.local` — anything with `NEXT_PUBLIC_` on it is
> shipped to the browser.

### 1.2 Local AI — no account or API key

ARIES runs all model inference on this computer:

- **Ollama + Qwen 3 4B** — local conversational follow-ups, résumé parsing, scoring, and reports.
- **Nomic Embed Text** — local 768-dimension question retrieval vectors.
- **Faster-Whisper Small English** — speech-to-text on the NVIDIA GPU.
- **Kokoro** — local text-to-speech.

Run `scripts\setup-local-ai.ps1` once after Docker Desktop is running. It starts
the services, downloads the models, warms up the interviewer, and updates the
question index. The first run downloads several gigabytes; later starts reuse
the native Ollama cache and Docker volumes. No candidate audio, résumé text, or
model prompt is sent to Gemini or OpenAI.

### 1.3 Postgres — **YOU** (install Docker Desktop)

Docker Desktop is installed on this machine and runs Postgres plus the local
speech service. Native Ollama provides the language model. Start Docker Desktop,
then use the setup script from section 5.

**Option A — Docker Desktop (recommended).** Install from
<https://www.docker.com/products/docker-desktop/>, then from the repo root:

```powershell
docker compose up -d
```

That starts `pgvector/pgvector:pg17` on port 5432 with user/password/db all
`aries`, matching the `DATABASE_URL` already in `.env.example`.

**Option B — native Postgres.** Install Postgres 17, then install the pgvector
extension, create a database, and point `DATABASE_URL` at it.

**Option C — skip storage for now.** Set `PERSISTENCE_ENABLED=false` in
`backend/.env`. The voice loop, the adaptive questioning, and the live
transcript panel all work fully without a database; only the stored transcript
and the `/transcript` endpoint go away. This is a real fallback, not a
degraded mode — every database write in the codebase is best-effort by design.

### 1.4 Langfuse — **YOU**, optional

1. Sign up at <https://cloud.langfuse.com>, create a project.
2. **Settings → API keys → Create**.
3. Put `LANGFUSE_PUBLIC_KEY` (starts `pk-lf-`) and `LANGFUSE_SECRET_KEY`
   (starts `sk-lf-`) in `backend/.env`.

If you are in the EU, set `LANGFUSE_HOST=https://cloud.langfuse.com`;
for the US region use `https://us.cloud.langfuse.com`.

Leave both blank and tracing silently disables itself. Nothing else changes.

---

## 2. Local toolchain

Already verified working on this machine:

| Tool | Required | Found here |
|---|---|---|
| Python | 3.11+ | 3.14.2 ✅ |
| Node.js | 20+ | 24.13.0 ✅ |
| npm | 10+ | 11.6.2 ✅ |
| Docker Desktop | Postgres + local speech | installed ✅ |
| Ollama | Local language model + embeddings | installed ✅ |

---

## 3. Dependencies

### Backend — `backend/requirements.txt`

Installed and confirmed working on Python 3.14:

```
fastapi, uvicorn[standard]          API server
pydantic, pydantic-settings         typed config from .env
python-dotenv                       .env loading in the agent worker
python-multipart, pypdf            in-memory PDF resume upload and text extraction
livekit-api                         mints room JWTs
livekit-agents[openai,silero]      local pipeline adapters + voice activity detection
httpx                              Ollama structured output and embeddings
langgraph                           fast_evaluate -> decide graph
sqlalchemy[asyncio], asyncpg        async Postgres
pgvector                            vector column (Phase 3 retrieval)
greenlet                            required by SQLAlchemy async
opentelemetry-sdk                   tracing
opentelemetry-exporter-otlp-proto-http   ships spans to Langfuse
```

### Frontend — `frontend/package.json`

```
next, react, react-dom              app shell
livekit-client                      WebRTC + data channel
@livekit/components-react           room context, mic controls, audio renderer
@livekit/components-styles          base styles for those components
typescript, @types/*                dev only
```

---

## 4. Configure

```powershell
# from the repo root
copy backend\.env.example backend\.env
copy frontend\.env.local.example frontend\.env.local
```

Then edit `backend/.env` and fill in the values from section 1. The frontend
file needs no changes for local development.

Minimum to get a talking interview: `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
and `LIVEKIT_API_SECRET`. Local model services need no keys. Set
`SESSION_SIGNING_SECRET` to a long random value before exposing the API beyond
localhost.

---

## 5. Install and run

Three terminals. Do these once:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```powershell
cd frontend
npm install
```

Start and prepare Postgres plus all local AI services from the repository root:

```powershell
.\scripts\setup-local-ai.ps1
```

This is the only slow first-time step. Keep Docker Desktop running while using
ARIES. The script also creates the database schema and local vector index.

Then, three terminals, all running at once:

```powershell
# 1 — API
cd backend; .venv\Scripts\Activate.ps1; uvicorn api.main:app --reload --port 8000
```

```powershell
# 2 — realtime agent worker  (this is the one people forget)
cd backend; .venv\Scripts\Activate.ps1; python -m agent.worker dev
```

```powershell
# 3 — frontend
cd frontend; npm run dev
```

Open <http://localhost:3000>.

On the setup page, the candidate can upload a text-based PDF resume (maximum
5 MB and 15 pages). ARIES extracts its text in memory, asks local Ollama to organize
the name, likely role, skills, summary, experience, and education, and fills the
editable form. The uploaded file itself is not written to disk. Scanned or
password-protected PDFs are rejected; the candidate can still fill the fields
manually.

> Use `localhost`, not your LAN IP. Browsers only grant microphone access on a
> secure origin, and `localhost` counts as one while a bare IP does not.

---

## 6. Verify

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/health/ai
```

The first response reports the API. The second must contain `"ready":true` and
shows exactly which local service or model is missing when setup is incomplete.

The decision policy has offline tests that need no keys and no database:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -m tests.test_decide
```

---

## 7. Acceptance checks

**Phase 1 — voice loop**

1. The browser joins the room and publishes microphone audio.
2. The interviewer greets you and holds a spoken conversation.
3. Talking over the interviewer cuts it off; it does not restart its sentence.
4. Saying "mm-hmm" while it talks does not derail it. The worker logs
   `false interruption (backchannel)` when it correctly ignores one.

**Phase 2 — adaptive loop**

5. Give a deliberately vague answer. The next thing you hear is a follow-up on
   that answer, not a new topic. The worker logs `score_answer action=probe`.
6. Give a specific, detailed answer. The interviewer moves to a new
   competency. The worker logs `action=advance`.
7. The transcript panel fills in as you speak, and an evidence marker appears
   under each of your answers with a score and the quote behind it.
8. With Postgres running, the transcript reloads after refresh using the
   session-scoped access token stored by the browser.

**Phase 3 — evidence and reporting**

9. Start from `/setup` with a role, job description, or resume. The resulting
   competency plan is stored with the session, contains seven unique topics,
   and explicitly references the candidate's target role and résumé details.
10. Deep technical/STAR scores and exact-substring evidence appear after each
    answer without delaying the next spoken response.
11. Leave the room, then open `/report/<sessionId>` for evidence-linked
    feedback and delivery mechanics.
12. Open `/review/<sessionId>` for the auto-refreshing reviewer timeline.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser connects, interviewer never speaks | Agent worker not running | Start terminal 2: `python -m agent.worker dev` |
| Setup says Ollama or Speaches is offline | The native Ollama service or speech container is not ready | Start Docker Desktop, then run `.\scripts\setup-local-ai.ps1` |
| Setup says a model is not downloaded | First-time model download was interrupted | Run `.\scripts\setup-local-ai.ps1` again; completed layers are reused |
| Worker reports CUDA out of memory | Another GPU-heavy app is using VRAM | Close games/model tools, restart `ollama` and `speaches`, then restart the worker |
| `pydantic_core.ValidationError` on startup | `backend/.env` missing or a required LiveKit value blank | Check `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` |
| No microphone prompt | Page not on `localhost`/HTTPS | Use `http://localhost:3000` |
| `ImportError: DLL load failed ... Application Control policy` | Windows blocked a freshly-written native DLL on first load | Re-run the command; it clears after the first attempt. If it persists, exclude the `.venv` folder in Windows Security |
| `connection refused` on port 5432 | Postgres not up | Run `.\scripts\setup-local-ai.ps1`, or set `PERSISTENCE_ENABLED=false` |
| Transcript panel stays empty | Data channel messages not arriving | Confirm the token has `canPublishData` and that the worker logs turns |
| Spans never reach Langfuse | Wrong region host | US projects need `LANGFUSE_HOST=https://us.cloud.langfuse.com` |

The only external credential is the LiveKit project used for browser-to-worker
audio transport. All model inference and Postgres storage run locally.
