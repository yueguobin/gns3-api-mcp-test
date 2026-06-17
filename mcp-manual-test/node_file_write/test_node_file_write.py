#!/usr/bin/env python3
"""Test the MCP tool ``node_file_write``.

Tool description
----------------
Write content to a file in a node directory. Creates the file if it doesn't
exist; overwrites existing content.

Input parameters
----------------
project_id : str (UUID, required)
node_id : str (UUID, required)
file_path : str (required)
    Path within the node directory.
content : str (required)
    Content to write.

Returns
-------
Write confirmation.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls node_file_write. Auto-discovers
project_id and node_id. Default writes a small marker file ``mcp_test.txt``.

Usage::

    ../../.venv/bin/python test_node_file_write.py
    ../../.venv/bin/python test_node_file_write.py --file-path custom.txt --content "hi"
    ../../.venv/bin/python test_node_file_write.py --show-schema
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
    call_and_record, call_tool, connect, find_tool, first_id, first_node,
    format_result, list_tools,
)

TOOL = "node_file_write"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool node_file_write")
    p.add_argument("--project-id", help="UUID of the project (omit to auto-discover)")
    p.add_argument("--node-id", help="UUID of the node (omit to auto-discover)")
    p.add_argument("--file-path", default="mcp_test.txt", help="Path within the node directory")
    p.add_argument("--content", default=None, help="Content to write (default: timestamped marker)")
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
        node_id = args.node_id
        if not project_id or not node_id:
            if not project_id:
                pl, _ = await call_tool(session, "project_list", {})
                project_id = first_id(pl)
                if not project_id:
                    print("⚠️  No projects found.")
                    return
                print(f"  Picked project: {project_id}")
            if not node_id:
                nl, _ = await call_tool(session, "node_list", {"project_id": project_id})
                node = first_node(nl)
                node_id = (node or {}).get("node_id")
                if not node_id:
                    print("⚠️  No nodes in project.")
                    return
                print(f"  Picked node: {node_id}")

        content = args.content or f"mcp test marker @ {datetime.datetime.now().isoformat(timespec='seconds')}\n"
        call_args = {"project_id": project_id, "node_id": node_id,
                     "file_path": args.file_path, "content": content}
        print(f"\n=== Calling {TOOL}({{'project_id':..., 'file_path': '{args.file_path}', 'content': <{len(content)} chars>}}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL, arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
