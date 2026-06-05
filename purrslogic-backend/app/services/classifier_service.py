import re

class DynamicEventClassifierService:
    def __init__(self):
        # 🛡️ Default safety value: when a new event completely misses the user's custom rules, the system gives the conservative value
        self.default_matrix = {
            "priority": "FLEXIBLE",
            "mental_cost": 2,
            "physical_cost": 2,
            "battery_impact": 0,
            "focus_type": "SHALLOW_WORK",
            "desire_score": 5
        }

    def classify_single_event(self, summary: str, description: str, custom_rules: list) -> dict:
        """
        Use regular expression to match the event title and description against the user's custom rules list stored in MongoDB
        """
        text_to_check = f"{summary} {description or ''}".lower()

        # Loop through each custom rule retrieved from the database
        for rule in custom_rules:
            pattern = rule.get("pattern", "").lower()
            if pattern and re.search(pattern, text_to_check):
                # Perfect hit! Return the five-dimensional matrix assigned to the user at the time of the pattern
                return rule.get("assigned_matrix", self.default_matrix)
        
        # If all rules miss, take the default defensive value
        return self.default_matrix

    def calculate_and_tag_agenda(self, raw_events: list, custom_rules: list) -> tuple:
        """
        Batch process today's events, dynamic tagging, and calculate the total mental and physical energy consumption simultaneously
        """
        tagged_events = []
        total_mental = 0
        total_physical = 0

        for event in raw_events:
            summary = event.get("summary", "")
            description = event.get("description", "")

            # 1. Dynamically calculate the 5D life energy characteristics of the event
            energy_matrix = self.classify_single_event(summary, description, custom_rules)
            
            # 2. Add up the total energy consumption value of today
            total_mental += energy_matrix.get("mental_cost", 0)
            total_physical += energy_matrix.get("physical_cost", 0)

            # 3. Perfect dictionary merge (Python 3.9+): preserve the original GCal fields and insert the structured energy_matrix
            tagged_event = event.copy()
            tagged_event["energy_matrix"] = energy_matrix
            tagged_events.append(tagged_event)

        return tagged_events, total_mental, total_physical