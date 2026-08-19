---
name: container-restart-via-mcp-only
description: GNS3 容器节点重启/操作只走 MCP node_stop→node_start，禁止 docker CLI/exec 直接触碰
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 26925966-39a5-4879-91ca-d19104aeba3a
  modified: 2026-08-19T14:46:01.075Z
---

GNS3 容器节点的重启方式：先 MCP `node_stop`，再 `node_start`。不要使用容器内的软重启，也不要用本机 docker CLI（docker restart / docker exec / docker logs）直接操作容器——虽然 gns3server 就在本机、docker 命令可用，但用户明确拒绝了这类操作（2026-08-19 FRRDocker-5 console 排障时被拦）。

**Why:** 用户把节点生命周期完全收口在 GNS3 MCP 层；docker 层直接操作绕过 GNS3 的状态管理（console 管道、链路 uBridge 挂接），可能造成状态不一致。

**How to apply:** 节点僵死（如 console 无输出）→ node_stop → **等状态真正 stopped（GUI/`node_get` 确认，别背靠背连发，留 10s+ dwell）** → node_start → 等就绪再探。2026-08-19 实证：node_stop 后 0~5s 内 node_start 会把 console 管道搞成永久哑死（TCP/WS 全通但零数据，token 正常也无认证错），用户手动 stop→start 即恢复。另：websocat 探测**别丢 stderr**、**现取现用 token**（10 分钟 TTL，等待循环里复用旧 token 会被拒且报错只在日志里）。仍不行就报告用户，别动 docker。配置一律走 console（websocat/[[gns3-ws-console-usage]]）或 device 工具。
