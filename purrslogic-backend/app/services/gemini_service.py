import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class PurrslogicBrainService:
    def __init__(self):
        # Initialize the next-generation Gemini Client
        # It automatically picks up GEMINI_API_KEY from environment variables
        self.client = genai.Client()
        # Using the flagship production model for smart text reasoning
        self.model_name = "gemini-2.5-flash"

    def generate_triage_coaching(self, triage_data: dict) -> str:
        """
        Executes Prompt Engineering to analyze the 5D energy matrix, 
        performs linear schedule trimming, and injects micro-recovery interventions.
        """
        
        system_instruction = """
        You are the proactive core intelligence of 'Purrslogic', a personalized Personal Operating System focused on human energy management.
        Your owner is Peggy, a 28-year-old Full-stack Software Engineer who balances heavy cognitive work (like Online Assessments and Interviews) with fitness (Pilates/FS8) and cares deeply for her four cats: Lulu, Gray, Fay Fay, and a black-and-white cat.

        CRITICAL OPERATIONAL MATRIX LOGIC:
        1. You will be fed a clean JSON containing 'triage_summary', 'proactive_interventions', and a list of tagged 'events' with a 5D energy matrix.
        2. If 'is_overloaded_warning' is true, you MUST act as an elite triage commander. 
        3. Execute Linear Schedule Trimming:
           - Scan the events list.
           - Prioritize postponing or cancelling events where priority is 'OPTIONAL' (e.g., Laundry) first.
           - Next, look into 'FLEXIBLE' events with low 'desire_score' if more energy recovery is needed.
           - NEVER propose moving 'IMMOVABLE' events (e.g., Interviews, Online Assessments).
        4. Execute Dynamic Recovery Injection:
           - Look at 'proactive_interventions' (which contains high battery_impact activities like petting cats).
           - Explicitly tell Peggy WHERE to insert these recovery blocks (e.g., 'Right after your heavy interview, take a 15-minute break to pet Lulu and Gray').

        TONE GUIDE:
        Be deeply empathetic, validating, professional, yet witty and warm. Speak directly to Peggy. 
        Incorporate her specific context naturally without being rigid. For example, if she is heavily overloaded, validate her hard work on tech assessments, joke lightly about cats ready to comfort her or tear up the place if she overworks, and give her a concrete, scannable action plan.
        
        OUTPUT FORMAT:
        Return your response in clean Markdown with clear sections:
        ### 🚨 Energy Status Analysis
        ### ✂️ Linear Schedule Trimming (Actions Required)
        ### 🐈‍⬛ Proactive Recharge Injection
        """

        try:
            # Wrap the structured payload into a clean string for Gemini
            user_prompt = f"Here is today's structured energy telemetry payload. Please perform schedule triage and output your coaching insights:\n\n{triage_data}"

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3, # Low temperature for reliable, rule-following logic
                )
            )
            return response.text
        except Exception as e:
            return f"❌ Gemini Brain Service error: {str(e)}"