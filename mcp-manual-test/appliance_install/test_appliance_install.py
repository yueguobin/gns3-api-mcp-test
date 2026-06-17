#!/usr/bin/env python3
"""Test the MCP tool ``appliance_install``.

Tool description
----------------
Create a template from a GNS3 appliance definition. The appliance definition
is read from local .gns3a files bundled with the server.

**Important notes:**
  - This does NOT download images. Images must be placed in the GNS3 images
    directory (e.g. ``~/GNS3/images/``) beforehand.
  - The appliance definition is read from local .gns3a files bundled with
    the server — it does NOT pull from an external registry.
  - Use ``appliance_get`` first to inspect what images are required for a
    given appliance before installing.

Input parameters
----------------
appliance_id : str (UUID, required)
    UUID of the appliance to install, e.g.
    ``"cf5d1f22-953a-434d-a07e-6e17de85acf1"``.

Returns
-------
Template / appliance install confirmation. If the appliance has already been
installed (template already exists), the server may return an error.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls appliance_install to create a template
from the appliance definition. By default it auto-discovers an appliance ID
via appliance_list; use --appliance-id to specify one directly.

Usage::

    # Auto-select the first appliance
    ../../.venv/bin/python test_appliance_install.py
    # Manual ID
    ../../.venv/bin/python test_appliance_install.py --appliance-id <UUID>
    # View the tool's input schema only
    ../../.venv/bin/python test_appliance_install.py --show-schema
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

TOOL = "appliance_install"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool appliance_install")
    p.add_argument(
        "--appliance-id",
        help="UUID of the appliance to install (omit to auto-discover from appliance_list)",
    )
    p.add_argument(
        "--show-schema",
        action="store_true",
        help="Print the tool's input schema and exit",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Skip persisting call data + raw return to a JSON record file",
    )
    return p.parse_args()


def extract_ids(list_result) -> list[tuple[str, str]]:
    """Extract (appliance_id, name) pairs from the appliance_list MCP result."""
    data, _ = payload(list_result)
    items = data if isinstance(data, list) else (data or {}).get("appliances", [])
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        aid = it.get("appliance_id") or it.get("id")
        if aid:
            out.append((str(aid), it.get("name", "")))
    seen: set[str] = set()
    uniq = []
    for aid, name in out:
        if aid not in seen:
            seen.add(aid)
            uniq.append((aid, name))
    return uniq


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

        appliance_id = args.appliance_id
        if not appliance_id:
            print("\nNo --appliance-id given, calling appliance_list to auto-discover ...")
            lr, _ = await call_tool(session, "appliance_list", {})
            ids = extract_ids(lr)
            if not ids:
                print("⚠️  Could not parse any appliance id from appliance_list.")
                print("Please retry with --appliance-id <UUID>")
                print(f"Raw content[0].text (first 200 chars):")
                print(repr(getattr(lr.content[0], "text", ""))[:200])
                return
            appliance_id, name = ids[0]
            print(f"  Found {len(ids)} appliances, picked first: {name or '(unnamed)'} -> {appliance_id}")

        print(f"\n=== Calling {TOOL}({{'appliance_id': '{appliance_id}'}}) ===")
        result, elapsed, _ = await call_and_record(
            session,
            script_file=__file__,
            tool=TOOL,
            arguments={"appliance_id": appliance_id},
            input_schema=tool.inputSchema,
            save=not args.no_save,
        )

    print(format_result(result))
    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
