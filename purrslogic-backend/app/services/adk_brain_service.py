import asyncio
import json
from typing import Any

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.config.model_config import TRIAGE_MODEL, build_generate_content_config, performance_profile
from app.services.introspection_service import AgentIntrospectionService
from app.services.triage_context import prefetch_agent_context, slim_triage_for_agent
from app.services.vector_service import MongoDBVectorSearchService
from purrslogic_agent.agent import mongodb_mcp_toolset, root_agent

load_dotenv()

APP_NAME = "purrslogic"
_OVERLOAD_MARKERS = ("503", "UNAVAILABLE", "HIGH DEMAND", "OVERLOADED")
_MAX_RETRIES = 3


def _is_overloaded_api(error: Exception | str) -> bool:
    message = str(error).upper()
    return any(marker in message for marker in _OVERLOAD_MARKERS)


class AdkBrainService:
    """Google ADK (Agent Builder) orchestration for Purrslogic triage."""

    def __init__(self):
        self.introspection_api = AgentIntrospectionService()
        self.vector_search_api = MongoDBVectorSearchService()
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            app_name=APP_NAME,
            agent=root_agent,
            session_service=self._session_service,
        )

    def _extract_text(self, event) -> str:
        if not event.content or not event.content.parts:
            return ""
        return "".join(part.text for part in event.content.parts if part.text)

    async def generate_triage_coaching(self, triage_data: dict) -> dict[str, Any]:
        last_error: dict[str, Any] | None = None
        for attempt in range(_MAX_RETRIES):
            result = await self._generate_triage_coaching_once(triage_data)
            if "error" not in result:
                return result
            last_error = result
            if _is_overloaded_api(result["error"]) and attempt < _MAX_RETRIES - 1:
                wait_seconds = 2 ** attempt
                print(
                    f"⚠️ [ADK Brain] Model busy, retrying in {wait_seconds}s "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES})..."
                )
                await asyncio.sleep(wait_seconds)
                continue
            return result
        return last_error or {"error": "ADK triage failed after retries.", "orchestrator": "google-adk"}

    async def _generate_triage_coaching_once(self, triage_data: dict) -> dict[str, Any]:
        executed_actions_log: list[dict[str, Any]] = []
        user_id = triage_data.get("user_id", "peggy_pei_28")

        print("⚙️ [ADK Brain] Parallel prefetch: Phoenix + MongoDB RAG...")
        prefetch_log, past_traces, rag_results = await prefetch_agent_context(
            self.introspection_api,
            self.vector_search_api,
            triage_data,
        )
        executed_actions_log.extend(prefetch_log)

        from app.services.guardrail_service import guardrail_service

        guardrail_service.register_agenda(triage_data.get("events", []))

        is_overloaded = triage_data.get("triage_summary", {}).get("is_overloaded_warning", False)
        root_agent.generate_content_config = build_generate_content_config(is_overloaded)

        payload = {
            "phoenix_memory_traces": past_traces,
            "rag_knowledge_matches": rag_results,
            "today_telemetry": slim_triage_for_agent(triage_data),
            "safety_guardrails": triage_data.get("safety_guardrails", {}),
        }
        user_prompt = (
            "Analyze the verified Phoenix memory, RAG knowledge, and today's telemetry. "
            "Use Google ADK tools (including MongoDB MCP) as needed:\n\n"
            f"{json.dumps(payload, default=str)}"
        )

        session = await self._session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
        )

        final_text = ""
        try:
            print("🧠 [ADK Brain] Running root_agent via Google ADK Runner...")
            content = types.Content(role="user", parts=[types.Part(text=user_prompt)])

            async for event in self._runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=content,
            ):
                for call in event.get_function_calls() or []:
                    tool_name = call.name
                    tool_args = dict(call.args) if call.args else {}
                    print(f"🤖 [ADK Brain] Tool call: {tool_name} {tool_args}")
                    executed_actions_log.append({
                        "tool_invoked": tool_name,
                        "arguments": tool_args,
                        "result": {"status": "invoked_via_adk"},
                    })

                for response in event.get_function_responses() or []:
                    executed_actions_log.append({
                        "tool_invoked": response.name or "mcp_tool",
                        "arguments": {"source": "adk_response"},
                        "result": response.response,
                    })

                if event.is_final_response():
                    text = self._extract_text(event)
                    if text:
                        final_text = text

            return {
                "agent_coaching_text": final_text or "ADK agent completed triage loop.",
                "automated_actions_executed": executed_actions_log,
                "model_used": TRIAGE_MODEL,
                "orchestrator": "google-adk",
                "performance_profile": performance_profile(),
            }
        except Exception as error:
            return {
                "error": f"❌ ADK Agent Engine failed: {error}",
                "automated_actions_executed": executed_actions_log,
                "orchestrator": "google-adk",
            }

    async def shutdown(self) -> None:
        try:
            await mongodb_mcp_toolset.close()
        except Exception as error:
            print(f"⚠️ [ADK Brain] MCP toolset shutdown: {error}")
