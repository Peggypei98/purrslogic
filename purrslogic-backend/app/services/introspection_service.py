import os
from typing import Dict, List

import phoenix as px
from phoenix.client import Client


class AgentIntrospectionService:
    """Day 16 MCP tool: exposes Phoenix trace memory to Gemini for self-introspection."""

    def _get_phoenix_client(self) -> Client:
        session = px.active_session()
        base_url = session.url if session else os.getenv(
            "PHOENIX_COLLECTOR_URL", "http://127.0.0.1:6006"
        )
        return Client(base_url=base_url)

    def inspect_past_decisions(self, limit: int = 3) -> List[Dict]:
        """
        [Day 16 MCP Tool] Allows Gemini to query the Arize Phoenix trace store
        and reflect on its own historical execution traces, token usage, and
        past tool actions.
        """
        try:
            print("🖥️ [Phoenix Radar] Reading memory dataframe spans for introspection...")
            spans_df = self._get_phoenix_client().spans.get_spans_dataframe(limit=max(limit, 20))

            if spans_df.empty:
                print("🟢 [Phoenix Radar] Phoenix database is clean. No past decisions recorded yet.")
                return [{
                    "status": "success",
                    "message": "Phoenix database is clean. No past decisions recorded yet.",
                }]

            print(f"🖥️ [Phoenix Radar] Loaded {len(spans_df)} spans, returning top {limit} for agent review.")
            spans_df = spans_df.sort_values("start_time", ascending=False)

            # Prefer LLM / tool spans when the column is present
            if "span_kind" in spans_df.columns:
                priority_kinds = ["LLM", "TOOL", "CHAIN", "AGENT"]
                prioritized = spans_df[spans_df["span_kind"].isin(priority_kinds)]
                if not prioritized.empty:
                    spans_df = prioritized

            recent_logs = []
            for _, row in spans_df.head(limit).iterrows():
                input_value = row.get("attributes.input.value", "")
                output_value = row.get("attributes.output.value", "")

                short_input = (
                    str(input_value)[:200] + "..."
                    if len(str(input_value)) > 200
                    else str(input_value)
                )
                short_output = (
                    str(output_value)[:300] + "..."
                    if len(str(output_value)) > 300
                    else str(output_value)
                )

                recent_logs.append({
                    "trace_id": str(row.get("context.span_id", "")),
                    "action_name": row.get("name", "unnamed"),
                    "layer_type": str(row.get("span_kind", "UNKNOWN")),
                    "what_agent_saw_input": short_input,
                    "what_agent_decided_output": short_output,
                })

            return recent_logs

        except Exception as e:
            return [{"status": "error", "message": f"Failed to query Phoenix via MCP Tool: {str(e)}"}]
