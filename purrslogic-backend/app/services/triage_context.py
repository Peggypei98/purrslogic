"""
Shared agent context — parallel memory prefetch and slim LLM payloads.
"""

import asyncio
from typing import Any

from app.config.model_config import PHOENIX_PREFETCH_LIMIT, RAG_PREFETCH_LIMIT


def _slim_event(event: dict[str, Any]) -> dict[str, Any]:
    matrix = event.get("energy_matrix") or {}
    return {
        "event_id": event.get("event_id"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "priority": matrix.get("priority"),
        "mental_cost": matrix.get("mental_cost"),
        "physical_cost": matrix.get("physical_cost"),
    }


def slim_triage_for_agent(triage_data: dict[str, Any]) -> dict[str, Any]:
    """Strip redundant fields before sending telemetry to Gemini (fewer tokens, faster)."""
    safety = triage_data.get("safety_guardrails") or {}
    return {
        "user_id": triage_data.get("user_id"),
        "triage_summary": triage_data.get("triage_summary"),
        "proactive_interventions": triage_data.get("proactive_interventions"),
        "events": [_slim_event(event) for event in triage_data.get("events", [])],
        "safety_guardrails": {
            "policy": safety.get("policy"),
            "deletable_event_ids": safety.get("deletable_event_ids", []),
            "protected_summaries": [
                {"event_id": item.get("event_id"), "summary": item.get("summary")}
                for item in safety.get("protected_events", [])
            ],
        },
    }


def build_rag_query(triage_data: dict[str, Any]) -> str:
    interventions = triage_data.get("proactive_interventions") or []
    titles = " ".join(item.get("title", "") for item in interventions[:2])
    if triage_data.get("triage_summary", {}).get("is_overloaded_warning"):
        return f"energy recovery micro-break cat walk recipe {titles}".strip()
    return f"wellness balance recipe walk {titles}".strip()


async def prefetch_agent_context(
    introspection_api: Any,
    vector_search_api: Any,
    triage_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Fetch Phoenix traces and RAG matches concurrently.
    Returns (executed_actions_log_entries, past_traces, rag_results).
    """
    rag_query = build_rag_query(triage_data)

    past_traces, rag_results = await asyncio.gather(
        asyncio.to_thread(
            introspection_api.inspect_past_decisions,
            limit=PHOENIX_PREFETCH_LIMIT,
        ),
        vector_search_api.search_health_knowledge_base(
            query=rag_query,
            limit=RAG_PREFETCH_LIMIT,
        ),
    )

    log: list[dict[str, Any]] = [
        {
            "tool_invoked": "inspect_past_decisions",
            "arguments": {"limit": PHOENIX_PREFETCH_LIMIT, "source": "prefetch"},
            "result": past_traces,
        },
        {
            "tool_invoked": "search_health_knowledge_base",
            "arguments": {
                "query": rag_query,
                "limit": RAG_PREFETCH_LIMIT,
                "source": "prefetch",
                "via": "mongodb_mcp",
            },
            "result": rag_results,
        },
    ]
    return log, past_traces, rag_results
