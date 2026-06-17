#!/usr/bin/env python3
"""Test the MCP tool ``appliance_get``.

Connects to the GNS3 server via MCP (SSE), calls appliance_get to retrieve
detailed information for a single appliance.
By default it auto-discovers an appliance ID via appliance_list;
use --appliance-id to specify one directly.

Usage::

    # Auto-select the first appliance
    ../../.venv/bin/python test_appliance_get.py
    # Manual ID
    ../../.venv/bin/python test_appliance_get.py --appliance-id <UUID>
    # View the tool's input schema only
    ../../.venv/bin/python test_appliance_get.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add mcp-manual-test/ to sys.path so _lib can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record,
    call_tool,
    connect,
    find_tool,
    format_result,
    list_tools,
    payload,
)

TOOL = "appliance_get"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool appliance_get")
    p.add_argument(
        "--appliance-id",
        help="UUID of the appliance to fetch (omit to auto-discover from appliance_list)",
    )
    p.add_argument(
        "--show-schema",
        action="store_true",
        help="Print the tool's input schema and exit",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Skip persisting call data + raw return to a JSON record file",
    )
    return p.parse_args()


def extract_ids(list_result) -> list[tuple[str, str]]:
    """Extract (appliance_id, name) pairs from the appliance_list MCP result.

    Uses the standard ``content[0].text → json.loads`` path (same as Claude Code).
    """
    data, _ = payload(list_result)
    items = data if isinstance(data, list) else (data or {}).get("appliances", [])
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        aid = it.get("appliance_id") or it.get("id")
        if aid:
            out.append((str(aid), it.get("name", "")))
    # Deduplicate while preserving order
    seen: set[str] = set()
    uniq = []
    for aid, name in out:
        if aid not in seen:
            seen.add(aid)
            uniq.append((aid, name))
    return uniq


async def main() -> None:
    args = parse_args()

    async with connect() as session:
        # 1) Verify the target tool exists
        tools = await list_tools(session)
        tool = find_tool(tools, TOOL)
        if not tool:
            print(f"⚠️  Server does not expose tool {TOOL}")
            return
        print(f"✓ Connected to GNS3 MCP, tool {TOOL} is available")

        if args.show_schema:
            print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
            return

        # 2) Resolve appliance_id
        appliance_id = args.appliance_id
        if not appliance_id:
            print("\nNo --appliance-id given, calling appliance_list to auto-discover ...")
            lr, _ = await call_tool(session, "appliance_list", {})
            ids = extract_ids(lr)
            if not ids:
                print("⚠️  Could not parse any appliance id from appliance_list.")
                print("Please retry with --appliance-id <UUID>")
                print(f"Raw content[0].text (first 200 chars):")
                print(repr(getattr(lr.content[0], "text", ""))[:200])
                return
            appliance_id, name = ids[0]
            print(f"  Found {len(ids)} appliances, picked first: {name or '(unnamed)'} -> {appliance_id}")

        # 3) Call appliance_get (persists call + raw return to a record file)
        print(f"\n=== Calling {TOOL}({{'appliance_id': '{appliance_id}'}}) ===")
        result, elapsed, _ = await call_and_record(
            session,
            script_file=__file__,
            tool=TOOL,
            arguments={"appliance_id": appliance_id},
            input_schema=tool.inputSchema,
            save=not args.no_save,
        )

    # 4) Display result + timing
    print(format_result(result))

    # Same data-access pattern as Claude Code: content[0].text → json.loads once
    data, src = payload(result)
    if isinstance(data, dict):
        print(f"\n✓ Parsed via {src} ({len(data)} fields from one json.loads):")
        print(f"  name        : {data.get('name')}")
        print(f"  category    : {data.get('category')}")
        qemu = data.get("qemu") or {}
        print(f"  qemu.ram    : {qemu.get('ram')}")
        print(f"  images      : {len(data.get('images', []))}")

    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
