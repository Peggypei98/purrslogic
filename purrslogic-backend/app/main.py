import os
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
# from pymongo import MongoClient
# from pymongo.errors import ConnectionFailure
from app.services.bigquery_service import BigQueryService
from app.services.calendar_service import GoogleCalendarService
from app.services.gemini_service import GeminiService

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
        "message": "Welcome to Purrslogic AI Agent Backend Center! 🐈‍⬛"
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