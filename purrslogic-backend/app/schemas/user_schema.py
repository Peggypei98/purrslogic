from pydantic import BaseModel, Field
from typing import List
from app.schemas.event_schema import EnergyMatrix

# Define the structure of a single Heuristic rule
class CustomHeuristicRule(BaseModel):
    pattern: str = Field(
        ..., 
        description="The keyword regex pattern to match against event titles (e.g., 'working' or 'cooking')"
    )
    assigned_matrix: EnergyMatrix = Field(
        ..., 
        description="The 5-dimensional life energy matrix mapped to this specific keyword pattern"
    )

# The complete data structure submitted by the user for initial onboarding
class UserOnboardingSubmit(BaseModel):
    user_id: str = Field(
        ..., 
        description="The unique identifier for the user (e.g., username or auth0 ID)"
    )
    email: str = Field(
        ..., 
        description="The user's registered email address"
    )
    custom_heuristic_rules: List[CustomHeuristicRule] = Field(
        ..., 
        description="List of custom keyword-to-matrix mapping rules configured by the user"
    )