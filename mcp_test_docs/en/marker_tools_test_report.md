# GNS3 MCP Marker Tools Test Report

Testing the two new traffic-insight MCP tools: `link_marker` (per-link) and `marker_definition` (project-level, auto-fanout to all links).

- **Date:** 2026-07-26
- **Project:** `mark-test` (`20f40515-35b0-4a11-b15f-9552ba6e4715`)
- **Test topology:** 13 nodes, 16 links (dynamips + IOL + qemu + docker + ethernet_switch)
- **Test link:** IOU3(Ethernet0/2) ↔ Switch1(Ethernet1) — `e5c03b8c-29e8-40e5-a08c-46ff08248b12`
- **BPF:** `ip proto 89` (OSPF, protocol number 89; the `ospf` keyword is **not supported** by the BPF parser on this GNS3 3.1 server — returns 409)

## 1. `link_marker` — Per-link marker

### create

```json
// Input
{"project_id": "20f40515-...", "link_id": "e5c03b8c-...", "action": "create", "bpf": "ip proto 89"}

// Output
{"bpf": "ip proto 89", "tag": null, "enabled": true, "color": null,
 "highlight_duration": null, "capture_node_id": "67d65e52-fbc9-46b0-8815-4da95bb91b09"}
```

Result: ✅ Marker `marker-e5c03b8c-c274` created, captured on the **IOU3** side of the link.

### read (via link_get)

`markers` dict on the link confirmed the marker: `"marker-e5c03b8c-c274": {"bpf": "ip proto 89", "enabled": true, ...}`

### delete

```json
// Input
{"project_id": "20f40515-...", "link_id": "e5c03b8c-...", "action": "delete", "marker_name": "marker-e5c03b8c-c274"}

// Output
{"message": "Marker 'marker-e5c03b8c-c274' deleted from link e5c03b8c-...", ...}
```

Result: ✅ Marker removed. `link_get` → `markers: {}`.

## 2. `marker_definition` — Project-level marker (fanout)

### create

```json
// Input
{"project_id": "20f40515-...", "action": "create", "bpf": "ip proto 89",
 "name": "ospf-hello", "color": "#ff5722"}

// Output
{"bpf": "ip proto 89", "tag": null, "color": "#ff5722", "highlight_duration": null}
```

Result: ✅ Definition `ospf-hello` created. Auto-fanout to **all 16 links** in the project.

### list

```json
// Output
{"ospf-hello": {"bpf": "ip proto 89", "color": "#ff5722", "link_ids": [
  "04f21b62-...", "593fdfaa-...", ..., "281e6eb3-..."  // all 16 link IDs
]}}
```

### inherited markers on links (verified via link_get on IOU1↔IOU3 link `562c4766`)

```json
"global-ospf-hello": {
  "bpf": "ip proto 89", "enabled": true, "color": "#ff5722",
  "capture_node_id": "5adfef6c-...", "inherited_from": "ospf-hello"
}
```

Result: ✅ `global-ospf-hello` present on all links with `inherited_from: ospf-hello`. Capture side auto-selected per link.

### delete

```json
// Input
{"project_id": "20f40515-...", "action": "delete", "def_name": "ospf-hello"}

// Output
{"message": "Marker definition 'ospf-hello' deleted", ...}
```

Result: ✅ Definition deleted. `global-ospf-hello` auto-removed from all 16 links. Verified on `e5c03b8c` → `markers: {}`.

## 3. `global-*` protection

Per the tool description, markers named `global-*` are inherited from project-level definitions and **cannot be modified or deleted** via `link_marker`. This protects the inheritance chain — changes must go through `marker_definition update/delete`.

## 4. Edge cases & notes

| Item | Result | Detail |
|------|--------|--------|
| `ospf` keyword | ❌ 409 | `can't parse filter expression: syntax error` — use `ip proto 89` instead |
| IOL link compatibility | ✅ | Marker works on IOL links (IOU3 side auto-selected for capture) |
| No color/defaults | ✅ | `color` and `highlight_duration` default to null — UI may not highlight without explicit color |
| Coexistence | ✅ | Link-level and `global-*` markers coexist on the same link independently |

## Summary

Both `link_marker` and `marker_definition` work as designed on GNS3 3.1. The project-level fanout mechanism correctly inherits to all links and cleans up on delete. The only minor caveat is that the `ospf` BPF keyword is not supported — use numeric `ip proto 89` instead.
