# DC-Test：XRd Spine-Leaf Fabric 方案与实施记录（2026-09-12）

## 概述

在 GNS3 项目 **DC-Test**（`c8f3efe2-1c1d-42cf-aad3-9460fcb5ccb4`）用 6 台 Cisco XRd Control Plane（IOS XR 24.4.1，docker 模板，4GB/台）搭建 2-Spine + 4-Leaf Clos Fabric。

- **Underlay（完成）**：eBGP（RFC 7938 BGP-only 风格），Spine 共用 AS 65000，Leaf 各持 AS 65001–65004，/31 点对点编址，全网 lo0 互通，ping 矩阵 100%。
- **Overlay（验证门判定：不可行，降级）**：原计划 eBGP EVPN + VXLAN。实测定 **XRd control-plane 镜像没有 NVE/VXLAN 子系统**（`show nve` 命令不存在、`interface nve1` 无法创建、EVPN VNI 恒 unresolved、BGP EVPN 表恒空），遂降级为 **routed tenant**：租户网段直接进 BGP，两台 VPCS 主机经 Fabric 跨网段 E2E 互通（实测通，TTL=61 三跳）。
- **故障演练（完成）**：挂起 Spine-1 全部 4 条下联 → 收敛 ≈168s（BGP hold timer 主导）→ 业务切 Spine-2 恢复 → 链路恢复后双平面回归。

## 拓扑与编址

```
Spine-1 (10.0.0.1/32, AS65000)      Spine-2 (10.0.0.2/32, AS65000)
   Gi0/0/0/0-3 ──────┐  ┌────── Gi0/0/0/0-3
                     │  │
   ┌───────┬───────┬─┴──┴────┬────────┐
Leaf-1   Leaf-2   Leaf-3    Leaf-4     (各自 Gi0/0/0/0 上联 Spine-1、Gi0/0/0/1 上联 Spine-2)
10.0.1.1 10.0.1.2 10.0.1.3  10.0.1.4   (Loopback0)
AS65001  AS65002  AS65003   AS65004
                  Gi0/0/0/2  Gi0/0/0/2 ← L3 主机口
                  172.16.10.1/24  172.16.20.1/24
                  Host-1(172.16.10.11)  Host-2(172.16.20.12)  (VPCS)
```

- 链路点对点：`10.<S>.<L>.0/31`（S=Spine 编号，L=Leaf 编号；spine 端 .0，leaf 端 .1）
- 租户网段：Leaf-3 侧 172.16.10.0/24、Leaf-4 侧 172.16.20.0/24，均 `network` 进各自 BGP
- 全网每台设备：`route-policy PASS / pass / end-policy`，所有 eBGP 邻居双向挂 PASS（XR 默认无策略邻居不收发路由）

## 实施时间线（全部经 MCP 工具完成）

| 阶段 | 内容 | 结果 |
|---|---|---|
| Phase 0 | 批量建 8 节点（6 XRd + 2 VPCS）、10 链路、批量启动 | 遇项目 auto_close 假 opened（project_open 解决，已改 auto_close=false）|
| Phase 1 | 6 台推 lo0 + /31 + eBGP + PASS 策略 | 8 条会话全 Est；lo0 ping 矩阵 100%（含跨 spine leaf↔leaf）|
| Phase 2 | Overlay 尝试 → 验证门失败 → routed tenant 降级 | 详见下节；最终 Host-1↔Host-2 E2E 5/5 |
| Phase 3 | 全网验证 + 断 Spine-1 演练 + 文档 | 收敛 ≈168s；恢复后双平面回归 |

## 关键发现与坑（XRd / IOS XR 24.4.1）

1. **XRd control-plane 无 NVE/VXLAN**（本次最大发现，证据链）：
   - `show nve interface` → Invalid input（整棵 NVE show 子树不存在）
   - `(config)# interface nve1` → Invalid input（配置不进去）
   - `l2vpn bridge-domain` 里 VNI 10000 恒 `unresolved`、EVPN 实例 `unresolved`
   - `show bgp l2vpn evpn` 恒空表（无路由可起源）
   - 结论：该镜像定位是控制面实验（BGP/OSPF/SR/NETCONF），VXLAN 数据面与 EVPN 路由起源均不可用。要做 EVPN-VXLAN 需换 FRR / SR Linux / XRd platform 版镜像。
2. **XR 单 BGP 进程单 AS**：原计划「underlay eBGP 各 AS + overlay iBGP 65500」在一台设备上无法实现，改为 eBGP EVPN 模型（EVPN riding 现有 eBGP 会话 + spine 侧 `next-hop-unchanged`）。`next-hop-unchanged` 在 24.4.1 直连 eBGP 上可用。
3. **l2vpn evpn AF 需先在进程级初始化**：直接给邻居挂 `address-family l2vpn evpn` 会报 `The address family has not been initialized` 并整批原子回滚。顺序：`router bgp N → address-family l2vpn evpn →（重进 router bgp）→ neighbor ...`。
4. **eBGP 邻居默认无策略=不收不发**：summary 里邻居标 `0!`，`network` 语句无效。必须 route-policy 双向挂。
5. **EVPN VNI/EVI 语法漂移**：老版 `vni <id> → evpn → route-target import/export` 语法在 24.4 被拒（`route-target both/import/export` 均无效）；`evpn → evi N → vni N` + `advertise-mac` 可接受，但受限于坑 1 无实际产出。`l2transport` 口必须显式 `no shutdown`（默认 admin-down，BD 里 AC 显示 down 的元凶）。
6. **l2transport→L3 残留会打死端口 RX**：Leaf-3 的 Gi0/0/0/2 经历 l2transport 实验（BD/MSTi）后改回 L3，接口 Up/Up 但 ARP 只出不出（accounting：12 out / 0 in），主机侧完全不通。接口 bounce、链路删除重建、主机重启均无效，**node_stop→node_start（配置经 /xr-storage 完整保留）后恢复**。排障利器：`show interfaces <if> accounting` 对比收发计数。
7. **link suspend 不产生载波信号**：uBridge 挂起后 XR 接口仍 up，BGP 会话保持 Est 直到 hold timer（默认 180s）超时，期间流量黑洞。收敛实测 ≈168s。生产对应：上 BFD 或依赖更激进的 keepalive。
8. 其他小坑：XR 管道不支持 `| include a|b` 交替正则（拆多条跑）；`show l2vpn bridge-domain <name> detail` 不带名字直接 `show l2vpn bridge-domain`；MCP device_show_run 的 Jinja2 模板模式不带 vars 不渲染命令（直接用 commands 列表）。

## 最终状态与验收

- 8 条 eBGP（ipv4 unicast）全 Established；每 Leaf 5 前缀（2 spine lo0 + 3 远端 lo0 + 对端租户 /24）
- l2vpn evpn AF 仍挂在各 eBGP 会话上（AF 协商成功、空表——保留作为验证门证据）
- Host-1(172.16.10.11) ↔ Host-2(172.16.20.12) 跨 Fabric 互通（Leaf-3↔Spine↔Leaf-4）
- 演练收敛/恢复数据见上；XRd 配置已 commit 持久化（Leaf-3 重启实证），VPCS 已 save
- 未做 snapshot（需全停节点，不值得为一个快照拆 Fabric）
- Spine 上遗留的 EVPN/EVI 试验配置已从 Leaf-3 清除；Leaf-1/2 保持纯 underlay

## 后续方向

- 收敛提速：underlay 邻居上 BFD（50ms×3）
- 要真正的 EVPN-VXLAN overlay：Leaf 换 FRRDocker/FRRDockerLite 或 SRLinux（本项目已有模板），Spine 可留 XRd
- 多租户扩展：Leaf-1/2 加 L3 主机口 + network 进 BGP 即可复用本 fabric
