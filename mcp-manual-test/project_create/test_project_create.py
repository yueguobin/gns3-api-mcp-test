#!/usr/bin/env python3
"""Test the MCP tool ``project_create``.

Tool description
----------------
Create a new GNS3 project. auto_close is set to False so the project stays
open when clients disconnect.

Input parameters
----------------
name : str (required)
    Project name.

Returns
-------
The newly created project object (project_id, name, status, path, etc.).

Test flow
---------
Connects to GNS3 via MCP (SSE), calls project_create.

Usage::

    ../../.venv/bin/python test_project_create.py
    ../../.venv/bin/python test_project_create.py --name "my project"
    ../../.venv/bin/python test_project_create.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record, connect, find_tool, format_result, list_tools, payload,
)

TOOL = "project_create"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool project_create")
    p.add_argument("--name", default="mcp-test-project", help="Project name (default: mcp-test-project)")
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

        call_args = {"name": args.name}
        print(f"\n=== Calling {TOOL}({json.dumps(call_args, ensure_ascii=False)}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))

    data, _ = payload(result)
    if isinstance(data, dict):
        print(f"\n✓ Created project: {data.get('name')} -> {data.get('project_id')}")

    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
