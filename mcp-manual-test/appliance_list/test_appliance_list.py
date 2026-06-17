#!/usr/bin/env python3
"""Test the MCP tool ``appliance_list``.

Tool description
----------------
List all available appliances in the GNS3 appliance/template library.
Use ``--fields`` to return only the fields you need.

Input parameters
----------------
fields : list of str (optional)
    Return only these fields. Available values:
    ``name``, ``category``, ``description``, ``vendor_name``,
    ``product_name``, ``status``, ``availability``, ``images``,
    ``versions``, ``tags``, ``symbol``, ``usage``, ``builtin``.

Returns
-------
List of appliance objects, each containing the requested (or all) fields.

Test flow
---------
Connects to GNS3 via MCP (SSE), calls appliance_list to retrieve the
full appliance library catalog.

Usage::

    # List all appliances (all fields)
    ../../.venv/bin/python test_appliance_list.py
    # List with selected fields only
    ../../.venv/bin/python test_appliance_list.py --fields name category vendor_name
    # View the tool's input schema only
    ../../.venv/bin/python test_appliance_list.py --show-schema
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

TOOL = "appliance_list"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test the MCP tool appliance_list")
    p.add_argument(
        "--fields",
        nargs="*",
        default=None,
        help="Fields to return (space-separated). Omit to get all fields.",
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


def count_items(list_result) -> int:
    """Count the number of appliance entries in the result.

    Handles both list-type and dict-with-appliances-key responses.
    """
    data, _ = payload(list_result)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        items = data.get("appliances", data.get("data", []))
        return len(items) if isinstance(items, list) else 0
    return 0


def summary(list_result) -> str:
    """Return a one-line summary of the appliance list."""
    data, src = payload(list_result)
    items = data if isinstance(data, list) else (data or {}).get("appliances", [])
    if not isinstance(items, list):
        return "0 items (unexpected structure)"
    if not items:
        return "0 items (empty)"
    # Collect categories present
    cats = set()
    for it in items:
        c = it.get("category") or "unknown"
        cats.add(c)
    cat_str = ", ".join(sorted(cats))
    names = [it.get("name", "") for it in items[:3]]
    first_few = ", ".join(n for n in names if n)
    return f"{len(items)} items | categories: {cat_str} | e.g. {first_few} ..."


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

        call_args = {}
        if args.fields is not None:
            call_args["fields"] = args.fields

        print(f"\n=== Calling {TOOL}({json.dumps(call_args, ensure_ascii=False)}) ===")
        result, elapsed, _ = await call_and_record(
            session,
            script_file=__file__,
            tool=TOOL,
            arguments=call_args,
            input_schema=tool.inputSchema,
            save=not args.no_save,
        )

    print(format_result(result))

    n = count_items(result)
    print(f"\n📊  Total appliances: {n}")
    if n > 0:
        print(f"📋  {summary(result)}")

    print(f"\n⏱  {TOOL} elapsed {elapsed * 1000:.1f} ms")
    sys.exit(1 if getattr(result, "isError", False) else 0)


if __name__ == "__main__":
    asyncio.run(main())
