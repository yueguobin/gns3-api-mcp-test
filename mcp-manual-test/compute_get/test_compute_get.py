#!/usr/bin/env python3
"""Test the MCP tool ``compute_get``.

Tool description
----------------
Get detailed information about a registered remote compute node.

**Note:** Only works for computes registered in the database (returned by
``compute_list``). For the built-in local compute info, use
``server_statistics`` instead.

Input parameters
----------------
compute_id : str (UUID, required)
    UUID of the registered compute node.

Returns
-------
Compute node configuration object.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls compute_get for a specific compute
node. By default it auto-discovers a compute_id via compute_list;
use --compute-id to specify one directly.

Usage::

    # Auto-select the first registered compute
    ../../.venv/bin/python test_compute_get.py
    # Manual ID
    ../../.venv/bin/python test_compute_get.py --compute-id <UUID>
    ../../.venv/bin/python test_compute_get.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

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

TOOL = "compute_get"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool compute_get")
    p.add_argument("--compute-id", help="UUID of the registered compute node (omit to auto-discover via compute_list)")
    p.add_argument("--show-schema", action="store_true", help="Print the tool's input schema and exit")
    p.add_argument("--no-save", action="store_true", help="Skip persisting call data + raw return to a JSON record file")
    return p.parse_args()


def extract_ids(list_result) -> list[tuple[str, str]]:
    """Extract (compute_id, name) from compute_list result."""
    data, _ = payload(list_result)
    items = data if isinstance(data, list) else (data or {}).get("computes", [])
    if not isinstance(items, list):
        return []
    return [(str(it.get("compute_id") or it.get("id")), it.get("name", ""))
            for it in items if it.get("compute_id") or it.get("id")]


async def main() -> None:
    args = parse_args()

    async with connect() as session:
        tools = await list_tools(session)
        tool = find_tool(tools, TOOL)
        if not tool:
            print(f"⚠️  Server does not expose tool {TOOL}")
            return
        print(f"✓ Connected to GNS3 MCP, tool {TOOL} is available")

        if args.show_schema:
            print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
            return

        compute_id = args.compute_id
        if not compute_id:
            print("\nNo --compute-id given, calling compute_list to auto-discover ...")
            lr, _ = await call_tool(session, "compute_list", {})
            ids = extract_ids(lr)
            if not ids:
                print("⚠️  No registered computes found. Try --compute-id <UUID> or use server_statistics for local compute.")
                return
            compute_id, name = ids[0]
            print(f"  Found {len(ids)} compute nodes, picked first: {name or '(unnamed)'} -> {compute_id}")

        print(f"\n=== Calling {TOOL}({{'compute_id': '{compute_id}'}}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL,
            arguments={"compute_id": compute_id},
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
