#!/usr/bin/env python3
"""Fix link port labels: set every endpoint label to ``eth{adapter_number}``.

API-created links (node_duplicate-following link_create, or manual link_create
without a label) get an auto-generated ``"{adapter}/{port}"`` label like "4/0"
instead of the port name "eth4". This script walks every link in a project and
PUTs each endpoint's label to ``eth{adapter_number}`` via the MCP ``link_update``
tool. Links whose endpoints are already correctly labeled are skipped.

Usage:
    python fix_link_labels.py --project <id>
    python fix_link_labels.py --project <id> --concurrency 20 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.gns3_mcp import call_tool, connect, payload  # noqa: E402


async def get_links(session, project_id: str) -> list[dict]:
    result, _ = await call_tool(
        session, "link_list",
        {"project_id": project_id, "fields": ["link_id", "nodes"]},
    )
    data, _ = payload(result)
    return data["links"]


def needs_fix(link: dict) -> bool:
    """True if any endpoint label is missing or not eth{adapter_number}."""
    for end in link.get("nodes") or []:
        ad = end.get("adapter_number")
        lbl = (end.get("label") or {}).get("text")
        if lbl != f"eth{ad}":
            return True
    return False


async def fix_one(session, project_id: str, link: dict, sem: asyncio.Semaphore,
                  dry_run: bool) -> tuple[bool, str]:
    """Update one link's labels; return (ok, link_id)."""
    nodes = []
    for end in link.get("nodes") or []:
        ad = end.get("adapter_number")
        nodes.append({
            "node_id": end["node_id"],
            "adapter_number": ad,
            "port_number": end.get("port_number", 0),
            "label": {"text": f"eth{ad}"},
        })
    if dry_run:
        return True, link["link_id"]
    async with sem:
        try:
            result, _ = await call_tool(session, "link_update", {
                "project_id": project_id,
                "link_id": link["link_id"],
                "kwargs": {"nodes": nodes},
            })
            if getattr(result, "isError", False):
                return False, link["link_id"]
            return True, link["link_id"]
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {link['link_id'][:8]} exception: {exc}")
            return False, link["link_id"]


async def main(args) -> None:
    async with connect() as session:
        links = await get_links(session, args.project)
        print(f"total links: {len(links)}")

        to_fix = [l for l in links if needs_fix(l)]
        print(f"need relabel: {len(to_fix)}  (skipped {len(links) - len(to_fix)} already ok)")

        if not to_fix:
            print("nothing to do.")
            return
        if args.dry_run:
            print(f"[dry-run] would update {len(to_fix)} links.")
            return

        sem = asyncio.Semaphore(args.concurrency)
        done = 0
        ok_total = fail_total = 0
        failed_ids: list[str] = []

        async def _track(coro, lid):
            nonlocal done, ok_total, fail_total
            ok, _ = await coro
            done += 1
            if ok:
                ok_total += 1
            else:
                fail_total += 1
                failed_ids.append(lid)
            if done % 200 == 0:
                print(f"  progress {done}/{len(to_fix)}  ok={ok_total} fail={fail_total}")

        await asyncio.gather(*(
            _track(fix_one(session, args.project, l, sem, False), l["link_id"])
            for l in to_fix
        ))

        print(f"\n✅ relabel done: {ok_total} ok, {fail_total} failed "
              f"({len(to_fix)} attempted).")
        if failed_ids:
            print("failed link_ids:", [f[:8] for f in failed_ids[:20]],
                  "..." if len(failed_ids) > 20 else "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True, help="GNS3 project id")
    p.add_argument("--concurrency", type=int, default=20,
                   help="max concurrent link_update calls (default 20)")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
