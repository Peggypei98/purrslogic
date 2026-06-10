import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from typing import Optional

# Import all custom services and databases
from app.services.bigquery_service import BigQueryService
from app.services.calendar_service import GoogleCalendarService
from app.config.database import db
from app.schemas.user_schema import UserOnboardingSubmit
from app.services.classifier_service import DynamicEventClassifierService
from app.services.recovery_service import MicroRecoveryService
from app.services.adk_brain_service import AdkBrainService
from app.services.guardrail_service import guardrail_service
from app.services.gemini_service import PurrslogicBrainService
from app.services.health_ingest_service import health_ingest_service
from app.services.vector_service import MongoDBVectorSearchService
from app.services.mongodb_mcp_service import mongodb_mcp
from app.config.model_config import TRIAGE_MODEL, performance_profile
from app.config.observability import init_agent_observability
# from pymongo import MongoClient
# from pymongo.errors import ConnectionFailure
# from app.services.gemini_service import GeminiService


# Load environment variables
load_dotenv()

# Initialize the observability system
init_agent_observability()

vector_search_api = MongoDBVectorSearchService()
adk_brain_service = AdkBrainService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await vector_search_api.seed_initial_knowledge()
    except Exception as error:
        print(f"⚠️ [Vector RAG] Startup seed skipped: {error}")
    try:
        await mongodb_mcp.connect()
    except Exception as error:
        print(f"⚠️ [MongoDB MCP] Startup connect skipped: {error}")
    yield
    await adk_brain_service.shutdown()
    await mongodb_mcp.disconnect()


app = FastAPI(
    title="Purrslogic AI Agent API",
    description="The brain center for personalized proactive calendar triaging.",
    version="1.0.0",
    lifespan=lifespan,
)

# Initialize services (BigQuery optional — app runs without GCP key)
try:
    bq_service = BigQueryService()
except FileNotFoundError as error:
    print(f"⚠️ [BigQuery] {error}")
    bq_service = None
# Initialize the classification service
classifier_service = DynamicEventClassifierService()
# Initialize the recovery tool engine
recovery_service = MicroRecoveryService()
# ADK primary brain (singleton); legacy gemini_service kept as fallback
brain_service = adk_brain_service
legacy_brain_service = PurrslogicBrainService()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return {"status": "online", "project": "Purrslogic", "version": "V1-Core"}


@app.get("/health")
async def health_upload_page():
    """Simple UI: iPhone export instructions + Apple Health zip upload."""
    page = STATIC_DIR / "health.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="health.html not found")
    return FileResponse(page)


@app.post("/api/v1/health/upload")
async def upload_apple_health_export(
    user_id: str = "peggy_pei_28",
    file: UploadFile = File(...),
):
    """
    Accept Apple Health export.zip (or export.xml).
    Parses vitals/sleep CSV logic in-process and stores daily recovery + energy budget in MongoDB.
    """
    try:
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        result = await health_ingest_service.process_upload(
            file_bytes=payload,
            filename=file.filename or "export.zip",
            user_id=user_id,
        )
        return result
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/v1/health/upload/stream")
async def upload_apple_health_export_stream(
    user_id: str = "peggy_pei_28",
    file: UploadFile = File(...),
):
    """
    Same as /upload but streams NDJSON progress events while parsing.
    Final line: {"type":"done","result":{...}} or {"type":"error","detail":"..."}
    """
    try:
        payload = await file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        return StreamingResponse(
            health_ingest_service.process_upload_stream(
                file_bytes=payload,
                filename=file.filename or "export.zip",
                user_id=user_id,
            ),
            media_type="application/x-ndjson",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/v1/health/recovery-summary")
async def get_health_recovery_summary(user_id: str = "peggy_pei_28", limit: int = 7):
    """Return latest uploaded Apple Health daily recovery summary from MongoDB."""
    try:
        stored = await health_ingest_service.get_stored_summary(user_id=user_id, limit=limit)
        if stored.get("status") == "not_found" and bq_service:
            bq_rows = bq_service.get_daily_recovery_summary(limit=limit)
            if isinstance(bq_rows, list) and bq_rows:
                return {"status": "success", "source": "bigquery", "daily_recovery_summary": bq_rows}
        if stored.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=stored.get("message"))
        stored["source"] = "mongodb_upload"
        return stored
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

# Fetch unique historical event titles for onboarding
@app.get("/api/v1/calendar/onboarding-history")
async def get_onboarding_history(months: int = 3):
    try:
        calendar_service = GoogleCalendarService()
        unique_titles = calendar_service.get_historical_events(months_back=months)
        
        if isinstance(unique_titles, dict) and "error" in unique_titles:
            raise HTTPException(status_code=400, detail=unique_titles["error"])
            
        return {
            "status": "success",
            "count": len(unique_titles),
            "unique_titles": unique_titles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# Store the 5D matrix textbook rules into MongoDB Atlas cloud memory store
@app.post("/api/v1/calendar/onboarding-submit")
async def submit_onboarding_rules(payload: UserOnboardingSubmit):
    try:
        user_filter = {"user_id": payload.user_id}
        
        # Convert Pydantic model to dictionary format that can be directly inserted into MongoDB
        update_data = {
            "$set": {
                "email": payload.email,
                "onboarding_completed": True,
                "custom_heuristic_rules": [rule.dict() for rule in payload.custom_heuristic_rules]
            }
        }
        
        # Use upsert=True: if the user doesn't exist, create a new document, otherwise overwrite the rules precisely
        await db.user_profiles.update_one(user_filter, update_data, upsert=True)
        
        return {
            "status": "success",
            "message": f"Successfully wrote {len(payload.custom_heuristic_rules)} personalized life energy rules into MongoDB cloud memory store!",
            "user_id": payload.user_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Read the user's custom matrix profile
@app.get("/api/v1/user/profile")
async def get_user_profile(user_id: str = "peggy_pei_28"):
    try:
        profile = await db.user_profiles.find_one({"user_id": user_id})
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found, please complete the onboarding submission first.")
        
        # Remove MongoDB automatically generated ObjectId to prevent JSON serialization failure
        profile.pop("_id", None)
        return {
            "status": "success",
            "profile": profile
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/mcp/status")
async def mongodb_mcp_status():
    """Verify the official MongoDB MCP Server is connected."""
    return {
        "status": "connected" if mongodb_mcp.is_connected else "disconnected",
        "server": "mongodb-mcp-server",
        "transport": "stdio",
        "read_only": True,
    }


@app.get("/api/v1/adk/status")
async def adk_status():
    """Verify Google ADK agent is configured."""
    return {
        "status": "configured",
        "orchestrator": "google-adk",
        "agent_name": "purrslogic_brain",
        "model": TRIAGE_MODEL,
        "performance": performance_profile(),
        "tools": [
            "mongodb_mcp_toolset (aggregate, find)",
            "inspect_past_decisions",
            "search_health_knowledge_base",
            "delete_calendar_event",
            "insert_calendar_event",
        ],
    }


@app.get("/api/v1/knowledge/search")
async def search_knowledge_base(q: str, limit: int = 2, user_id: str = "peggy_pei_28"):
    """Debug endpoint: test Atlas Vector Search without invoking Gemini."""
    try:
        results = await vector_search_api.search_health_knowledge_base(
            query=q,
            limit=limit,
            user_id=user_id,
        )
        if results and results[0].get("status") == "error":
            raise HTTPException(status_code=503, detail=results[0]["message"])
        return {"status": "success", "query": q, "results": results}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Fetch today's calendar events
@app.get("/api/v1/calendar/today")
async def get_today_calendar(
    user_id: str = "peggy_pei_28",
    simulate_budget: Optional[int] = None
):
    try:
        # 1. Fetch custom rules matrix from MongoDB Atlas
        user_profile = await db.user_profiles.find_one({"user_id": user_id})
        custom_rules = user_profile.get("custom_heuristic_rules", []) if user_profile else []
            
        # 2. Fetch raw today's agenda from Google Calendar API
        calendar_service = GoogleCalendarService()
        raw_events = calendar_service.get_today_events()
        if isinstance(raw_events, dict):
            raise HTTPException(status_code=400, detail=raw_events.get("error", "Failed to fetch calendar events"))
            
        # 3. Dynamic 5D energy matrix matching & summation
        classified_events, total_mental_cost, total_physical_cost = classifier_service.calculate_and_tag_agenda(
            raw_events=raw_events,
            custom_rules=custom_rules
        )
        total_agenda_cost = total_mental_cost + total_physical_cost

        # 4. Defensive handling for health metrics budget
        budget_meta = None
        if simulate_budget is not None:
            today_health_budget = simulate_budget
            budget_meta = {"source": "simulated", "source_date": None, "is_fallback": False}
        else:
            resolution = await health_ingest_service.get_budget_resolution(user_id=user_id)
            if resolution and resolution.budget is not None:
                today_health_budget = resolution.budget
                from app.services.health_budget import budget_meta_dict
                budget_meta = budget_meta_dict(resolution)
            elif bq_service:
                today_health_budget = bq_service.get_today_health_budget(user_id=user_id)
                budget_meta = {"source": "bigquery", "source_date": None, "is_fallback": True}
            else:
                today_health_budget = 45
                budget_meta = {"source": "default", "source_date": None, "is_fallback": True}

        # 5. Core Mathematical Energy Accounting Formula
        remaining_energy_net = today_health_budget - total_agenda_cost
        
        # 6. Proactive Overload Triaging Mode
        is_overloaded = remaining_energy_net < 0
        recommendations = []
        triage_status = "HEALTHY_BALANCED"

        if is_overloaded:
            triage_status = "ENERGY_OVERLOAD_WARNING"
            recommendations = recovery_service.get_top_recommendations(
                needed_charge=abs(remaining_energy_net),
                limit=2
            )
            
        # 7. Day 19 safety guardrails — partition deletable vs IMMOVABLE-protected events
        guardrail_service.register_agenda(classified_events)
        deletable_events, protected_events = guardrail_service.partition_events(classified_events)

        # 8. Bundle everything and invoke agent reasoning
        payload_for_ai = {
            "user_id": user_id,
            "triage_summary": {
                "status_code": triage_status,
                "is_overloaded_warning": is_overloaded,
                "physiological_budget": today_health_budget,
                "budget_meta": budget_meta,
                "total_agenda_cost_burn": total_agenda_cost,
                "remaining_net_energy": remaining_energy_net
            },
            "proactive_interventions": recommendations,
            "events": classified_events,
            "safety_guardrails": {
                "policy": "NEVER delete IMMOVABLE events. Runtime blocks unsafe deletes.",
                "deletable_event_ids": [e["event_id"] for e in deletable_events if e.get("event_id")],
                "deletable_events": deletable_events,
                "protected_events": protected_events,
            },
        }
        
        # Invoke Google ADK agent (fallback to legacy gemini loop on failure)
        brain_response = await brain_service.generate_triage_coaching(triage_data=payload_for_ai)
        if "error" in brain_response:
            print(f"⚠️ [ADK Brain] Falling back to legacy gemini_service: {brain_response['error']}")
            brain_response = await legacy_brain_service.generate_triage_coaching(
                triage_data=payload_for_ai
            )

        if "error" in brain_response:
            raise HTTPException(status_code=503, detail=brain_response["error"])

        return {
            "status": "success",
            "user_id": user_id,
            "triage_summary": payload_for_ai["triage_summary"],
            "agent_decision_center": brain_response.get("agent_coaching_text"),
            "proactive_interventions": brain_response.get("automated_actions_executed", []),
            "events": classified_events
        }
        
        
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))