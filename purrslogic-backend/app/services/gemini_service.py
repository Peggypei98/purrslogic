import os

import google.generativeai as genai


class GeminiService:
    """Handles Gemini LLM calls for triage and proactive insights."""

    def __init__(self):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    async def generate_triage_summary(
        self, recovery_data: list[dict], calendar_context: str
    ) -> str:
        prompt = f"""
You are PurrsLogic, a proactive health-tech AI assistant.

Given the user's recent recovery metrics and upcoming calendar, provide a concise
triage summary with actionable recommendations.

Recovery data:
{recovery_data}

Calendar context:
{calendar_context}
"""
        response = self.model.generate_content(prompt)
        return response.text
