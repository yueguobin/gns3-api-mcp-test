# Stage 17: Alpine Linux (Docker) Node Batch Test - Test Record

## Basic Information

**Stage ID**: Stage 17  
**Stage Name**: Alpine Linux (Docker) Node Batch Test  
**Test Date**: 2026-06-16  
**Test Type**: Docker node batch creation + full mesh / circulant topology  
**Node Type**: Docker / Alpine Linux  
**Test Status**: ✅ All Passed

### Test Server Environment

| Item | Value |
|------|-------|
| Hostname | home |
| OS | Debian GNU/Linux 12 (bookworm) |
| Kernel | Linux 6.1.0-42-amd64 x86_64 |
| CPU | Intel Pentium Silver J5040 @ 2.00GHz (4 cores) |
| RAM | 11 GiB |
| Disk | 915G |

---

## Test Objectives

1. **Docker batch creation**: 100 Alpine Linux containers in a single `node_create` call
2. **Full mesh topology**: 10 nodes × 9 links each = 45 links
3. **Circulant graph C(100,{1,2})**: 100 nodes × 4 links each = 200 links
4. **Docker adapter model**: `adapters=30`, all links use `port_number=0`, differentiated by `adapter_number`

---

## Test Target: Alpine Linux Template

**Name**: Alpine Linux  
**Template ID**: `ef7d4150-d6d1-4ff4-816b-403e2235776e`  
**Type**: `docker`  
**Image**: `alpine`  
**Adapters**: `30` (adapter 0~29, each 1 port)  
**Default name format**: `{name}-{0}`

### Docker Port Model

| Property | Value |
|----------|-------|
| `adapters` | 30 (adapter 0~29) |
| Ports per adapter | 1 (port 0) |
| Port label | `{adapter_number}/0` |

> Docker containers have 30 adapters — much more than QEMU IOSv (4). Suitable for dense topologies.

---

## Test Process

### Test 17.1: 10-Node Full Mesh

**Tools**: `project_create` / `node_create` / `link_create`  
**Project**: alpine-mesh-test

#### Port Assignment (Critical Detail)

For Docker containers, `port_number` is always 0. Different links must use different `adapter_number`.

For pair `(i, j)` with `i < j`:
- node_i uses `adapter_(j-1)` / port0
- node_j uses `adapter_i` / port0

Maximum adapters used per node: 9 (adapter 0~8), well under the 30 limit.

#### Issue Encountered

❌ **First attempt failed with 409**: All links from AlpineLinux-2 used `adapter=0` incorrectly, causing port conflicts. Deleted project and retried with correct mapping.

✅ Second attempt: 45/45 ✅ all success.

#### Verification
```json
link_list → count: 45
node_links(AlpineLinux-1) → count: 9 (connected to all 9 others)
```

✅ **Success** - Full mesh complete

---

### Test 17.2: 100-Node Circulant C(100,{1,2}) = 200 Links

**Tools**: `mcp__My_GNS3_Server__node_create` / `link_create`  
**Project**: alpine-100 (efe40892-…)

#### Create 100 Alpine Docker Nodes

```json
{
  "project_id": "efe40892-...",
  "template_id": "ef7d4150-...",
  "nodes": [
    {"x":100,"y":100}, {"x":220,"y":100}, ... 100 items
  ]
}
```

**100/100 ✅** — Docker creation is very fast (seconds).

#### Topology: Circulant C(100,{1,2})

Each node gets 4 links:
- dist1 `(i, i+1)`: adapter 0 ↔ adapter 2
- dist2 `(i, i+2)`: adapter 1 ↔ adapter 3

Node names: `AlpineLinux-1` ~ `AlpineLinux-100`

#### Creating 200 Links

| Batch | Count | Type | Ports | Result |
|-------|-------|------|-------|--------|
| 1 | 50 | dist1 (i=0..49) | ad0↔ad2 | ✅ |
| 2 | 50 | dist1 (i=50..99 + wrap) | ad0↔ad2 | ✅ |
| 3 | 50 | dist2 (i=0..49) | ad1↔ad3 | ✅ |
| 4 | 50 | dist2 (i=50..99 + wrap) | ad1↔ad3 | ✅ |

> Note: `link_create` processes ~50 links (~11KB) per call. 200 links split into 4 batches.

#### Verification
```json
link_list(fields=["link_id"]) → {"count": 200}
```

✅ **Success** — 100 nodes, 200 links, all degree=4

---

## Stage Summary

### Test Results

| Test | Tool | Scale | Status | Notes |
|------|------|-------|--------|-------|
| 17.1 10-node full mesh | node_create / link_create | 10 nodes, 45 links | ✅ | First attempt had port conflict |
| 17.2 100-node circulant | node_create / link_create | 100 nodes, 200 links | ✅ | 4 batch link_create calls |

### Scale

| Resource | Count | Notes |
|----------|-------|-------|
| Nodes | 100 | AlpineLinux-1~100 |
| Links | 200 | dist1 100 + dist2 100 |
| Per-node ports | 4 | adapter 0/1/2/3 |
| Node type | docker | Alpine Linux |

### Docker vs QEMU vs Dynamips Creation Speed

| Node Type | 100 nodes | Characteristics |
|-----------|-----------|-----------------|
| Dynamips c7200 | Very slow | Loads IOS image, high resource usage |
| QEMU IOSv | ~190s (1000) | linked_clone copies qcow2 |
| Docker Alpine | **Seconds** | Container-based, no disk image |

### Key Findings
- 🟢 **Docker creation is fastest**: 100 nodes in seconds
- 🟢 **30 adapters provide ample ports** for dense topologies
- 🟢 **`link_create` limit ~50 links per call** (~11KB), beyond that split into batches
- 🟢 **Top-level `template_id` works** for Docker too
- 🟡 **Port assignment must be careful**: Docker uses `port_number=0` always, different links need different `adapter_number`
- 🟡 **Incorrect adapter mapping causes 409**: Port conflict errors when reusing the same adapter on one node

---

## Test Signature

**Test Executor**: Claude  
**Test Supervisor**: YueGuobin  
**Test Date**: 2026-06-16  
**Test Status**: ✅ All Passed  
**Completion**: 2 test items, 100 nodes + 200 links

---

**Created**: 2026-06-16  
**Last Updated**: 2026-06-16  
**Version**: 1.0
