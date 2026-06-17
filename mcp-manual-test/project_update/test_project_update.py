#!/usr/bin/env python3
"""Test the MCP tool ``project_update``.

Tool description
----------------
Update a project's properties (name, auto_close, auto_open, auto_start,
scene_width, scene_height, zoom, show_layers, snap_to_grid, show_grid,
grid_size, drawing_grid_size, show_interface_labels).

Input parameters
----------------
project_id : str (UUID, required)
    UUID of the project to update.

Plus any of the optional properties above (passed via ``--set key=value``).

Returns
-------
The updated project object.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls project_update. Auto-discovers a
project_id via project_list; use --project-id to specify one directly.
Without ``--set``, it toggles ``show_grid`` as a benign demo change.

Usage::

    ../../.venv/bin/python test_project_update.py
    ../../.venv/bin/python test_project_update.py --set scene_width=2000 --set show_grid=true
    ../../.venv/bin/python test_project_update.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record, call_tool, connect, find_tool, first_id,
    format_result, list_tools,
)

TOOL = "project_update"


def parse_value(raw: str):
    """Parse a --set value: JSON (int/bool/str) if valid, else raw string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool project_update")
    p.add_argument("--project-id", help="UUID of the project (omit to auto-discover via project_list)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="Property to set (repeatable). Value parsed as JSON if possible.")
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
            print(f"  Picked project: {project_id}")

        props = {}
        for kv in args.set:
            if "=" not in kv:
                print(f"⚠️  ignoring bad --set '{kv}' (expected KEY=VALUE)")
                continue
            k, v = kv.split("=", 1)
            props[k.strip()] = parse_value(v)
        if not props:
            # benign demo change when nothing specified
            props = {"show_grid": True}

        call_args = {"project_id": project_id, **props}
        print(f"\n=== Calling {TOOL}({json.dumps(call_args, ensure_ascii=False)}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
