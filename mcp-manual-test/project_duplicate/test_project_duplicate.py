#!/usr/bin/env python3
"""Test the MCP tool ``project_duplicate``.

Tool description
----------------
Duplicate a project (creates a copy).

Input parameters
----------------
project_id : str (UUID, required)
    UUID of the project to duplicate.

name : str (required)
    Name for the duplicated project.

reset_mac_addresses : bool (optional, default False)
    Reset MAC addresses for the duplicated project.

Returns
-------
The newly created (duplicated) project object.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls project_duplicate. Auto-discovers a
source project_id via project_list; use --project-id to specify one directly.

Usage::

    ../../.venv/bin/python test_project_duplicate.py
    ../../.venv/bin/python test_project_duplicate.py --project-id <UUID> --name "copy"
    ../../.venv/bin/python test_project_duplicate.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record, call_tool, connect, find_tool, first_id,
    format_result, list_tools, payload,
)

TOOL = "project_duplicate"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool project_duplicate")
    p.add_argument("--project-id", help="UUID of the source project (omit to auto-discover via project_list)")
    p.add_argument("--name", default=None, help="Name for the duplicated project (default: mcp-dup-<timestamp>)")
    p.add_argument("--reset-mac", action="store_true", help="Reset MAC addresses in the duplicate")
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

        project_id = args.project_id
        if not project_id:
            print("\nNo --project-id given, calling project_list to auto-discover ...")
            lr, _ = await call_tool(session, "project_list", {})
            project_id = first_id(lr)
            if not project_id:
                print("⚠️  No projects found. Try --project-id <UUID>")
                return
            print(f"  Picked source project: {project_id}")

        name = args.name or f"mcp-dup-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        call_args = {"project_id": project_id, "name": name, "reset_mac_addresses": args.reset_mac}
        print(f"\n=== Calling {TOOL}({{'project_id': '{project_id}', 'name': '{name}'}}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))
    data, _ = payload(result)
    if isinstance(data, dict):
        print(f"\n✓ Duplicated into: {data.get('name')} -> {data.get('project_id')}")
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
