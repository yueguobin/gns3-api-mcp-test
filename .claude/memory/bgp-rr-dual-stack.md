---
name: bgp-rr-dual-stack
description: Comprehensive Regression Testing 项目的 BGP 双 RR 设计 + IPv6 AF over v4 会话的 NH 坑
metadata: 
  node_type: memory
  type: project
  originSessionId: 26925966-39a5-4879-91ca-d19104aeba3a
  modified: 2026-08-15T16:38:10.228Z
---

Comprehensive Regression Testing 项目（20f40515-35b0-4a11-b15f-9552ba6e4715）在 ① 组 OSPF 之上加的 BGP 层（2026-08-16 部署）：

- **拓扑**：R3(f2/0)/R7(f3/0)/BGP-RR-1(eth0)/BGP-RR-2(eth0) 同接 Switch1；RR 两台另有 eth1 直连。AS 64501，双 RR 冗余，R3/R7 为 client（双上联），RR-1↔RR-2 互联，R3↔R7 不直建。
- **编址**：Switch1 段 10.254.254.0/24 + 2026:254:254::/64（R3=.3/::3、R7=.7/::7、RR-1=.101/::101、RR-2=.102/::102，用户指定复用旧骨干段）；RR 互联 10.254.253.0/30 + 2026:254:253::/64；BGP 测试环回 Lo100=10.99.N.N/32 + 2026:99::N/128（不进 OSPF，BGP 路由是唯一路径，验证干净）。该段不跑 OSPF。
- **关键坑：IPv6 AF 挂在 IPv4 会话上时，IOS 反射来的路由 NH 是 `::FFFF:10.254.254.3`（v4 映射地址），IOS 无法在 v6 RIB 解析 → 路由不最优不安装 → v6 ping 0%**。修复：**按 AF 分传输**——ipv4 AF 走 v4 邻居，ipv6 AF 走 v6 邻居（`neighbor 2026:254:254::101` 等），NH 变真实 v6 直连可解析。IOS 侧 `no neighbor <v4> activate`（af ipv6 下）时会打 "Neighbor deleted" 日志但邻居仍在（会话重建），且 IOS 自动在 af ipv4 给 v6 邻居写 `no activate`。
- RR 配置（FRR）：`neighbor X route-reflector-client` 在 address-family 下配；双 RR cluster-id 默认=各自 router-id（.101/.102 不同即可）。验证看 `Originator:` / `Cluster list:`、双路径、`show ip route` bgp 200。

**②组扩展（2026-08-16）**：IOU1-4 六链路物理 full-mesh OSPFv2/v3 area 0（10.2.AB.0/30 + 2026:2:AB::N/64，Lo0=10.2.N.N/32 + 2026:2:N::N/128），IOU3/IOU4 e0/3 接 Switch1 做 **eBGP** AS 64502→64501（.13/.14 + v6 ::13/::14，避开 R3=.3/R7=.7/RR=101/102），Lo100=10.2.99.N/32 + 2026:2:99::N/128 当测试路由。eBGP 同样按 AF 分传输。新坑：
- **FRR 10.x eBGP 默认 `ebgp-requires-policy`（RFC 8212）开**：会话 Established 但 PfxRcd=0，RR 侧必须 `no bgp ebgp-requires-policy`（iBGP 不受影响，①组当时没踩到）。
- **IOL 15.2 拒绝传统 `ipv6 router ospf 1`**（报 `Use "router ospfv3 1"`）；接口级 `ipv6 ospf 1 area 0` 仍被接受并自动建进程，router-id 用 `router ospfv3 1`+`address-family ipv6 unicast`+`router-id` 补。
- **复用的 IOU 节点带旧 startup-config，部分接口 administratively down**（IOU1 e0/2、IOU3/IOU4 e0/3 踩中）：配完 IP 必查 `show ip int brief`，对在用接口统一 `interface range Ethernet0/0 - 3` + `no shutdown`，否则邻居缺、BGP 口不起。
