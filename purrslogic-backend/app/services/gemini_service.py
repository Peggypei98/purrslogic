import json
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.config.model_config import TRIAGE_MODEL, build_generate_content_config, performance_profile
from app.services.calendar_service import GoogleCalendarService
from app.services.guardrail_service import guardrail_service
from app.services.introspection_service import AgentIntrospectionService
from app.services.triage_context import prefetch_agent_context, slim_triage_for_agent
from app.services.vector_service import MongoDBVectorSearchService, search_health_knowledge_base

load_dotenv()

_OVERLOAD_MARKERS = ("503", "UNAVAILABLE", "high demand")
_QUOTA_MARKERS = ("429", "RESOURCE_EXHAUSTED", "QUOTA")


class PurrslogicBrainService:
    def __init__(self):
        self.client = genai.Client()
        self.model_name = TRIAGE_MODEL
        self.calendar_api = GoogleCalendarService()
        self.introspection_api = AgentIntrospectionService()
        self.vector_search_api = MongoDBVectorSearchService()

    def _error_message(self, error: Exception) -> str:
        return str(error).upper()

    def _is_overloaded_api(self, error: Exception) -> bool:
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
                if self._is_overloaded_api(error) and attempt < max_retries - 1:
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

    async def _execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        if tool_name == "inspect_past_decisions":
            return self.introspection_api.inspect_past_decisions(**tool_args)
        if tool_name == "search_health_knowledge_base":
            return await self.vector_search_api.search_health_knowledge_base(**tool_args)
        if tool_name == "delete_calendar_event":
            return guardrail_service.guarded_delete_calendar_event(
                event_id=tool_args["event_id"]
            )
        if tool_name == "insert_calendar_event":
            return self.calendar_api.insert_calendar_event(**tool_args)
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    async def generate_triage_coaching(self, triage_data: dict) -> dict[str, Any]:
        """
        Day 16 + 17 engine: Phoenix short-term memory, MongoDB RAG long-term memory,
        and calendar tools when energy is overloaded.
        """
        is_overloaded = triage_data.get("triage_summary", {}).get("is_overloaded_warning", False)
        executed_actions_log: list[dict[str, Any]] = []

        guardrail_service.register_agenda(triage_data.get("events", []))

        print("⚙️ [Agent Execution] Parallel prefetch: Phoenix + MongoDB RAG...")
        prefetch_log, past_traces, rag_results = await prefetch_agent_context(
            self.introspection_api,
            self.vector_search_api,
            triage_data,
        )
        executed_actions_log.extend(prefetch_log)

        safety = triage_data.get("safety_guardrails", {})
        deletable_ids = safety.get("deletable_event_ids", [])

        if is_overloaded:
            overload_guidance = (
                "Energy overload detected. Use rag_knowledge_matches to craft a precise recovery block, "
                "then call insert_calendar_event and/or delete_calendar_event ONLY for deletable_event_ids."
            )
        else:
            overload_guidance = (
                "Energy is balanced. Do NOT modify the calendar. Use rag_knowledge_matches for coaching only."
            )

        system_instruction = f"""
        You are the ultimate proactive core intelligence of 'Purrslogic'.
        You possess Short-term memory (Phoenix traces) AND Long-term memory (MongoDB Atlas via the official MongoDB MCP Server).

        YOUR FULL-STACK PROTOCOL:
        1. Read phoenix_memory_traces first. Reference concrete trace_id / action_name values in
           '### 🧠 Agent Self-Introspection Report'.
        2. Read rag_knowledge_matches (prefetched via MongoDB MCP aggregate + Atlas Vector Search).
           Cite specific title/content in '### 📚 Long-Term RAG Knowledge Retrieval'.
        3. proactive_interventions in today_telemetry are system pre-scored suggestions;
           rag_knowledge_matches provide detailed execution steps — use both together.
        4. {overload_guidance}
        5. SAFETY: NEVER delete IMMOVABLE events. Only delete from deletable_event_ids: {deletable_ids}.
           protected_events in safety_guardrails are hard-blocked by runtime guardrails.
        6. If a delete is blocked, include '### 🛡️ Safety Guardrail Report' explaining why.
        7. You may call inspect_past_decisions or search_health_knowledge_base again if you need a refresh.
        """

        payload = {
            "phoenix_memory_traces": past_traces,
            "rag_knowledge_matches": rag_results,
            "today_telemetry": slim_triage_for_agent(triage_data),
        }
        user_prompt = (
            "Analyze the verified Phoenix memory, RAG knowledge, and today's telemetry, "
            "then act accordingly:\n\n"
            f"{json.dumps(payload, default=str)}"
        )

        tool_list: list[Any] = [
            self.introspection_api.inspect_past_decisions,
            search_health_knowledge_base,
        ]
        if is_overloaded:
            tool_list.extend([
                self.calendar_api.delete_calendar_event,
                self.calendar_api.insert_calendar_event,
            ])

        allowed_tools = {
            "inspect_past_decisions",
            "search_health_knowledge_base",
            "delete_calendar_event",
            "insert_calendar_event",
        }

        gen_config = build_generate_content_config(is_overloaded)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tool_list,
            temperature=gen_config.temperature,
            top_p=gen_config.top_p,
            max_output_tokens=gen_config.max_output_tokens,
            thinking_config=gen_config.thinking_config,
        )

        try:
            chat = self._create_chat(self.model_name, config)
            response = self._send_with_retry(chat, user_prompt)

            while response.function_calls:
                print(
                    f"🤖 [Gemini Brain] Tool call requested! "
                    f"Found {len(response.function_calls)} action(s)."
                )
                tool_responses = []

                for call in response.function_calls:
                    tool_name = call.name
                    tool_args = dict(call.args) if call.args else {}

                    if tool_name not in allowed_tools:
                        continue

                    print(
                        f"⚙️ [Agent Execution] Invoking tool: {tool_name} "
                        f"with args: {tool_args}"
                    )
                    try:
                        result = await self._execute_tool(tool_name, tool_args)
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
                "performance_profile": performance_profile(),
            }

        except Exception as error:
            if self._is_quota_exhausted(error):
                detail = (
                    "Gemini API quota exhausted. Wait ~30s and retry, "
                    "or check billing at https://ai.dev/rate-limit"
                )
            elif self._is_overloaded_api(error):
                detail = "Gemini model is temporarily overloaded (503). Please retry in a minute."
            else:
                detail = str(error)

            return {
                "error": f"❌ MCP Agent Engine failed: {detail}",
                "automated_actions_executed": executed_actions_log,
            }
