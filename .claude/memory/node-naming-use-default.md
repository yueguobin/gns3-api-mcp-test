---
name: node-naming-use-default
description: "node_create 不自定义节点名,沿用模板 default_name_format,除非用户明确要求起名"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d236e8af-7eec-496e-8330-2ef9c24f362a
  modified: 2026-08-09T16:31:52.736Z
---

用户反馈（2026-08-10，100-FRR-Node 任务）：建节点时不用配置名称，除非明确要求。模板自带 `default_name_format`（如 FRRDockerLite → `FRRDockerLite-{0}`），node_create 不传 name 即按规则自动命名；node_duplicate 复制时也是自动命名。

**Why:** 自定义名称是多余操作，且偏离模板默认的一致性。

**How to apply:** node_create 批量建节点时，`nodes` 项只给坐标 `{"x":..,"y":..}`，不传 `name`；表格/汇报里也别刻意强调自定义名。例外：用户明确要求起特定名字时才传 name。相关 [[mcp-backend-optimization]]（命名受 default_name_format 控制）、[[1000-frr-node]]。
