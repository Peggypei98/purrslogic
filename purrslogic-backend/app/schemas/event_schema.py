from pydantic import BaseModel, Field, validator
from enum import Enum
from typing import Optional, List
from datetime import datetime

# 1. define the four quadrants of Priority
class EventPriority(str, Enum):
    IMMOVABLE = "IMMOVABLE"
    IMPORTANT = "IMPORTANT"
    FLEXIBLE = "FLEXIBLE"
    OPTIONAL = "OPTIONAL"

# 2. define the cognitive scenarios of Focus Type
class FocusType(str, Enum):
    DEEP_WORK = "DEEP_WORK"
    SHALLOW_WORK = "SHALLOW_WORK"
    SOCIAL = "SOCIAL"
    RECOVERY = "RECOVERY"
    CREATIVE = "CREATIVE"
    ADMIN = "ADMIN"

# 🌟 Core: five-dimensional life energy matrix model
class EnergyMatrix(BaseModel):
    priority: EventPriority = Field(..., description="priority of the event in the four quadrants")
    mental_cost: int = Field(..., ge=0, le=10, description="mental energy consumption (0~10)")
    physical_cost: int = Field(..., ge=0, le=10, description="physical energy consumption (0~10)")
    battery_impact: int = Field(..., ge=-10, le=10, description="emotional charging coefficient (-10 ~ +10)")
    focus_type: FocusType = Field(..., description="focus type")
    desire_score: int = Field(..., ge=0, le=10, description="subjective desire score (0~10)")

# 3. Google Calendar context information
class GCalContext(BaseModel):
    status: str = "accepted"
    is_recurring: bool = False
    is_all_day: bool = False

# 4. detailed time interval information
class TimeSlots(BaseModel):
    start_time: str
    end_time: str
    duration_minutes: int
    day_of_week: int  # 1 (Mon) ~ 7 (Sun)
    hour_of_day: int  # 0 ~ 23

# 5. this is the future complete calendar event model that will be stored in MongoDB or received from the frontend
class PurrslogicEvent(BaseModel):
    user_id: str
    google_event_id: str
    summary: str
    description: Optional[str] = ""
    gcal_context: GCalContext
    time_slots: TimeSlots
    energy_matrix: Optional[EnergyMatrix] = None # Onboarding stage can be None
    is_labeled_by_user: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)