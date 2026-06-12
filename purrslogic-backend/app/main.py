import os
import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
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
from app.services.gcs_upload_service import gcs_upload_service
from app.services.google_oauth_service import google_oauth_service
from app.services.calendar_triage_service import calendar_triage_service
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


async def _get_calendar_service(user_id: str) -> GoogleCalendarService:
    """Per-user OAuth tokens first; legacy config/token.json as dev fallback."""
    calendar_service = await GoogleCalendarService.for_user(user_id)
    if calendar_service:
        return calendar_service
    try:
        return GoogleCalendarService()
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(
            status_code=401,
            detail=(
                "Google Calendar not connected. "
                f"Visit /api/v1/calendar/oauth/start?user_id={user_id} to authorize."
            ),
        ) from error


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


@app.post("/api/v1/health/upload/signed-url")
async def health_upload_signed_url(
    user_id: str = "peggy_pei_28",
    filename: str = "export.zip",
):
    """Return a signed PUT URL for large exports (bypasses Cloud Run 32 MiB request limit)."""
    try:
        lower = filename.lower()
        content_type = "application/xml" if lower.endswith(".xml") else "application/octet-stream"
        return gcs_upload_service.create_signed_upload_url(
            user_id=user_id,
            filename=filename,
            content_type=content_type,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/v1/health/upload/stream/gcs")
async def upload_apple_health_export_from_gcs(
    user_id: str = "peggy_pei_28",
    object_name: str = "",
    filename: str = "export.zip",
):
    """Parse an object already uploaded via signed GCS URL; streams NDJSON progress."""
    if not object_name:
        raise HTTPException(status_code=400, detail="object_name is required.")
    try:
        gcs_upload_service.validate_object_for_user(object_name, user_id)

        async def stream_and_cleanup():
            with tempfile.TemporaryDirectory() as tmp_dir:
                upload_path = Path(tmp_dir) / PurePosixPath(filename or "export.zip").name
                await asyncio.to_thread(
                    gcs_upload_service.download_object_to_file,
                    object_name,
                    upload_path,
                )
                if upload_path.stat().st_size == 0:
                    yield json.dumps({"type": "error", "detail": "Empty file upload."}) + "\n"
                    return
                try:
                    async for line in health_ingest_service.process_upload_stream_from_path(
                        file_path=upload_path,
                        filename=filename or "export.zip",
                        user_id=user_id,
                    ):
                        yield line
                finally:
                    await asyncio.to_thread(gcs_upload_service.delete_object, object_name)

        return StreamingResponse(stream_and_cleanup(), media_type="application/x-ndjson")
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
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


@app.get("/api/v1/health/analytics")
async def get_health_analytics(user_id: str = "peggy_pei_28"):
    """Rolling averages, monthly/yearly summaries, and export date range."""
    try:
        result = await health_ingest_service.get_analytics(user_id=user_id)
        if result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=result.get("message"))
        return result
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/v1/calendar/oauth/start")
async def calendar_oauth_start(user_id: str):
    """Redirect browser to Google OAuth consent (Web client required)."""
    try:
        return RedirectResponse(await google_oauth_service.authorization_url(user_id))
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/v1/calendar/oauth/callback")
async def calendar_oauth_callback(code: str, state: str):
    """OAuth redirect target — persists refresh token per user_id (state)."""
    try:
        await google_oauth_service.exchange_code(code=code, user_id=state)
        return RedirectResponse(f"/health?calendar=connected&user_id={state}")
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/v1/calendar/oauth/status")
async def calendar_oauth_status(user_id: str):
    return await google_oauth_service.get_status(user_id)


@app.delete("/api/v1/calendar/oauth/disconnect")
async def calendar_oauth_disconnect(user_id: str):
    return await google_oauth_service.disconnect(user_id)

# Fetch unique historical event titles for onboarding
@app.get("/api/v1/calendar/onboarding-history")
async def get_onboarding_history(user_id: str, months: int = 3):
    try:
        calendar_service = await _get_calendar_service(user_id)
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
        return await calendar_triage_service.run_triage(
            user_id=user_id,
            simulate_budget=simulate_budget,
            bq_service=bq_service,
            brain_service=brain_service,
            legacy_brain_service=legacy_brain_service,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/v1/calendar/today/stream")
async def get_today_calendar_stream(
    user_id: str = "peggy_pei_28",
    simulate_budget: Optional[int] = None,
):
    """NDJSON progress while running calendar triage (same final payload as /today)."""
    return StreamingResponse(
        calendar_triage_service.run_triage_stream(
            user_id=user_id,
            simulate_budget=simulate_budget,
            bq_service=bq_service,
            brain_service=brain_service,
            legacy_brain_service=legacy_brain_service,
        ),
        media_type="application/x-ndjson",
    )