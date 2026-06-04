import os
from fastapi import FastAPI, HTTPException, Body
from dotenv import load_dotenv
# from pymongo import MongoClient
# from pymongo.errors import ConnectionFailure
from app.services.bigquery_service import BigQueryService
from app.services.calendar_service import GoogleCalendarService
from app.services.gemini_service import GeminiService
from app.config.database import db
from app.schemas.user_schema import UserOnboardingSubmit

# Load environment variables
load_dotenv()

app = FastAPI(
    title="Purrslogic AI Agent API",
    description="The brain center for personalized proactive calendar triaging.",
    version="1.0.0"
)
# Initialize services
try:
    bq_service = BigQueryService()
except Exception as e:
    print(f"⚠️ BigQuery Service Initialization Failed: {e}")
    bq_service = None
    

@app.get("/")
async def root():
    return {
        "status": "online",
        "project": "Purrslogic",
        "version": "V1-Core"
    }

# @app.get("/api/health-check")
# async def health_check():
#     return {"status": "healthy", "database": "connected_placeholder"}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("main.py", host="127.0.0.1", port=8000, reload=True)
@app.get("/api/v1/recovery-summary")
async def get_recovery_summary(limit: int = 7):
    if not bq_service:
        raise HTTPException(status_code=500, detail="BigQuery service is unavailable")
    
    data = bq_service.get_daily_recovery_summary(limit=limit)
    
    if isinstance(data, dict) and "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
        
    return {
        "status": "success",
        "count": len(data) if isinstance(data, list) else 0,
        "data": data
    }
    
    
@app.get("/api/v1/calendar/today")
async def get_today_calendar():
    try:
        # initialize the service only when the route is clicked, so it doesn't block Uvicorn startup
        calendar_service = GoogleCalendarService()
        events = calendar_service.get_today_events()
        
        if isinstance(events, dict) and "error" in events:
            raise HTTPException(status_code=400, detail=events["error"])
            
        return {
            "status": "success",
            "count": len(events),
            "events": events
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/v1/calendar/onboarding-history")
async def get_onboarding_history(months: int = 3):
    try:
        calendar_service = GoogleCalendarService()
        unique_titles = calendar_service.get_historical_events(months_back=months)
        
        if isinstance(unique_titles, dict) and "error" in unique_titles:
            raise HTTPException(status_code=400, detail=unique_titles["error"])
            
        return {
            "status": "success",
            "message": "Successfully fetched historical unique events! Please let the user fill in the five-dimensional life energy matrix for these high-frequency events.",
            "count": len(unique_titles),
            "unique_titles": unique_titles
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
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
        result = await db.user_profiles.update_one(user_filter, update_data, upsert=True)
        
        return {
            "status": "success",
            "message": f"Successfully wrote {len(payload.custom_heuristic_rules)} personalized life energy rules into MongoDB cloud memory store!",
            "user_id": payload.user_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
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