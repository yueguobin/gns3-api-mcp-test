# Stage 16: Cisco IOSv (QEMU) Large-Scale Batch Test - Test Record

## Basic Information

**Stage ID**: Stage 16  
**Stage Name**: Cisco IOSv (QEMU) Large-Scale Batch Test  
**Test Date**: 2026-06-15 ~ 2026-06-16  
**Test Type**: Stress test (QEMU node large-scale batch creation, top-level `template_id` verification)  
**Node Type**: QEMU / Cisco IOSv (vios-adventerprisek9-m.spa.159-3.m4)  
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

1. **Verify top-level `template_id`**: In batch mode, write `template_id` once at top level instead of repeating per item
2. **QEMU IOSv large-scale batch**: 40/100/1000 nodes in single `node_create` calls
3. **Naming behavior**: Template `default_name_format` overrides passed `name`
4. **Performance measurement**: Record actual completion times

---

## Test Target: Cisco IOSv Template

**Name**: Cisco IOSv  
**Template ID**: `ac877b51-252a-4a2c-a28d-a587b138355d`  
**Type**: `qemu`  
**Image**: `vios-adventerprisek9-m.spa.159-3.m4.qcow2`  
**Adapters**: `4` (adapter 0~3, each 1 port), `adapter_type=e1000`  
**Default name format**: `{name}-{0}`

### Port Model (Multi-adapter)

| adapter_number | Interface | Port count | Port | Label |
|---------------|-----------|-----------|------|-------|
| 0 | e1000 | 1 | 0 | `0/0` |
| 1 | e1000 | 1 | 0 | `1/0` |
| 2 | e1000 | 1 | 0 | `2/0` |
| 3 | e1000 | 1 | 0 | `3/0` |

---

## Backend Optimization Record

During stage 16 testing, the MCP backend underwent multiple hot-update iterations. The final test (1000 nodes) completed in ~190 seconds on the test server hardware.

| Iteration | Nodes | Result | Response |
|-----------|-------|--------|----------|
| First attempt (per-item template_id) | 40 | 39/40 + 1 retry | Occasional timeout |
| First top-level fix | 40 | 40/40 | 1 timeout (server-side rebuild) |
| Server restart | 40 | 40/40 | Stable |
| Repeated tests (v2~v9) | 40×8 | 320/320 | All stable |
| 100 nodes | 100 | 100/100 | ~2~3s |
| 1000 nodes | 1000 | 1000/1000 | **~190s** |

Optimizations delivered:
- Top-level `template_id` support (no per-item repetition)
- Response trimmed to `{node_id, name, node_type, status, console}` — 5 fields
- Bulk processing performance: from 50-node timeout to 1000-node success

---

## Test Process

### Test 16.1: Create Project

```json
project_create(name="iosv-1000-test") → project_id: "c84ff62f-..."
project_update(project_id="c84ff62f-...", auto_close=false)
```

✅ **Success**

---

### Test 16.2: 40 Nodes (Top-level template_id)

**Tool**: `mcp__My_GNS3_Server__node_create`

```json
{
  "project_id": "...",
  "template_id": "ac877b51-252a-4a2c-a28d-a587b138355d",
  "nodes": [
    {"x":100,"y":100}, {"x":280,"y":100}, ... 40 items
  ]
}
```

**Result**: 40/40 ✅ `name:"CiscoIOSv-1"~"CiscoIOSv-40"`

> Note: template `default_name_format` overrides passed `name`. The passed name is ignored; actual names follow template format.

✅ **Success**

---

### Test 16.3: 100 Nodes

```json
{
  "project_id": "5e442e79-...",
  "template_id": "ac877b51-...",
  "nodes": [100 items, 10×10 grid]
}
```

**Result**: 100/100 ✅, ~2~3s

✅ **Success**

---

### Test 16.4: 1000 Nodes (Limit Test)

```json
{
  "project_id": "c84ff62f-...",
  "template_id": "ac877b51-...",
  "nodes": [1000 items, 40×25 grid]
}
```

**Result**: 1000/1000 ✅, **~190 seconds**

```json
node_list(fields=["name"]) → {"nodes": [1000 items], "count": 1000}
```

#### Performance Data

| Batch | Nodes | Time | Rate | Bottleneck |
|-------|-------|------|------|------------|
| 40 | 40 | ~2s | ~20/s | — |
| 100 | 100 | ~3s | ~33/s | — |
| 1000 | 1000 | ~190s | ~5.3/s | Server CPU (J5040 4-core) |

✅ **Success** - 1000 nodes created, ~190s on J5040 hardware

---

## Stage Summary

### Test Results

| Test | Tool | Scale | Status | Notes |
|------|------|-------|--------|-------|
| 16.1 Create project | project_create/update | 1 | ✅ | auto_close=false |
| 16.2 Batch 40 nodes | node_create | 40 IOSv | ✅ | Top-level template_id |
| 16.3 Batch 100 nodes | node_create | 100 IOSv | ✅ | ~2~3s |
| 16.4 Batch 1000 nodes | node_create | 1000 IOSv | ✅ | ~190s, CPU bound |

### Key Findings
- 🟢 **Top-level `template_id` works**: One `template_id` at top, `nodes` need only `{x,y}`
- 🟢 **QEMU IOSv batch stable**: 1000/1000 success
- 🟢 **Response trimmed**: 5-field summary, inline return
- 🟡 **Naming controlled by template**: `name` parameter not directly used as final node name
- 🟡 **1000 nodes CPU-bound**: ~5.3 nodes/s on J5040, limited by server CPU

---

## Test Signature

**Test Executor**: Claude  
**Test Supervisor**: YueGuobin  
**Test Date**: 2026-06-15 ~ 2026-06-16  
**Test Status**: ✅ All Passed  
**Completion**: 4 test items, up to 1000 nodes

---

**Created**: 2026-06-15  
**Last Updated**: 2026-06-16  
**Version**: 1.0
