#!/usr/bin/env python3
"""Test the MCP tool ``node_create``.

Tool description
----------------
Create one or more nodes from templates.

Input parameters
----------------
project_id : str (UUID, required)
    UUID of the project.
template_id : str (UUID, optional)
    Template UUID (single mode). Auto-discovered from the first existing node
    if omitted.
x, y : int (optional)
    Canvas coordinates.
nodes : list (optional)
    Batch mode: [{name, template_id?, x?, y?, compute_id?}].

Returns
-------
Created node object(s).

Test flow
---------
Connects to GNS3 via MCP (SSE), calls node_create. Auto-discovers project_id
via project_list and template_id by reading the first existing node's
template_id.

Usage::

    ../../.venv/bin/python test_node_create.py
    ../../.venv/bin/python test_node_create.py --template-id <UUID>
    ../../.venv/bin/python test_node_create.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record, call_tool, connect, find_tool, first_id, first_node,
    format_result, list_tools, payload,
)

TOOL = "node_create"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool node_create")
    p.add_argument("--project-id", help="UUID of the project (omit to auto-discover)")
    p.add_argument("--template-id", help="Template UUID (omit to derive from first existing node)")
    p.add_argument("--name", default="mcp-test-node", help="Name for the created node")
    p.add_argument("--x", type=int, default=0, help="Canvas X coordinate")
    p.add_argument("--y", type=int, default=0, help="Canvas Y coordinate")
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
            pl, _ = await call_tool(session, "project_list", {})
            project_id = first_id(pl)
            if not project_id:
                print("⚠️  No projects found. Try --project-id <UUID>")
                return
            print(f"  Picked project: {project_id}")

        template_id = args.template_id
        if not template_id:
            print("No --template-id given, deriving from first existing node ...")
            nl, _ = await call_tool(session, "node_list", {"project_id": project_id})
            node = first_node(nl)
            template_id = (node or {}).get("template_id")
            if not template_id:
                print("⚠️  Could not derive a template_id. Pass --template-id <UUID>")
                return
            print(f"  Derived template_id: {template_id} (from node {(node or {}).get('name','')})")

        call_args = {
            "project_id": project_id, "template_id": template_id,
            "x": args.x, "y": args.y, "name": args.name,
        }
        print(f"\n=== Calling {TOOL}({json.dumps(call_args, ensure_ascii=False)}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))
    data, _ = payload(result)
    if isinstance(data, dict):
        print(f"\n✓ Created node: {data.get('name')} -> {data.get('node_id')}")
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
