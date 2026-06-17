#!/usr/bin/env python3
"""Test the MCP tool ``project_delete``.

Tool description
----------------
Delete a GNS3 project permanently. Cannot be undone.

Input parameters
----------------
project_id : str (UUID, required)
    UUID of the project to delete.

Returns
-------
Deletion confirmation.

**Safety:** By default this script creates a throwaway project and deletes
THAT (so the test is non-destructive). Pass ``--project-id`` to delete a
specific project — double-check the UUID, deletion is permanent.

Test flow
---------
Connects to GNS3 via MCP (SSE). Without ``--project-id`` it creates a temp
project then deletes it; with ``--project-id`` it deletes that project.

Usage::

    # Safe: create a throwaway project and delete it
    ../../.venv/bin/python test_project_delete.py
    # Delete a specific project (PERMANENT — verify the UUID)
    ../../.venv/bin/python test_project_delete.py --project-id <UUID>
    ../../.venv/bin/python test_project_delete.py --show-schema
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
    call_and_record, call_tool, connect, find_tool,
    format_result, list_tools, payload,
)

TOOL = "project_delete"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool project_delete")
    p.add_argument("--project-id", help="UUID of the project to delete (PERMANENT). Omit to auto-create+delete a throwaway.")
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
            # safe mode: create a throwaway project, then delete it
            tmp_name = f"mcp-delete-target-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            print(f"\nSafe mode: creating throwaway project '{tmp_name}' ...")
            cr, _ = await call_tool(session, "project_create", {"name": tmp_name})
            cdata, _ = payload(cr)
            project_id = (cdata or {}).get("project_id") if isinstance(cdata, dict) else None
            if not project_id:
                print("⚠️  Could not create a throwaway project to delete; aborting.")
                print(format_result(cr))
                return
            print(f"  Created throwaway project: {project_id}")

        call_args = {"project_id": project_id}
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
