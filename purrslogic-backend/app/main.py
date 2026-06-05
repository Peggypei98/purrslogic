import os
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv
from typing import Optional

# Import all custom services and databases
from app.services.bigquery_service import BigQueryService
from app.services.calendar_service import GoogleCalendarService
from app.config.database import db
from app.schemas.user_schema import UserOnboardingSubmit
from app.services.classifier_service import DynamicEventClassifierService
from app.services.recovery_service import MicroRecoveryService
from app.services.gemini_service import PurrslogicBrainService
# from pymongo import MongoClient
# from pymongo.errors import ConnectionFailure
# from app.services.gemini_service import GeminiService


# Load environment variables
load_dotenv()

app = FastAPI(
    title="Purrslogic AI Agent API",
    description="The brain center for personalized proactive calendar triaging.",
    version="1.0.0"
)

# Initialize services
bq_service = BigQueryService() if BigQueryService else None
# Initialize the classification service
classifier_service = DynamicEventClassifierService()
# Initialize the recovery tool engine
recovery_service = MicroRecoveryService() 
# Initialize the Gemini reasoning engine
brain_service = PurrslogicBrainService()
    

@app.get("/")
async def root():
    return {"status": "online", "project": "Purrslogic", "version": "V1-Core"}

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
        if isinstance(raw_events, dict) and "error" in raw_events:
            raise HTTPException(status_code=400, detail=raw_events["error"])
            
        # 3. Dynamic 5D energy matrix matching & summation
        classified_events, total_mental_cost, total_physical_cost = classifier_service.calculate_and_tag_agenda(
            raw_events=raw_events,
            custom_rules=custom_rules
        )
        total_agenda_cost = total_mental_cost + total_physical_cost

        # 4. Defensive handling for health metrics budget
        if simulate_budget is not None:
            today_health_budget = simulate_budget
        else:
            today_health_budget = bq_service.get_today_health_budget(user_id=user_id) if bq_service else 45

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
            
        # 7. Bundle everything and invoke Gemini reasoning
        payload_for_ai = {
            "triage_summary": {
                "status_code": triage_status,
                "is_overloaded_warning": is_overloaded,
                "physiological_budget": today_health_budget,
                "total_agenda_cost_burn": total_agenda_cost,
                "remaining_net_energy": remaining_energy_net
            },
            "proactive_interventions": recommendations,
            "events": classified_events
        }
        
        # Invoke the advanced Purrslogic Brain (including Tool Calling execution loop)
        brain_response = brain_service.generate_triage_coaching(triage_data=payload_for_ai)

        return {
            "status": "success",
            "user_id": user_id,
            "triage_summary": payload_for_ai["triage_summary"],
            "agent_decision_center": brain_response.get("agent_coaching_text"),
            "proactive_interventions": brain_response.get("automated_actions_executed", []),
            "events": classified_events
        }
        
        
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))