"""Purrslogic tools exposed to the ADK root agent (lazy service init)."""


def inspect_past_decisions(limit: int = 5) -> list:
    """Query Arize Phoenix for recent agent traces (short-term memory)."""
    from app.services.introspection_service import AgentIntrospectionService

    return AgentIntrospectionService().inspect_past_decisions(limit=limit)


async def search_health_knowledge_base(query: str, limit: int = 2) -> list:
    """
    Search Peggy's wellness knowledge base via MongoDB MCP + Atlas Vector Search.
    Use keywords like 'cat', 'walk', 'recipe', or 'recovery'.
    """
    from app.services.vector_service import MongoDBVectorSearchService

    return await MongoDBVectorSearchService().search_health_knowledge_base(
        query=query,
        limit=limit,
    )


def delete_calendar_event(event_id: str) -> dict:
    """
    Delete a calendar event by event_id.
    Day 19 guardrail: IMMOVABLE events (interviews, critical meetings) are blocked at runtime.
    """
    from app.services.guardrail_service import guardrail_service

    return guardrail_service.guarded_delete_calendar_event(event_id=event_id)


def insert_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
) -> dict:
    """Insert a micro-recovery block into Google Calendar."""
    from app.services.calendar_service import GoogleCalendarService

    return GoogleCalendarService().insert_calendar_event(
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
    )
