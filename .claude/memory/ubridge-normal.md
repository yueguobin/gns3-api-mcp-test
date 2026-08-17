---
name: ubridge-normal
description: uBridge 二层转发正常；链路不通别归咎 uBridge，别用 link_reset/重启节点瞎修
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 763c6a9d-275e-4c08-a11a-8ac6b8ec8af4
  modified: 2026-08-11T16:59:33.339Z
---

uBridge 二层转发一直正常，**不是**链路不通的原因。

**Why:** 在 FRR-BGP-EVPN 拓扑（5 FRR spine/leaf）里，多条直连链路出现 ARP FAILED / ping 100% loss，我误判成 "uBridge 单通 / MAC 学习异常"，连做两次 `link_reset` 无效后又 `node_stop_all` + `node_start_all` 重启全部节点，白丢了已配好的 FRR 接口/BGP 配置。用户明确指出：uBridge 没问题。

**How to apply:** 链路不通时去查真正原因——GNS3 adapter↔容器 eth 编号映射、接口 IP 是否配在正确的 eth、MAC、节点/daemon 是否就绪、协议配置——**不要**默认归咎 uBridge，**不要**把 `link_reset` 或 `node_stop/start` 当万能修复。任何破坏性操作（尤其重启节点会清空 FRR running-config）之前，必须先 `write memory` 或 dump running-config 备份。相关：[[100-frr-node]]（已删 uBridge 误判）、[[gns3-ws-console-usage]]。
