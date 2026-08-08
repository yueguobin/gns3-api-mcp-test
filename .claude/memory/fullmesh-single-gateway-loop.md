---
name: fullmesh-single-gateway-loop
description: full-mesh 多节点用单网关上联时，网关不在某些网段会导致默认路由环路
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7729fc62-68f9-4e13-868d-c39a05902088
---

3 节点 full-mesh（A1-A2-A3，三个 /30 段），只用其中一台 A3 作网关上联骨干时，A3 只直连它自己的两条链路段，**不直连另外两节点之间的段**。

**Why:** 上例 A3 直连 10.4.13.0/30(到A1) 和 10.4.23.0/30(到A2)，但不直连 A1↔A2 的 10.4.12.0/30。骨干用静态路由 `10.4.0.0/16 → A3` 回程，去 10.4.12.x 的包到 A3 后，A3 路由表无 10.4.12.0/30 → 走默认路由(指骨干 R3) → R3 又按静态路由发回 A3 → TTL 环路，ping 100% 丢包。而 A3 直连侧(10.4.13.1/10.4.23.1)正常通——这种"部分通部分不通"就是该坑的特征。

**How to apply:**
- A3（网关）补明细路由覆盖它不直连的内部段：`ip route 10.4.12.0/30 via 10.4.13.1`（经 A1）或 via 10.4.23.1（经 A2）。
- 中间节点(被经过的 A1/A2)要 `sysctl net.ipv4.ip_forward=1` 才能转发；终点节点收给自己的包不需转发。
- 排查手段：从骨干 ping 网关直连侧(应通) vs 非直连侧(不通) 对比，即可定位是路由缺失而非 ip_forward/ARP 问题。
- 更彻底的替代方案：容器组内部跑 OSPF(FRR/BIRD)，而非手工明细路由。

参见 [[gns3-ws-console-usage]]（Docker 节点配置持久化写 /etc/network/interfaces）。
