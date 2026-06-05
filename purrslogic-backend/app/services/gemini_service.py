import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv
from app.services.calendar_service import GoogleCalendarService

load_dotenv()

class PurrslogicBrainService:
    def __init__(self):
        # Initialize the next-generation Gemini Client
        # It automatically picks up GEMINI_API_KEY from environment variables
        self.client = genai.Client()
        # Using the flagship production model for smart text reasoning
        self.model_name = "gemini-2.5-flash"
        self.calendar_api = GoogleCalendarService()

    def generate_triage_coaching(self, triage_data: dict) -> str:
        """
        Empowers Gemini to reason over data AND fire tool calls 
        to actively modify Google Calendar when an energy deficit occurs.
        """
        
        # Define the executable tool functions mapping for the agent loop
        available_tools = {
            "delete_calendar_event": self.calendar_api.delete_calendar_event,
            "insert_calendar_event": self.calendar_api.insert_calendar_event
        }
        
        system_instruction = """
        You are the proactive core intelligence of 'Purrslogic'. You possess direct writing access to Peggy's Google Calendar.
        
        YOUR CRITICAL OPERATIONAL PROTOCOL:
        1. Review the input JSON matrix. If 'is_overloaded_warning' is true, you MUST execute tool calls to optimize her day.
        2. Scan her schedule. If there is an 'OPTIONAL' task like 'Laundry', you MUST immediately call 'delete_calendar_event' using its exact summary/context to clear her schedule.
        3. Simultaneously, scan 'proactive_interventions'. You MUST call 'insert_calendar_event' to inject her high-impact recovery blocks (e.g., 'Petting Cats') right after her highest-cognitive events (like Interviews or Online Assessments).
        4. Always output a brief summary to Peggy explaining what automated executive actions you just performed on her calendar.
        """

        try:
            user_prompt = f"Here is today's telemetry payload. Perform dynamic triage and execute necessary tool actions:\n\n{json.dumps(triage_data)}"

            # Pass the raw python functions directly into the next-gen SDK tools list
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[self.calendar_api.delete_calendar_event, self.calendar_api.insert_calendar_event],
                    temperature=0.2
                )
            )

            executed_actions_log = []

            # 🌟 [Tool Calling Engine Core] Parse and execute function calls requested by Gemini
            if response.function_calls:
                print(f"🤖 [Gemini Brain] Tool call requested! Found {len(response.function_calls)} actions.")
                for call in response.function_calls:
                    tool_name = call.name
                    tool_args = call.args
                    
                    if tool_name in available_tools:
                        print(f"⚙️ [Agent Execution] Invoking tool: {tool_name} with args: {tool_args}")
                        # Execute the actual Python function dynamically
                        result = available_tools[tool_name](**tool_args)
                        executed_actions_log.append({
                            "tool_invoked": tool_name,
                            "arguments": tool_args,
                            "result": result
                        })

            return {
                "agent_coaching_text": response.text or "Automated event remediation loop completed successfully.",
                "automated_actions_executed": executed_actions_log
            }

        except Exception as e:
            return {"error": f"❌ Agent Engine failed: {str(e)}"}