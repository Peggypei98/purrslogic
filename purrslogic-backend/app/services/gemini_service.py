import json
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.services.calendar_service import GoogleCalendarService
from app.services.introspection_service import AgentIntrospectionService

load_dotenv()

_OVERLOAD_MARKERS = ("503", "UNAVAILABLE", "high demand")
_QUOTA_MARKERS = ("429", "RESOURCE_EXHAUSTED", "QUOTA")


class PurrslogicBrainService:
    def __init__(self):
        self.client = genai.Client()
        self.model_name = "gemini-2.5-flash"
        self.calendar_api = GoogleCalendarService()
        self.introspection_api = AgentIntrospectionService()

    def _error_message(self, error: Exception) -> str:
        return str(error).upper()

    def _is_overloaded(self, error: Exception) -> bool:
        message = self._error_message(error)
        return any(marker in message for marker in _OVERLOAD_MARKERS)

    def _is_quota_exhausted(self, error: Exception) -> bool:
        message = self._error_message(error)
        return any(marker in message for marker in _QUOTA_MARKERS)

    def _send_with_retry(self, chat, message, max_retries: int = 3):
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return chat.send_message(message)
            except Exception as error:
                last_error = error
                if self._is_quota_exhausted(error):
                    raise
                if self._is_overloaded(error) and attempt < max_retries - 1:
                    wait_seconds = 2 ** attempt
                    print(
                        f"⚠️ [Gemini Brain] Model busy (503), retrying in {wait_seconds}s "
                        f"(attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(wait_seconds)
                    continue
                raise error from error
        assert last_error is not None
        raise last_error

    def _create_chat(self, model_name: str, config: types.GenerateContentConfig):
        return self.client.chats.create(model=model_name, config=config)

    def generate_triage_coaching(self, triage_data: dict) -> dict[str, Any]:
        """
        Day 16 MCP-enabled engine: always prefetch Phoenix traces, then let Gemini
        reason and optionally invoke calendar tools when overloaded.
        """
        is_overloaded = triage_data.get("triage_summary", {}).get("is_overloaded_warning", False)

        available_tools: dict[str, Any] = {
            "inspect_past_decisions": self.introspection_api.inspect_past_decisions,
        }
        if is_overloaded:
            available_tools["delete_calendar_event"] = self.calendar_api.delete_calendar_event
            available_tools["insert_calendar_event"] = self.calendar_api.insert_calendar_event

        executed_actions_log: list[dict[str, Any]] = []

        # Always prefetch real Phoenix memory so introspection is never hallucinated.
        print("⚙️ [Agent Execution] Prefetching inspect_past_decisions from Phoenix...")
        past_traces = self.introspection_api.inspect_past_decisions(limit=5)
        executed_actions_log.append({
            "tool_invoked": "inspect_past_decisions",
            "arguments": {"limit": 5, "source": "prefetch"},
            "result": past_traces,
        })

        overload_guidance = (
            "Energy overload detected. You MUST call insert_calendar_event and/or "
            "delete_calendar_event after analyzing phoenix_memory_traces."
            if is_overloaded
            else "Energy is balanced. Do NOT modify the calendar; explain why no changes are needed."
        )

        system_instruction = f"""
        You are the proactive core intelligence of 'Purrslogic', equipped with Meta-Cognition.
        You receive verified Phoenix trace memory in phoenix_memory_traces (already fetched for you).

        YOUR ADVANCED OPERATIONAL PROTOCOL:
        1. Read phoenix_memory_traces first. Reference concrete trace_id / action_name values in your report.
        2. If you already injected cat-petting or removed optional tasks recently, acknowledge continuity.
        3. {overload_guidance}
        4. Always include '### 🧠 Agent Self-Introspection Report' citing phoenix_memory_traces evidence.
        """

        payload = {
            "phoenix_memory_traces": past_traces,
            "today_telemetry": triage_data,
        }
        user_prompt = (
            "Analyze the verified Phoenix memory and today's telemetry, then act accordingly:\n\n"
            f"{json.dumps(payload, default=str)}"
        )

        tool_list: list[Any] = [self.introspection_api.inspect_past_decisions]
        if is_overloaded:
            tool_list.extend([
                self.calendar_api.delete_calendar_event,
                self.calendar_api.insert_calendar_event,
            ])

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tool_list,
            temperature=0.2,
        )

        try:
            chat = self._create_chat(self.model_name, config)
            response = self._send_with_retry(chat, user_prompt)

            while response.function_calls:
                print(
                    f"🤖 [Gemini Brain] Advanced Tool call requested! "
                    f"Found {len(response.function_calls)} actions."
                )
                tool_responses = []

                for call in response.function_calls:
                    tool_name = call.name
                    tool_args = dict(call.args) if call.args else {}

                    if tool_name not in available_tools:
                        continue

                    print(
                        f"⚙️ [Agent Execution] Invoking tool: {tool_name} "
                        f"with args: {tool_args}"
                    )
                    try:
                        result = available_tools[tool_name](**tool_args)
                    except Exception as tool_error:
                        result = {"status": "error", "message": str(tool_error)}

                    executed_actions_log.append({
                        "tool_invoked": tool_name,
                        "arguments": tool_args,
                        "result": result,
                    })
                    tool_responses.append(
                        types.Part.from_function_response(
                            name=tool_name,
                            response={"result": result},
                        )
                    )

                response = self._send_with_retry(chat, tool_responses)

            return {
                "agent_coaching_text": (
                    response.text or "Automated meta-cognition remediation loop completed."
                ),
                "automated_actions_executed": executed_actions_log,
                "model_used": self.model_name,
            }

        except Exception as error:
            if self._is_quota_exhausted(error):
                detail = (
                    "Gemini API quota exhausted. Wait ~30s and retry, "
                    "or check billing at https://ai.dev/rate-limit"
                )
            elif self._is_overloaded(error):
                detail = "Gemini model is temporarily overloaded (503). Please retry in a minute."
            else:
                detail = str(error)

            return {
                "error": f"❌ MCP Agent Engine failed: {detail}",
                "automated_actions_executed": executed_actions_log,
            }
