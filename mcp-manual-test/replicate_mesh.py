#!/usr/bin/env python3
"""Replicate a mesh (routers + their links) in a GNS3 project via MCP.

Purely structural: node_duplicate + link_create. The duplicated IOU nodes
carry their source nvram/startup-config (GNS3 duplicate behavior) — this
script does NOT change IPs or hostnames. See .claude/memory/100node-iou-ospf.md
for the duplicate-IP caveat when running several meshes at once.

The source mesh is auto-discovered: given the --source node names, the
script finds every link whose two endpoints are inside the source set and
recreates the same (adapter, port) pairs in each replica.

Usage:
    python replicate_mesh.py --project <id> --grid 2x2 --place right
    python replicate_mesh.py --project <id> --grid 4x3 --place down --dry-run
    python replicate_mesh.py --project <id> --grid 1x2 --origin "-1155,-555"

Options:
    --source  6 node names of the source mesh (default: R-1 R-2 ... R-6)
    --grid    WxH number of replicas (columns x rows), e.g. 4x3
    --place   right | down | origin — where the new block starts
    --origin  X,Y for --place origin (position of the block's top-left node)
    --spacing grid spacing in px (default 225)
    --dry-run plan only, no changes
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib.gns3_mcp import call_tool, connect, payload  # noqa: E402

LINK_BATCH_LIMIT = 100  # link_create batch cap


async def get_nodes(session, project_id: str) -> list[dict]:
    result, _ = await call_tool(
        session, "node_list",
        {"project_id": project_id, "fields": ["name", "node_id", "x", "y", "status"]},
    )
    data, _ = payload(result)
    return data["nodes"]


async def get_links(session, project_id: str) -> list[dict]:
    result, _ = await call_tool(
        session, "link_list", {"project_id": project_id, "fields": ["link_id", "nodes"]}
    )
    data, _ = payload(result)
    return data["links"]


def discover_topology(links: list[dict], source_ids: list[str]) -> list[tuple]:
    """[(role_a, ad_a, pt_a, role_b, ad_b, pt_b), ...] for links whose two
    endpoints are both inside the source mesh. Role = A, B, C... per --source order."""
    roles = {nid: chr(ord("A") + i) for i, nid in enumerate(source_ids)}
    topology = []
    for link in links:
        ends = link.get("nodes") or []
        if len(ends) != 2:
            continue
        n0, n1 = ends[0], ends[1]
        if n0["node_id"] in roles and n1["node_id"] in roles:
            topology.append((
                roles[n0["node_id"]], n0["adapter_number"], n0["port_number"],
                roles[n1["node_id"]], n1["adapter_number"], n1["port_number"],
            ))
    return topology


def mesh_layout(nodes: list[dict], source_ids: list[str]) -> tuple[dict, int, int, int, int]:
    """Relative (x, y) of each source node vs the mesh's min-x/min-y, the
    number of node-columns / node-rows the mesh spans, and the absolute
    min-x / min-y of the source mesh (for --place right/down anchoring)."""
    pts = {n["node_id"]: (n["x"], n["y"]) for n in nodes if n["node_id"] in source_ids}
    min_x = min(x for x, _ in pts.values())
    min_y = min(y for _, y in pts.values())
    rel = {nid: (pts[nid][0] - min_x, pts[nid][1] - min_y) for nid in source_ids}
    n_cols = len({rx for rx, _ in rel.values()})
    n_rows = len({ry for _, ry in rel.values()})
    return rel, n_cols, n_rows, min_x, min_y


def block_origin(args, min_x: int, min_y: int, n_cols: int, n_rows: int,
                 spacing: int) -> tuple[int, int]:
    """Compute the new block's top-left position from --place / --origin."""
    if args.place == "right":
        return min_x + n_cols * spacing, min_y
    if args.place == "down":
        return min_x, min_y + n_rows * spacing
    if not args.origin:
        raise SystemExit("--origin X,Y required when --place origin")
    ox, oy = args.origin.split(",")
    return int(ox), int(oy)


def replica_positions(
    rel: dict, n_cols: int, n_rows: int, origin: tuple[int, int], spacing: int,
    source_ids: list[str], row: int, col: int,
) -> list[tuple[int, int]]:
    """Absolute position of each source node inside replica (row, col)."""
    ox, oy = origin
    return [
        (ox + col * n_cols * spacing + rel[nid][0],
         oy + row * n_rows * spacing + rel[nid][1])
        for nid in source_ids
    ]


async def duplicate_nodes(
    session, project_id: str, source_ids: list[str], roles: list[str],
    positions: list[tuple[int, int]], dry_run: bool,
) -> dict[str, dict]:
    """Duplicate the source nodes (parallel); return {role: {name, node_id, x, y}}."""

    async def _one(nid: str, role: str, x: int, y: int) -> tuple[str, dict]:
        if dry_run:
            return role, {"name": "DRY-RUN", "node_id": None, "x": x, "y": y}
        result, _ = await call_tool(session, "node_duplicate", {
            "project_id": project_id, "node_id": nid, "x": int(x), "y": int(y),
        })
        if getattr(result, "isError", False):
            raise RuntimeError(f"node_duplicate failed for {nid}: {result}")
        data, _ = payload(result)
        node = data["node"]
        return role, {"name": node["name"], "node_id": node["node_id"], "x": x, "y": y}

    created = {}
    results = await asyncio.gather(*(
        _one(nid, role, x, y)
        for nid, role, (x, y) in zip(source_ids, roles, positions)
    ))
    for role, info in results:
        created[role] = info
        print(f"  ✓ {role} → {info['name']} ({info['node_id'][:8]}…) @ ({info['x']},{info['y']})")
    return created


async def repair_links(
    session, project_id: str, nodes: list[dict], links: list[dict],
    topology: list[tuple], rel: dict, n_cols: int, n_rows: int,
    origin: tuple[int, int], spacing: int, source_ids: list[str],
    roles: list[str], rows: int, cols: int,
) -> None:
    """Link up complete meshes in the grid frame that are missing links;
    report incomplete meshes (e.g. after an interrupted run)."""
    pos_to_node = {(n["x"], n["y"]): n for n in nodes}
    existing = set()
    for link in links:
        ends = link.get("nodes") or []
        if len(ends) != 2:
            continue
        existing.add(tuple(sorted(
            (ends[0]["node_id"], ends[0]["adapter_number"], ends[0]["port_number"],
             ends[1]["node_id"], ends[1]["adapter_number"], ends[1]["port_number"]),
            key=str)))

    created_total = failed_total = 0
    for r in range(rows):
        for c in range(cols):
            pos = replica_positions(rel, n_cols, n_rows, origin, spacing, source_ids, r, c)
            found = [pos_to_node.get(p) for p in pos]
            if not all(found):
                print(f"  ⚠ replica[{r},{c}] INCOMPLETE: {sum(1 for n in found if n)}/6 nodes — "
                      f"missing at {[p for p, n in zip(pos, found) if n is None]}")
                continue
            by_role = {role: node["node_id"] for role, node in zip(roles, found)}
            missing = []
            for role_a, ad_a, pt_a, role_b, ad_b, pt_b in topology:
                edge = tuple(sorted(
                    (by_role[role_a], ad_a, pt_a, by_role[role_b], ad_b, pt_b), key=str))
                if edge not in existing:
                    missing.append({"link_type": "ethernet",
                                    "nodes": [{"node_id": by_role[role_a],
                                               "adapter_number": ad_a, "port_number": pt_a,
                                               "label": {"text": f"eth{ad_a}"}},
                                              {"node_id": by_role[role_b],
                                               "adapter_number": ad_b, "port_number": pt_b,
                                               "label": {"text": f"eth{ad_b}"}}]})
            if missing:
                for i in range(0, len(missing), LINK_BATCH_LIMIT):
                    chunk = missing[i:i + LINK_BATCH_LIMIT]
                    result, _ = await call_tool(session, "link_create", {
                        "project_id": project_id, "links": chunk,
                        "fields": ["link_id", "link_type"],
                    })
                    if getattr(result, "isError", False):
                        failed_total += len(chunk)
                        print(f"  ✗ replica[{r},{c}] link batch errored: {result}")
                        continue
                    data, _ = payload(result)
                    ok = sum(1 for item in data or [] if item.get("status") == "success")
                    created_total += ok
                    failed_total += len(chunk) - ok
                print(f"  ✓ replica[{r},{c}] created {len(missing)} missing links "
                      f"({len(topology) - len(missing)} already present)")
            else:
                print(f"  ✓ replica[{r},{c}] already complete ({len(topology)} links)")
    print(f"\n✅ repair done: {created_total} links created, {failed_total} failed. "
          f"Review any ⚠ INCOMPLETE replicas and delete their leftover nodes.")


async def create_links(
    session, project_id: str, replicas: list[dict[str, str]],
    topology: list[tuple], dry_run: bool,
) -> tuple[int, int]:
    """Create the topology links inside every replica (chunked ≤100/call).
    Returns (attempted, failed)."""
    specs = []
    for replica in replicas:
        for role_a, ad_a, pt_a, role_b, ad_b, pt_b in topology:
            specs.append({
                "link_type": "ethernet",
                "nodes": [
                    {"node_id": replica[role_a], "adapter_number": ad_a,
                     "port_number": pt_a, "label": {"text": f"eth{ad_a}"}},
                    {"node_id": replica[role_b], "adapter_number": ad_b,
                     "port_number": pt_b, "label": {"text": f"eth{ad_b}"}},
                ],
            })
    attempted = len(specs)
    failed = 0
    for i in range(0, len(specs), LINK_BATCH_LIMIT):
        chunk = specs[i:i + LINK_BATCH_LIMIT]
        if dry_run:
            print(f"  [dry-run] link_create ×{len(chunk)} (batch {i // LINK_BATCH_LIMIT + 1})")
            continue
        result, _ = await call_tool(session, "link_create", {
            "project_id": project_id, "links": chunk,
            "fields": ["link_id", "link_type"],
        })
        if getattr(result, "isError", False):
            failed += len(chunk)
            print(f"  ✗ link_create batch {i // LINK_BATCH_LIMIT + 1} errored: {result}")
            continue
        data, _ = payload(result)
        for item in data or []:
            if item.get("status") != "success":
                failed += 1
                print(f"  ✗ link failed: {item}")
        print(f"  ✓ link_create batch {i // LINK_BATCH_LIMIT + 1} ({len(chunk)} links)")
    return attempted, failed


async def main(args) -> None:
    cols, _, rows = args.grid.lower().partition("x")
    cols, rows = int(cols), int(rows)
    roles = [chr(ord("A") + i) for i in range(len(args.source))]

    async with connect() as session:
        nodes = await get_nodes(session, args.project)
        links = await get_links(session, args.project)

        by_name = {n["name"]: n for n in nodes}
        missing = [n for n in args.source if n not in by_name]
        if missing:
            raise SystemExit(f"source node(s) not found: {missing}")
        source_ids = [by_name[n]["node_id"] for n in args.source]

        running = [n["name"] for n in nodes
                   if n["node_id"] in source_ids and n.get("status") == "started"]
        if running:
            raise SystemExit(
                f"source node(s) RUNNING: {running} — GNS3 refuses to duplicate running "
                f"nodes (409). Stop them or use a stopped mesh as --source "
                f"(e.g. --source R-7 R-8 R-9 R-10 R-11 R-12)."
            )

        topology = discover_topology(links, source_ids)
        if not topology:
            raise SystemExit("no links found inside the source mesh (check --source)")
        rel, n_cols, n_rows, min_x, min_y = mesh_layout(nodes, source_ids)
        origin = block_origin(args, min_x, min_y, n_cols, n_rows, args.spacing)

        if args.repair_links:
            await repair_links(session, args.project, nodes, links, topology,
                               rel, n_cols, n_rows, origin, args.spacing,
                               source_ids, roles, rows, cols)
            return

        print(f"source: {', '.join(args.source)}  ({len(topology)} links, "
              f"{n_cols}×{n_rows} node layout)")
        print(f"grid: {cols}×{rows} replicas, origin=({origin[0]},{origin[1]}), "
              f"spacing={args.spacing}px")

        occupied = {(n["x"], n["y"]) for n in nodes}
        plan = []
        for r in range(rows):
            for c in range(cols):
                pos = replica_positions(rel, n_cols, n_rows, origin, args.spacing, source_ids, r, c)
                collisions = [p for p in pos if p in occupied]
                if args.skip_existing and collisions:
                    print(f"  ⏭ replica[{r},{c}] skipped ({len(collisions)} nodes collide with existing)")
                    continue
                plan.append((r, c, pos))
                if collisions:
                    print(f"  ⚠ replica[{r},{c}] OVERLAPS existing nodes at {collisions} "
                          f"(will create anyway)")
                else:
                    print(f"  replica[{r},{c}] nodes @ {pos}")

        if args.dry_run:
            print(f"\n[dry-run] would create {len(plan)}×{len(source_ids)} nodes "
                  f"+ {len(plan) * len(topology)} links. Nothing changed.")
            return

        print("\ncreating nodes…")
        replicas = []
        try:
            for r, c, pos in plan:
                print(f"replica[{r},{c}]:")
                replicas.append(await duplicate_nodes(
                    session, args.project, source_ids, roles, pos, dry_run=False))
        except Exception as exc:  # noqa: BLE001 — abort but still link completed replicas
            print(f"\n✗ node phase aborted at replica[{r},{c}]: {exc}")
        finally:
            if replicas:
                print("\ncreating links for completed replicas…")
                role_maps = [{role: n["node_id"] for role, n in rep.items()} for rep in replicas]
                attempted, failed = await create_links(
                    session, args.project, role_maps, topology, dry_run=False)
                print(f"\n✅ {len(replicas)} replicas linked: {attempted} links ({failed} failed)")
            else:
                print("\nno replicas completed, nothing to link")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True, help="GNS3 project id")
    p.add_argument("--source", nargs="+", default=["R-1", "R-2", "R-3", "R-4", "R-5", "R-6"],
                   help="source node names (order defines roles A,B,C…)")
    p.add_argument("--grid", required=True, help="replica grid WxH, e.g. 4x3")
    p.add_argument("--place", choices=["right", "down", "origin"], default="origin")
    p.add_argument("--origin", default=None,
                   help="X,Y of block top-left (for --place origin); "
                        "negative coords need the = form, e.g. --origin=-1155,795")
    p.add_argument("--spacing", type=int, default=225)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-existing", action="store_true",
                   help="skip replicas whose node positions collide with existing nodes "
                        "(for completing an existing matrix)")
    p.add_argument("--repair-links", action="store_true",
                   help="do not duplicate anything; scan the grid frame and create missing "
                        "links for complete meshes (e.g. after an interrupted run)")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
