from typing import List, Dict

class MicroRecoveryService:
    def __init__(self):
        #  Define standard micro-recovery catalog with full 5D energy matrices
        self._recovery_catalog = [
            {
                "activity_id": "pet_cats_15min",
                "title": "Petting Cats (Lulu, Gray, Fay Fay)",
                "duration_minutes": 15,
                "matrix": {
                    "priority": "OPTIONAL",
                    "mental_cost": 0,
                    "physical_cost": 1,
                    "battery_impact": 6,      # Huge emotional recharge!
                    "focus_type": "RECOVERY",
                    "desire_score": 10        # Maximum desire
                }
            },
            {
                "activity_id": "box_breathing_5min",
                "title": "Box Breathing Exercise",
                "duration_minutes": 5,
                "matrix": {
                    "priority": "OPTIONAL",
                    "mental_cost": 0,
                    "physical_cost": 0,
                    "battery_impact": 2,
                    "focus_type": "RECOVERY",
                    "desire_score": 6
                }
            },
            {
                "activity_id": "quick_stretch_10min",
                "title": "Quick Pilates Mat Stretching",
                "duration_minutes": 10,
                "matrix": {
                    "priority": "OPTIONAL",
                    "mental_cost": 1,
                    "physical_cost": 2,
                    "battery_impact": 3,
                    "focus_type": "RECOVERY",
                    "desire_score": 7
                }
            },
            {
                "activity_id": "hydration_walk_15min",
                "title": "Hydration Break & Quick SLU Walk",
                "duration_minutes": 15,
                "matrix": {
                    "priority": "OPTIONAL",
                    "mental_cost": 1,
                    "physical_cost": 2,
                    "battery_impact": 4,
                    "focus_type": "RECOVERY",
                    "desire_score": 8
                }
            }
        ]

    def get_top_recommendations(self, needed_charge: int, limit: int = 2) -> List[Dict]:
        """
        Sort and recommend top recovery activities based on maximum emotional recharge
        (battery_impact) and user desire_score.
        """
        # Sort primarily by emotional battery recharge, then by user preference
        sorted_activities = sorted(
            self._recovery_catalog,
            key=lambda x: (x["matrix"]["battery_impact"], x["matrix"]["desire_score"]),
            reverse=True
        )
        return sorted_activities[:limit]