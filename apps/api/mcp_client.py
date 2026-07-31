"""Bounded MCP (Model Context Protocol) JSON-RPC client.

Extracted from ``apps/api/main.py`` to shrink that module without changing any
behaviour. Self-contained: the only shared state is the keyring service name, and
credentials are still read from the OS keyring by ``credential_key`` rather than
being stored in the database.

``main`` re-exports ``mcp_headers``/``mcp_http_call``/``mcp_initialize``, so
existing ``main.mcp_*`` callers keep resolving.

Behaviour worth keeping:

* ``HTTPException(502)`` on transport failure and on a JSON-RPC ``error`` member.
  The API layer maps this straight to the client - an MCP server being unreachable
  is a bad gateway, not a 500 in our own code.
* A ``data:`` prefixed body is unwrapped before JSON parsing. Streamable-HTTP MCP
  servers answer a plain POST with a single SSE frame, so this is not dead code.
* ``Mcp-Session-Id`` is threaded through ``initialize`` -> ``tools/list``. Dropping
  it makes servers that scope tools per session return an empty tool list.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request

import keyring
from fastapi import HTTPException

#: OS keyring service name.
#:
#: Read from ``main`` at call time rather than redeclared here on purpose. ``main``
#: is what *writes* MCP credentials (``keyring.set_password(KEYRING_SERVICE, ...)``
#: in ``save_mcp_connection``), so a second literal in this module would be a silent
#: auth failure the moment either copy is edited: the write and the read would target
#: different keyring services and every token lookup would just return ``None``.
#: The import is inside the function because ``main`` imports this module.
def _keyring_service() -> str:
    from apps.api.main import KEYRING_SERVICE  # lazy: main imports this module

    return KEYRING_SERVICE


#: MCP protocol revision this client negotiates.
MCP_PROTOCOL_VERSION = "2025-03-26"

MCP_CLIENT_INFO = {"name": "AI Automation Office", "version": "1.0"}


def mcp_headers(connection: sqlite3.Row | dict, session_id: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    credential_key = connection["credential_key"]
    token = keyring.get_password(_keyring_service(), credential_key) if credential_key else None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def mcp_http_call(
    connection: sqlite3.Row | dict, method: str, params: dict, session_id: str | None = None
) -> tuple[dict, str | None]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = urllib.request.Request(
        connection["server_url"], data=body, headers=mcp_headers(connection, session_id), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            if raw.startswith("data:"):
                raw = raw.split("data:", 1)[1].strip()
            data = json.loads(raw)
            if "error" in data:
                raise HTTPException(502, f"MCP {method} failed: {data['error']}")
            return data.get("result", {}), response.headers.get("Mcp-Session-Id") or session_id
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise HTTPException(502, f"MCP {method} connection failed: {error}") from error


def mcp_initialize(connection: sqlite3.Row | dict) -> tuple[list[dict], str | None]:
    result, session_id = mcp_http_call(
        connection,
        "initialize",
        {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": MCP_CLIENT_INFO},
    )
    tools_result, session_id = mcp_http_call(connection, "tools/list", {}, session_id)
    return tools_result.get("tools", []), session_id


__all__ = [
    "MCP_CLIENT_INFO",
    "MCP_PROTOCOL_VERSION",
    "mcp_headers",
    "mcp_http_call",
    "mcp_initialize",
]
