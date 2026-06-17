"""Common client for GNS3 MCP manual testing.

Pipeline: load .env -> SSE connect -> call tool -> pretty-print.
All mcp-manual-test/<tool>/test_*.py scripts share this module to avoid boilerplate.

Usage (inside a tool's test script)::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _lib.gns3_mcp import connect, call_tool, format_result, list_tools

    async def main():
        async with connect() as session:
            result, elapsed = await call_tool(session, "appliance_get", {"appliance_id": "..."})
        print(format_result(result))
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client


def _load_env() -> None:
    """Walk up from this file's location to find the project root .env.

    Existing environment variables take precedence over .env values.
    """
    here = Path(__file__).resolve()
    for d in [here.parent, *here.parents]:
        env_file = d / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
            return


def config() -> tuple[str, str]:
    """Return (GNS3_MCP_URL, GNS3_MCP_TOKEN). Exits with error if missing."""
    _load_env()
    url = os.environ.get("GNS3_MCP_URL")
    token = os.environ.get("GNS3_MCP_TOKEN")
    if not url or not token:
        raise SystemExit(
            "GNS3_MCP_URL / GNS3_MCP_TOKEN not set. Configure them in the project root .env "
            "(see .env.example)"
        )
    return url, token


def headers() -> dict[str, str]:
    """Build MCP request headers with Bearer token authentication."""
    _, token = config()
    return {"Authorization": f"Bearer {token}"}


@asynccontextmanager
async def connect():
    """Connect to GNS3 MCP via SSE transport, yield an initialized ClientSession.

    Usage::

        async with connect() as session:
            ...  # call multiple tools within the same session
    """
    url, _ = config()
    async with sse_client(url, headers=headers()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def list_tools(session: ClientSession):
    """Return all tools exposed by the server."""
    return (await session.list_tools()).tools


def find_tool(tools, name: str):
    """Look up a tool by name; return the tool object or None."""
    return next((t for t in tools if t.name == name), None)


async def call_tool(session: ClientSession, name: str, arguments: dict | None = None):
    """Call a tool and return (CallToolResult, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = await session.call_tool(name, arguments or {})
    return result, time.perf_counter() - t0


def _unwrap_envelope(obj):
    """Recursively unwrap ``{"type":"text","text": <str|obj>}`` nested wrappers.

    Some GNS3 MCP tools wrap their result in an extra text content envelope,
    e.g. appliance_list text is '{"type":"text","text":"{...}"}'.
    Returns the innermost object; returns a plain string if the innermost
    layer is a non-JSON string.
    """
    for _ in range(8):
        if isinstance(obj, dict) and set(obj.keys()) <= {"type", "text"} and "text" in obj:
            inner = obj["text"]
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    return inner
            obj = inner
            continue
        break
    return obj


def _pretty_json_text(text: str) -> str:
    """Pretty-print JSON text (handles nested envelopes); return as-is if not JSON."""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text
    obj = _unwrap_envelope(obj)
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        return text


def format_result(result) -> str:
    """Render CallToolResult's ``content`` blocks as a human-readable string (wire layer only)."""
    lines: list[str] = []
    lines.append(f"isError: {bool(getattr(result, 'isError', False))}")

    content = getattr(result, "content", []) or []
    for i, block in enumerate(content):
        btype = getattr(block, "type", "?")
        if btype == "text":
            lines.append(f"[content {i}] text:\n{_pretty_json_text(block.text)}")
        else:
            lines.append(f"[content {i}] {btype}: {block}")
    return "\n".join(lines)


def raw_result(result) -> dict:
    """Extract the raw wire-level MCP return data, stripping SDK-private fields.

    Also unwraps the superfluous ``{"type":"text","text":"<real_data>"}`` layer
    that the GNS3 server nests inside ``content[].text``, converting each
    JSON-string layer into a parsed object for readability.
    """
    raw = json.loads(result.model_dump_json())
    raw.pop("structuredContent", None)
    raw.pop("structured_content", None)
    for block in raw.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            try:
                parsed = json.loads(block["text"])
                # The inner text is also a JSON string — parse it too
                if isinstance(parsed, dict) and "text" in parsed and isinstance(parsed["text"], str):
                    try:
                        parsed["text"] = json.loads(parsed["text"])
                    except (ValueError, TypeError):
                        pass
                block["text"] = parsed
            except (ValueError, TypeError):
                pass
    return raw


def payload(result):
    """Extract real data from ``content[0].text``, return ``(data, source)``.

    Only uses the standard MCP ``content`` array (behaves like Claude Code),
    ignoring the SDK-private ``structuredContent`` field.
    Auto-unwraps backend double envelopes.
    """
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", "") == "text":
            try:
                obj = _unwrap_envelope(json.loads(block.text))
            except ValueError:
                continue
            if isinstance(obj, (dict, list)):
                return obj, "content[].text"
    return None, None


def save_record(
    script_file: str | Path,
    *,
    tool: str,
    arguments: dict | None,
    result,
    elapsed: float,
    input_schema: dict | None = None,
) -> Path:
    """Write a JSON record of this tool invocation next to the script file.

    Record contains:
      - Call metadata: tool name, arguments, schema, timestamp, elapsed
      - MCP raw return: unwrapped wire-level data (``raw_result``)
    Filename: ``<tool>__YYYYmmdd_HHMMSS.json`` — one file per run (history kept).
    """
    out_dir = Path(script_file).resolve().parent
    now = datetime.datetime.now()
    path = out_dir / f"{tool}__{now.strftime('%Y%m%d_%H%M%S')}.json"
    record = {
        "tool": tool,
        "called_at": now.isoformat(timespec="seconds"),
        "elapsed_ms": round(elapsed * 1000, 1),
        "call": {
            "arguments": arguments or {},
            "input_schema": input_schema,
        },
        "result": {
            "is_error": bool(getattr(result, "isError", False)),
            "raw": raw_result(result),
        },
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def call_and_record(
    session: ClientSession,
    *,
    script_file: str | Path,
    tool: str,
    arguments: dict | None = None,
    input_schema: dict | None = None,
    save: bool = True,
):
    """Call a tool and (by default) persist call + raw return to a JSON record.

    Returns ``(result, elapsed, saved_path_or_None)``.
    """
    result, elapsed = await call_tool(session, tool, arguments)
    saved = None
    if save:
        saved = save_record(
            script_file, tool=tool, arguments=arguments, result=result,
            elapsed=elapsed, input_schema=input_schema,
        )
        print(f"💾 Record saved: {saved}")
    return result, elapsed, saved


def run(coro):
    """Convenience entry-point to run an async coroutine."""
    return asyncio.run(coro)
