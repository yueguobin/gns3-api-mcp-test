#!/usr/bin/env python3
"""Test the MCP tool ``compute_images``.

Tool description
----------------
List available images for an emulator on a registered compute node.

Input parameters
----------------
compute_id : str (UUID, required)
    UUID of the registered compute node.

emulator : str (required)
    Emulator type (e.g. ``"qemu"``, ``"iou"``, ``"docker"``).

Returns
-------
List of images available for the given emulator on that compute node.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls compute_images for a specific
compute + emulator. Auto-discovers compute_id via compute_list;
--emulator must be specified.

Usage::

    ../../.venv/bin/python test_compute_images.py --emulator qemu
    ../../.venv/bin/python test_compute_images.py --compute-id <UUID> --emulator iou
    ../../.venv/bin/python test_compute_images.py --show-schema
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

TOOL = "compute_images"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool compute_images")
    p.add_argument("--compute-id", help="UUID of the compute node (omit to auto-discover via compute_list)")
    p.add_argument("--emulator", required=True, help="Emulator type: qemu, iou, docker, etc.")
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
                print("⚠️  No registered computes found. Try --compute-id <UUID>")
                return
            compute_id, name = ids[0]
            print(f"  Found {len(ids)} compute nodes, picked first: {name or '(unnamed)'} -> {compute_id}")

        call_args = {"compute_id": compute_id, "emulator": args.emulator}
        print(f"\n=== Calling {TOOL}({json.dumps(call_args, ensure_ascii=False)}) ===")
        result, elapsed, _ = await call_and_record(
            session, script_file=__file__, tool=TOOL,
            arguments=call_args,
            input_schema=tool.inputSchema, save=not args.no_save,
        )

    print(format_result(result))

    data, _ = payload(result)
    items = data if isinstance(data, list) else []
    print(f"\n📊  Images for emulator '{args.emulator}': {len(items)}")

    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
