#!/usr/bin/env python3
"""Test the MCP tool ``project_load``.

Tool description
----------------
Load a project from a file path on the server's filesystem.

Input parameters
----------------
path : str (required)
    Filesystem path to the ``.gns3`` project file on the GNS3 server.

Returns
-------
The loaded project object.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls project_load with the given path.
The path must be readable by the GNS3 server process.

Usage::

    ../../.venv/bin/python test_project_load.py --path /path/to/project.gns3
    ../../.venv/bin/python test_project_load.py --show-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _lib.gns3_mcp import (  # noqa: E402
    call_and_record, connect, find_tool, format_result, list_tools,
)

TOOL = "project_load"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool project_load")
    p.add_argument("--path", required=True, help="Filesystem path to the .gns3 project file (on the GNS3 server)")
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

        call_args = {"path": args.path}
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
