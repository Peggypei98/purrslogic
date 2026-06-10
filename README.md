# Purrslogic

A proactive wellness AI agent that triages your Google Calendar against a physiological energy budget and autonomously recommends (and schedules) micro-recovery interventions when you are overloaded.

> **Status:** Demo / work-in-progress. Core agent loop is functional; some integrations are stubbed for local development.

---

## What It Does

1. **Reads** today's Google Calendar events
2. **Tags** each event with a personalized 5D energy matrix (mental cost, physical cost, battery impact, etc.)
3. **Compares** total agenda cost against a daily health budget (from BigQuery or a simulated value)
4. **Detects** energy overload and ranks micro-recovery options (pet cats, SLU walk, breathing, etc.)
5. **Reasons** via Gemini 2.5 Flash with multi-turn tool calling:
   - **Short-term memory** — Arize Phoenix trace introspection
   - **Long-term memory** — MongoDB Atlas Vector Search via **official MongoDB MCP Server**
   - **Calendar actions** — insert / delete events (stub in demo mode)

---

## Architecture

```
Google Calendar ──► Classifier (5D matrix) ──► Energy Triage
                                                    │
Apple Watch / BQ ──► Health Budget ────────────────┤
                                                    ▼
MongoDB MCP Server ──► Atlas Vector Search ──► Gemini Agent ◄── Phoenix (traces)
                              │
MongoDB (user rules) ─────────┘
                              ▼
                    Calendar tools + Coaching report
```

| Layer | Tech |
|-------|------|
| API | FastAPI, Motor (async MongoDB) |
| Agent orchestration | **Google ADK** (`google-adk` Runner + `LlmAgent`) |
| LLM | Google Gemini 2.5 Flash + tool calling |
| Short-term memory | Arize Phoenix + OpenInference |
| Long-term memory | MongoDB MCP Server → Atlas `$vectorSearch` (`gemini-embedding-001`, 768-dim) |
| Calendar | Google Calendar API (read-only OAuth) |
| Health data | BigQuery (mock budget available for demo) |

---

## Project Structure

```
purrslogic/
├── README.md
└── purrslogic-backend/
    ├── app/
    │   ├── main.py                 # FastAPI routes
    │   ├── config/
    │   │   ├── database.py         # MongoDB Atlas connection
    │   │   └── observability.py    # Phoenix instrumentation
    │   └── services/
    │       ├── gemini_service.py   # Multi-turn agent brain
    │       ├── vector_service.py   # RAG + embeddings (queries via MCP)
    │       ├── mongodb_mcp_service.py  # Day 18: official MongoDB MCP client
    │       ├── introspection_service.py
    │       ├── calendar_service.py
    │       ├── classifier_service.py
    │       ├── recovery_service.py
    │       └── bigquery_service.py
    ├── config/                     # Credentials (gitignored)
    └── requirements.txt
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/health` | **Apple Health upload UI** (export zip → analyze) |
| `POST` | `/api/v1/health/upload` | Parse export.zip / export.xml |
| `GET` | `/api/v1/health/recovery-summary` | Latest daily recovery metrics |
| `GET` | `/api/v1/calendar/today` | Full triage + Gemini agent loop |
| `GET` | `/api/v1/adk/status` | Google ADK agent configuration |
| `GET` | `/api/v1/mcp/status` | MongoDB MCP Server connection status |
| `GET` | `/api/v1/knowledge/search?q=cat` | Test vector RAG via MongoDB MCP |
| `GET` | `/api/v1/calendar/onboarding-history` | Historical event titles for onboarding |
| `POST` | `/api/v1/calendar/onboarding-submit` | Save user 5D heuristic rules to MongoDB |
| `GET` | `/api/v1/user/profile` | Read user profile |

### Demo: force energy overload

```bash
curl "http://127.0.0.1:8000/api/v1/calendar/today?user_id=peggy_pei_28&simulate_budget=5"
```

Use `simulate_budget=5` when your calendar cost is ~8 — this triggers `ENERGY_OVERLOAD_WARNING` and the full tool chain.

---

## Prerequisites

- Python 3.11+
- **Node.js 20+** (runs `mongodb-mcp-server` via `npx`)
- MongoDB Atlas cluster (Vector Search index required for RAG)
- Google Gemini API key
- Google Calendar OAuth credentials (`calendar-client-secret.json`)
- GCP service account key for BigQuery (`purrslogic-gcp-key.json`) — optional if using `simulate_budget`

---

## Setup

### 1. Clone and install

```bash
cd purrslogic-backend
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
| `calendar-client-secret.json` | Google Calendar OAuth |
| `token.json` | Auto-generated after first OAuth login |
| `purrslogic-gcp-key.json` | BigQuery / GCP access |

### 4. MongoDB Atlas Vector Search index

In Atlas → **Search** → create index on collection `knowledge_base`:

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

Wait until the index status is **Active**. On first startup, the app seeds 3 wellness knowledge documents automatically.

### 5. Run

```bash
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000/docs
- Phoenix UI: http://localhost:6006

---

## Implemented Features

- [x] 5D energy matrix event classification (MongoDB-backed user rules)
- [x] Energy budget accounting + overload detection
- [x] Micro-recovery recommendation engine
- [x] Gemini multi-turn tool calling loop
- [x] Arize Phoenix LLM observability + short-term introspection
- [x] MongoDB Atlas Vector Search RAG (long-term semantic memory)
- [x] **Day 18:** Official MongoDB MCP Server (`aggregate` tool for vector search)
- [x] **Day 19:** Safety guardrails — runtime block on IMMOVABLE calendar deletes
- [x] **Day 20:** Performance tuning — model params, parallel prefetch, slim agent payloads
- [x] Google Calendar read (today's events)
- [x] Demo mode via `simulate_budget` query param

## Work in Progress

- [ ] Real Google Calendar write (delete/insert are currently stubs)
- [x] Apple Health zip upload UI (`/health`) + in-app parse (方案 A)
- [ ] Auto-sync GCS → BigQuery load job (manual `gsutil` + BQ tables today)
- [ ] OAuth write scope for calendar modifications
- [x] Google Cloud Agent Builder via ADK (`purrslogic_agent/`)
- [ ] Cloud Run deploy (hackathon hosted URL)

### Apple Health upload (方案 A)

1. Open **http://127.0.0.1:8000/health** — step-by-step iPhone export guide + zip upload UI
2. Or CLI (same parser as before):

```bash
cd purrslogic-backend
python scripts/parse_health.py ~/Downloads/export.zip --csv-dir ./output
# Optional: gsutil cp output/apple_health_*.csv gs://YOUR_BUCKET/health/
```

Upload results are stored in MongoDB (`health_uploads`) and feed `/api/v1/calendar/today` energy budget automatically.

### Performance tuning (Day 20)

Active knobs live in `app/config/model_config.py`. Inspect at runtime:

```bash
curl http://127.0.0.1:8000/api/v1/adk/status
```

Optional `.env` overrides: `PURRSLOGIC_TEMPERATURE`, `PURRSLOGIC_THINKING_BUDGET_OVERLOAD`, `PURRSLOGIC_PHOENIX_LIMIT`, etc.

---

## License

MIT — see [LICENSE](LICENSE).
