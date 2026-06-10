import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent
from google.adk.tools.mcp_tool import McpToolset
from mcp import StdioServerParameters

from app.config.model_config import TRIAGE_MODEL, build_generate_content_config
from purrslogic_agent.tools import (
    delete_calendar_event,
    insert_calendar_event,
    inspect_past_decisions,
    search_health_knowledge_base,
)

# Load backend .env (MONGODB_URL, GOOGLE_API_KEY) and agent-local .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

_mongo_url = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or ""

mongodb_mcp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command="npx",
        args=["-y", "mongodb-mcp-server@latest", "--readOnly"],
        env={
            **os.environ,
            "MDB_MCP_CONNECTION_STRING": _mongo_url,
            "MDB_MCP_READ_ONLY": "true",
        },
    ),
    tool_filter=["aggregate", "find"],
)

root_agent = Agent(
    model=TRIAGE_MODEL,
    name="purrslogic_brain",
    description="Proactive wellness agent for calendar triage and energy recovery.",
    generate_content_config=build_generate_content_config(is_overloaded=False),
    instruction="""
You are Purrslogic — a proactive wellness AI agent built on Google ADK.

MEMORY:
- Short-term: call inspect_past_decisions for Phoenix traces.
- Long-term: call search_health_knowledge_base OR MongoDB MCP aggregate on purrslogic.knowledge_base.

PROTOCOL:
1. Include '### 🧠 Agent Self-Introspection Report' citing Phoenix trace_id values.
2. Include '### 📚 Long-Term RAG Knowledge Retrieval' citing knowledge base titles.
3. When is_overloaded_warning is true, use insert_calendar_event / delete_calendar_event.
4. SAFETY GUARDRAIL: NEVER delete IMMOVABLE events (interviews, critical meetings).
   Only delete event_ids listed in safety_guardrails.deletable_event_ids.
   Runtime will block unsafe deletes — report blocks in '### 🛡️ Safety Guardrail Report'.
5. When energy is balanced, do NOT modify the calendar.
""",
    tools=[
        mongodb_mcp_toolset,
        inspect_past_decisions,
        search_health_knowledge_base,
        delete_calendar_event,
        insert_calendar_event,
    ],
)
