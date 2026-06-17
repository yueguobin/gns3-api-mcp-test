#!/usr/bin/env python3
"""Test the MCP tool ``compute_list``.

Tool description
----------------
List all remotely registered compute nodes (returns only database entries,
does NOT include the built-in local compute). For the local compute info,
use ``server_statistics`` instead.

Input parameters
----------------
*(none)*

Returns
-------
List of registered compute node objects.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls compute_list to retrieve all
registered remote compute nodes.

Usage::

    ../../.venv/bin/python test_compute_list.py
    ../../.venv/bin/python test_compute_list.py --show-schema
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
    connect,
    find_tool,
    format_result,
    list_tools,
    payload,
)

TOOL = "compute_list"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool compute_list")
    p.add_argument("--show-schema", action="store_true", help="Print the tool's input schema and exit")
    p.add_argument("--no-save", action="store_true", help="Skip persisting call data + raw return to a JSON record file")
    return p.parse_args()


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

        print(f"\n=== Calling {TOOL}() ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments={},
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))

    data, _ = payload(result)
    items = data if isinstance(data, list) else []
    print(f"\n📊  Registered compute nodes: {len(items)}")

    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
