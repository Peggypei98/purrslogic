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
   - **Long-term memory** — MongoDB Atlas Vector Search RAG (`text-embedding-004`)
   - **Calendar actions** — insert / delete events (stub in demo mode)

---

## Architecture

```
Google Calendar ──► Classifier (5D matrix) ──► Energy Triage
                                                    │
Apple Watch / BQ ──► Health Budget ────────────────┤
                                                    ▼
MongoDB (rules + RAG) ──► Gemini Agent ◄── Phoenix (traces)
                              │
                              ▼
                    Calendar tools + Coaching report
```

| Layer | Tech |
|-------|------|
| API | FastAPI, Motor (async MongoDB) |
| LLM | Google Gemini 2.5 Flash + tool calling |
| Short-term memory | Arize Phoenix + OpenInference |
| Long-term memory | MongoDB Atlas `$vectorSearch` (768-dim embeddings) |
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
    │       ├── vector_service.py   # RAG + embeddings
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
| `GET` | `/api/v1/calendar/today` | Full triage + Gemini agent loop |
| `GET` | `/api/v1/knowledge/search?q=cat` | Test vector RAG without Gemini |
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
- [x] Google Calendar read (today's events)
- [x] Demo mode via `simulate_budget` query param

## Work in Progress

- [ ] Real Google Calendar write (delete/insert are currently stubs)
- [ ] Live BigQuery / Apple Watch recovery budget (mock returns `45` today)
- [ ] OAuth write scope for calendar modifications
- [ ] `.env.example` and one-command setup script

---

## License

TBD
