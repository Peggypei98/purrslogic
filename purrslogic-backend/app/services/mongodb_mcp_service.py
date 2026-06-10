"""
Official MongoDB MCP Server client (Model Context Protocol).

Spawns `mongodb-mcp-server` over stdio and exposes Atlas read tools (`aggregate`, `find`)
for the Purrslogic agent and RAG pipeline.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import AsyncExitStack
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

MCP_DATABASE = "purrslogic"
_UNTRUSTED_DATA_PATTERN = re.compile(
    r"<untrusted-user-data-[^>]+>\s*(.*?)\s*</untrusted-user-data-[^>]+>",
    re.DOTALL,
)


def _connection_string() -> str:
    url = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or ""
    if not url:
        raise RuntimeError("MONGODB_URL (or MONGODB_URI) is required for MongoDB MCP.")
    return url


def parse_mcp_documents(result: Any) -> list[dict[str, Any]]:
    """Extract JSON document payloads from MongoDB MCP tool responses."""
    documents: list[dict[str, Any]] = []

    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", "") or str(content)
        if not text.strip():
            continue

        payload_candidates: list[str] = []
        for matched in _UNTRUSTED_DATA_PATTERN.finditer(text):
            payload_candidates.append(matched.group(1).strip())

        if not payload_candidates and (text.strip().startswith("[") or text.strip().startswith("{")):
            payload_candidates.append(text.strip())

        for payload_text in payload_candidates:
            if not payload_text.startswith("[") and not payload_text.startswith("{"):
                continue
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        documents.append(item)
            elif isinstance(payload, dict):
                documents.append(payload)

    return documents


class MongoDBMCPService:
    """Persistent stdio client for the official MongoDB MCP Server."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if self._connected:
            return

        print("🍃 [MongoDB MCP] Starting mongodb-mcp-server (readOnly)...")
        params = StdioServerParameters(
            command="npx",
            args=["-y", "mongodb-mcp-server@latest", "--readOnly"],
            env={
                **os.environ,
                "MDB_MCP_CONNECTION_STRING": _connection_string(),
                "MDB_MCP_READ_ONLY": "true",
            },
        )

        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        self._connected = True

        tool_names = [tool.name for tool in (await self._session.list_tools()).tools]
        print(
            f"🍃 [MongoDB MCP] Connected. Tools available: "
            f"{', '.join(name for name in tool_names if name in ('aggregate', 'find', 'count'))}"
        )

    async def disconnect(self) -> None:
        if not self._stack:
            return
        try:
            await self._stack.aclose()
        except Exception as error:
            print(f"⚠️ [MongoDB MCP] Shutdown note: {error}")
        finally:
            self._stack = None
            self._session = None
            self._connected = False

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._connected or not self._session:
            await self.connect()

        assert self._session is not None
        print(f"🍃 [MongoDB MCP] call_tool → {tool_name}({list(arguments.keys())})")
        result = await self._session.call_tool(tool_name, arguments=arguments)

        if getattr(result, "isError", False):
            error_text = " ".join(
                getattr(item, "text", str(item)) for item in getattr(result, "content", [])
            )
            raise RuntimeError(f"MongoDB MCP tool '{tool_name}' failed: {error_text}")

        return parse_mcp_documents(result)

    async def aggregate(
        self,
        collection: str,
        pipeline: list[dict[str, Any]],
        database: str = MCP_DATABASE,
    ) -> list[dict[str, Any]]:
        return await self.call_tool(
            "aggregate",
            {
                "database": database,
                "collection": collection,
                "pipeline": pipeline,
            },
        )

    async def find(
        self,
        collection: str,
        filter_query: dict[str, Any],
        limit: int = 10,
        database: str = MCP_DATABASE,
        projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "database": database,
            "collection": collection,
            "filter": filter_query,
            "limit": limit,
        }
        if projection is not None:
            payload["projection"] = projection
        return await self.call_tool("find", payload)


# Shared singleton used by FastAPI lifespan and services.
mongodb_mcp = MongoDBMCPService()
