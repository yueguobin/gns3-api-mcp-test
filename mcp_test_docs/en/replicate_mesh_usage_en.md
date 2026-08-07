# replicate_mesh.py — GNS3 Mesh Replication Script Guide

`mcp-manual-test/replicate_mesh.py`: batch-replicates a mesh of routers (nodes + links) on a 225px grid through the GNS3 MCP, for building large IOU topologies (e.g. the 10×10 mesh matrix in the 100-node-iou project).

## Prerequisites

- Python 3.11+ with the `mcp` SDK (already installed in the repo `.venv`): run with `.venv/bin/python`
- `.env` connection config (see `.env.example`): `GNS3_MCP_URL` / `GNS3_MCP_TOKEN`
  - Local GNS3 server: `GNS3_MCP_URL=http://127.0.0.1:3080/v3/mcp/transport/sse`
- **Source mesh nodes must be `stopped`**: GNS3 3.1.0.dev5+ refuses to duplicate running nodes (409 "Cannot duplicate node data while the node is running"). The script checks this and exits with a clear error.

## Usage Examples

```bash
# Plan only (read-only, safe)
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 4x3 --place down --dry-run

# Copy 2×2 = 4 replicas to the right of the source mesh
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 2x2 --place right

# Explicit origin (negative coords need the = form)
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 1x3 --origin=-1830,-105

# Complete an existing matrix (skip occupied slots)
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 10x10 --origin=-1830,-555 --skip-existing

# Repair: scan the grid frame, create missing links for complete meshes
.venv/bin/python mcp-manual-test/replicate_mesh.py \
    --project <project_id> --grid 10x10 --origin=-1830,-555 --repair-links
```

## Options

| Option | Description |
|---|---|
| `--project` | Project UUID (required) |
| `--source` | Source node names; order defines roles A/B/C… (default `R-1 … R-6`) |
| `--grid` | Replica count `WxH` (cols x rows), e.g. `4x3`, `1x3` |
| `--place` | `right` / `down` / `origin`: place the block right of / below / at an explicit origin |
| `--origin` | `X,Y` block origin (for `--place origin`; negative coords need `--origin=X,Y`) |
| `--spacing` | Grid spacing in px (default 225) |
| `--dry-run` | Read-only plan (topology discovery, positions, collision warnings) |
| `--skip-existing` | Skip replica slots overlapping existing nodes (for completing a matrix) |
| `--repair-links` | No duplication; scan the frame, create missing links for complete meshes, report incomplete ones |

## Behavior & Limits

- **Auto topology discovery**: links whose two endpoints are both inside the source set are recreated with identical adapter/port pairs — generic for any source mesh shape (not hardcoded to 6 nodes).
- **Placement math**: intra-mesh step = `--spacing`; inter-mesh step = `mesh-cols×spacing` / `mesh-rows×spacing` (derived from the source mesh's actual 3×2 node layout).
- **Collision detection**: warns per node when target positions overlap existing nodes (visible in dry-run; `--skip-existing` skips them).
- **512-node IOU hard cap**: IOU application_id space is 1–512; all OPENED projects on the same compute share it (409 "Cannot create a new IOU node (limit of 512…)"). `--repair-links` reports frame slots left empty by the cap.
- **Interrupt safety**: if the node phase fails, a `finally` block still links the completed replicas — no orphaned unlinked meshes. Duplicated nodes carry the source nvram config (IOU duplicate behavior); running several meshes at once causes IP/hostname conflicts.
- `link_create` is chunked to ≤100 links per call.

## Test Record (2026-08-07)

- 100-node-iou project (`d82d5ee5-65c6-49fa-873f-bdb0790b393a`), grown from 6 IOU routers:
  - Manual + script replication up to 16 meshes (96 nodes / 176 links)
  - `--grid 10x10 --skip-existing` hit the 512 cap (reached 511 nodes), script aborted
  - `--repair-links` created 759 missing links; leftover node R-511 deleted
  - **Final: 85 meshes = 510 nodes / 935 links** (10×10 frame rows 0–7 full + row 8 cols 0–4)
- Related experience: `.claude/memory/100node-iou-ospf.md` (addressing scheme, OSPFv2/v3 AF syntax, tool quirks)
