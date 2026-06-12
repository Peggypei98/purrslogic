# Purrslogic

**Google Cloud Rapid Agent Hackathon** entry · MongoDB partner track

A proactive wellness AI agent that triages your Google Calendar against a physiological energy budget from Apple Health — and recommends micro-recovery when you are overloaded.

Named after the masters of rest — four cats: Huh, Lulu, Feifei, and Grey.

| | |
|---|---|
| **Live demo** | https://purrslogic-ln4fq7htzq-uc.a.run.app/health |
| **Demo video** | https://youtu.be/7zjOzc6ziD4 |
| **License** | [MIT](LICENSE) |

> **Status:** Hackathon demo / work-in-progress. The full ingest → triage → agent loop runs on Cloud Run. Calendar **write** tools (insert/delete) are **stubs** — the agent recommends actions but does not modify your calendar in production yet.

---

## The Problem

Your calendar treats every hour as equal. Your body does not. Purrslogic bridges that gap by scoring today's agenda against a daily energy budget derived from real Apple Health data — sleep, HRV, resting heart rate, activity, and mobility.

When agenda cost exceeds budget, the agent enters **overload mode**: it pulls short-term memory from Phoenix traces, long-term wellness knowledge from MongoDB Vector Search, and produces a coaching report with guarded calendar recommendations.

---

## How It Works

```
iPhone export.zip ──► Parse & store (MongoDB) ──► Energy budget + 30-day wellness scores
                                                          │
Google Calendar OAuth ──► Today's events ──► 5D classifier ──► Cost vs budget
                                                          │
                                              Overload? ──► Google ADK + Gemini 2.5 Flash
                                                          │     ├─ Phoenix introspection
                                                          │     ├─ MongoDB MCP + Vector RAG
                                                          └──► Coaching report (+ stub calendar actions)
```

### End-to-end flow

1. **Upload** Apple Health `export.zip` from iPhone (or use pre-uploaded data)
2. **View** 30-day wellness scorecard — sleep, vitals, activity, mobility (green / yellow / red)
3. **Connect** Google Calendar via per-user OAuth (read-only)
4. **Run triage** — each event classified with a personalized 5D energy matrix
5. **Compare** total agenda cost vs. today's energy budget (90-day rolling average fallback)
6. **Agent loop** (on overload) — ADK orchestrates Gemini 2.5 Flash with tool calling:
   - **Short-term memory** — Arize Phoenix trace introspection (local dev; optional remote collector on Cloud Run)
   - **Long-term memory** — MongoDB Atlas Vector Search via the **official MongoDB MCP Server**
   - **Calendar actions** — insert/delete tools exist with guardrails, but are **stubs** in this demo

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI, Uvicorn, Motor (async MongoDB) |
| Agent orchestration | **Google ADK** (`google-adk` Runner + `LlmAgent`) |
| LLM | **Gemini 2.5 Flash** + tool calling |
| Short-term memory | Arize Phoenix + OpenInference |
| Long-term memory | MongoDB MCP Server → Atlas `$vectorSearch` (`gemini-embedding-001`, 768-dim) |
| Calendar | Google Calendar API (read-only OAuth per user) |
| Health data | Apple Health XML parser → MongoDB (primary); BigQuery fallback for recovery summary |
| Large uploads | Google Cloud Storage signed URLs (Cloud Run 32 MiB limit bypass) |
| Deploy | Cloud Run · Cloud Build · GCS · Secret Manager (8 GiB RAM, 4 CPU, 900s timeout) |

---

## Project Structure

```
purrslogic/
├── LICENSE
├── README.md
└── purrslogic-backend/
    ├── app/
    │   ├── main.py
    │   ├── config/
    │   │   ├── database.py
    │   │   ├── model_config.py          # Gemini / ADK tuning knobs
    │   │   └── observability.py         # Phoenix instrumentation
    │   ├── database/
    │   │   └── mongodb.py
    │   ├── services/
    │   │   ├── adk_brain_service.py     # Google ADK agent runner
    │   │   ├── apple_health_parser.py   # Memory-efficient export.zip parser
    │   │   ├── calendar_service.py
    │   │   ├── calendar_triage_service.py
    │   │   ├── classifier_service.py    # 5D energy matrix
    │   │   ├── gcs_upload_service.py    # GCS signed URLs
    │   │   ├── gemini_service.py        # Legacy brain (ADK fallback)
    │   │   ├── google_oauth_service.py  # Per-user Calendar OAuth
    │   │   ├── guardrail_service.py     # IMMOVABLE event protection
    │   │   ├── health_analytics_service.py  # Wellness scores
    │   │   ├── health_budget.py
    │   │   ├── health_ingest_service.py
    │   │   ├── introspection_service.py
    │   │   ├── mongodb_mcp_service.py
    │   │   ├── recovery_service.py
    │   │   ├── triage_context.py
    │   │   └── vector_service.py
    │   └── schemas/
    ├── purrslogic_agent/
    │   ├── agent.py                     # ADK root agent + MongoDB MCP toolset
    │   └── tools.py
    ├── static/
    │   └── health.html                  # Upload, wellness dashboard, triage UI
    ├── scripts/
    │   ├── deploy-cloud-run.sh
    │   └── parse_health.py
    ├── config/                          # Credentials (gitignored)
    ├── Dockerfile
    └── requirements.txt
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/health` | Apple Health upload + triage UI |
| `POST` | `/api/v1/health/upload` | Parse `export.zip` / `export.xml` |
| `POST` | `/api/v1/health/upload/stream` | Same, with NDJSON progress stream |
| `POST` | `/api/v1/health/upload/signed-url` | GCS signed PUT URL (large files on Cloud Run) |
| `POST` | `/api/v1/health/upload/stream/gcs` | Parse after GCS upload, NDJSON progress |
| `GET` | `/api/v1/health/recovery-summary` | Latest daily recovery metrics |
| `GET` | `/api/v1/health/analytics` | Rolling aggregates + 30-day wellness scores |
| `GET` | `/api/v1/calendar/oauth/start?user_id=` | Start Google OAuth |
| `GET` | `/api/v1/calendar/oauth/callback` | OAuth redirect target |
| `GET` | `/api/v1/calendar/oauth/status?user_id=` | Calendar connection status |
| `DELETE` | `/api/v1/calendar/oauth/disconnect?user_id=` | Revoke stored tokens |
| `GET` | `/api/v1/calendar/today` | Full calendar triage + agent loop |
| `GET` | `/api/v1/calendar/today/stream` | Triage with NDJSON progress |
| `GET` | `/api/v1/calendar/onboarding-history` | Historical event titles for onboarding |
| `POST` | `/api/v1/calendar/onboarding-submit` | Save user 5D heuristic rules |
| `GET` | `/api/v1/user/profile` | Read user profile |
| `GET` | `/api/v1/adk/status` | ADK agent configuration |
| `GET` | `/api/v1/mcp/status` | MongoDB MCP connection status |
| `GET` | `/api/v1/knowledge/search?q=` | Test vector RAG |

All endpoints accept a `user_id` query param. The `/health` UI generates one automatically and stores it in `localStorage`.

### Demo: force energy overload

When today's agenda is balanced, triage returns early without invoking the agent. Use `simulate_budget=5` to force overload mode:

```bash
curl "https://purrslogic-ln4fq7htzq-uc.a.run.app/api/v1/calendar/today?user_id=YOUR_ID&simulate_budget=5"
```

Also available via checkbox in the `/health` UI.

---

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- **Node.js 20+** (ADK spawns `mongodb-mcp-server` via `npx`)
- MongoDB Atlas cluster with Vector Search index
- Google Gemini API key
- Google Calendar OAuth credentials — **Web application** type

### 1. Clone and install

```bash
git clone https://github.com/Peggypei98/purrslogic.git
cd purrslogic/purrslogic-backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment variables

Create `purrslogic-backend/.env`:

```env
MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/
GEMINI_API_KEY=your_gemini_api_key
```

`MONGODB_URI` is also supported as an alias.

### 3. Credentials (gitignored)

Place in `purrslogic-backend/config/`:

| File | Purpose |
|------|---------|
| `calendar-client-secret.json` | Google OAuth **Web application** client |
| `token.json` | Legacy dev fallback (per-user tokens live in MongoDB) |
| `purrslogic-gcp-key.json` | BigQuery access (optional) |

### 4. Google Calendar OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → **Web application** OAuth client
2. Enable **Google Calendar API**
3. Add authorized redirect URI:
   - Local: `http://127.0.0.1:8000/api/v1/calendar/oauth/callback`
   - Cloud Run: `https://YOUR-SERVICE-URL/api/v1/calendar/oauth/callback`
4. Save JSON as `config/calendar-client-secret.json`
5. Open `/health` → copy your Purrslogic ID → **Connect Google Calendar**

OAuth scope is **read-only** (`calendar.events.readonly`).

### 5. MongoDB Atlas Vector Search index

Atlas → **Search** → create index on collection `knowledge_base`:

- **Index name:** `vector_index`
- **Database:** `purrslogic`

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    }
  ]
}
```

Wait until status is **Active**. On first startup, the app seeds 3 wellness knowledge documents.

### 6. Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000/health | Upload + triage UI |
| http://127.0.0.1:8000/docs | Swagger |
| http://localhost:6006 | Phoenix UI (local dev only) |

---

## Apple Health Upload

1. iPhone: **Health app** → Profile (avatar) → **Export All Health Data** → save `export.zip`
2. Open `/health` → upload the zip
3. Data stored in MongoDB (`health_uploads`) and feeds calendar triage automatically

**Large files on Cloud Run:** the UI uploads via GCS signed URLs (bypasses the 32 MiB HTTP limit). Parsing multi-year exports can take several minutes.

**CLI alternative:**

```bash
cd purrslogic-backend
python scripts/parse_health.py ~/Downloads/export.zip --csv-dir ./output
```

---

## Deploy to Cloud Run

### One-time setup

```bash
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
```

Ensure `.env` has `MONGODB_URL` and `GEMINI_API_KEY`, and `config/calendar-client-secret.json` exists.

### Deploy

```bash
cd purrslogic-backend
export GCP_PROJECT_ID=YOUR_GCP_PROJECT_ID
export GCP_REGION=us-central1
./scripts/deploy-cloud-run.sh
```

The script:

- Enables Cloud Run, Cloud Build, Secret Manager, and Storage APIs
- Builds the Docker image (Python 3.13 + Node 20 for MongoDB MCP)
- Creates a GCS upload bucket (optional CORS via `config/gcs-cors.json`)
- Mounts OAuth client secret from Secret Manager
- Deploys with **8 GiB RAM, 4 CPU, 900s timeout**

### After deploy

1. Add OAuth redirect URI in Google Cloud Console:
   `https://YOUR-SERVICE-URL/api/v1/calendar/oauth/callback`
2. Set env var on Cloud Run:

```bash
gcloud run services update purrslogic --region us-central1 \
  --update-env-vars GOOGLE_OAUTH_REDIRECT_URI=https://YOUR-SERVICE-URL/api/v1/calendar/oauth/callback
```

### Cloud Run notes

- Embedded Phoenix UI does not run on Cloud Run. Set `PHOENIX_COLLECTOR_URL` for remote traces.
- Gemini free-tier rate limits apply to triage (multiple API calls per run).
- Re-deploy after code changes: `./scripts/deploy-cloud-run.sh`

---

## What's Built vs. Roadmap

### Shipped in this demo

- [x] Apple Health zip upload UI with streaming progress (English / Chinese i18n)
- [x] GCS signed-URL upload for large exports on Cloud Run
- [x] 30-day wellness scorecard (sleep, vitals, activity, mobility)
- [x] Energy budget with 90-day rolling average fallback
- [x] Per-user Google Calendar OAuth (read-only)
- [x] 5D energy matrix event classification (MongoDB-backed user rules)
- [x] Overload detection + micro-recovery recommendations
- [x] Google ADK agent + Gemini 2.5 Flash tool-calling loop
- [x] MongoDB Atlas Vector Search RAG via official MongoDB MCP Server
- [x] Arize Phoenix + OpenInference (local dev)
- [x] Safety guardrails — runtime block on IMMOVABLE calendar deletes
- [x] Calendar triage streaming progress UI
- [x] Demo overload via `simulate_budget` query param
- [x] Cloud Run deployment with Secret Manager

### Not yet shipped

- [ ] Real Google Calendar write (insert/delete are stubs — log only, no API call)
- [ ] OAuth write scope for calendar modifications
- [ ] Automated wearable sync (no manual zip upload)
- [ ] Apple Watch / iPhone push notifications for micro-recovery
- [ ] Self-service UI for users to add personal RAG documents
- [ ] Onboarding UI for custom 5D heuristic rules (API exists)
- [ ] Auto-sync GCS → BigQuery pipeline
- [ ] Remote Phoenix collector wired on Cloud Run

---

## Performance Tuning

Knobs live in `app/config/model_config.py`. Inspect active values:

```bash
curl http://127.0.0.1:8000/api/v1/adk/status
```

Optional `.env` overrides: `PURRSLOGIC_TEMPERATURE`, `PURRSLOGIC_THINKING_BUDGET_OVERLOAD`, `PURRSLOGIC_PHOENIX_LIMIT`, `PURRSLOGIC_TRIAGE_MODEL`, etc.

---

## Built With

Python · FastAPI · Google Cloud Run · Cloud Build · Cloud Storage · Secret Manager · Google ADK · Gemini 2.5 Flash · MongoDB Atlas · Vector Search · MongoDB MCP · Arize Phoenix · OpenTelemetry · Google Calendar API · Apple Health

---

## License

MIT — see [LICENSE](LICENSE).
