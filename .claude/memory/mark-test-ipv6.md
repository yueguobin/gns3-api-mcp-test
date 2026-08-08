---
name: mark-test-ipv6
description: mark-test 项目 IPv6 (2026::/48) + OSPFv3 全网部署状态、编址规则与排错坑
metadata: 
  node_type: memory
  type: project
  originSessionId: 537818ed-7c45-494a-af21-04939f85efcd
  modified: 2026-08-07T14:30:24.100Z
---

mark-test（project_id `20f40515-35b0-4a11-b15f-9552ba6e4715`）已叠加 IPv6，前缀 `2026::/48`。

**编址规则**：`10.X.Y.Z → 2026:X:Y::Z`（Y 取 IPv4 第 3 段两位十进制作第 4 hextet）；骨干特例 `10.254.254.Z → 2026::Z`；loopback `/128`，链路 `/64`。

**区域 / 平台 / OSPFv3 语法**：
- 骨干 Area0（Switch1，2026::/64 broadcast）：R3=`2026::11`、IOU3=`::22`、IOSv3=`::33`、Ubuntu3=`::44`、FRR3=`::55`、R-3=`::66`、R4=`::77`
- Area1(7200 R1-3) / Area7(7200 R4-6) dynamips：传统 `ipv6 ospf 1 area X` + `ipv6 router ospf 1`
- Area2(IOU1-3) / Area6(R-1/2/3) IOU IOS17.15：AF 模式 `ospfv3 1 ipv6 area X` + `router ospfv3 1` → `address-family ipv6 unicast`
- Area3(IOSv1-3)：传统
- Area5(FRR1-3) FRR 8.2.2：`ipv6 ospf6 area X`（ospf6d 镜像默认已启用，**无需改 /etc/frr/daemons、无需重启**）
- Docker(Ubuntu1-3，10.4/2026:4) **无 OSPF**：Ubuntu3 作 IPv6 网关 static，骨干 ABR `ipv6 route 2026:4::/32` + redistribute static

**关键坑（IPv6 通用）**：
- **DAD `[DUP]` 是 sticky**：配置时与他地址撞 DAD 后，即使冲突方已改，本地仍标 DUP 不响应 NDP。必须 `no ipv6 address` + 重新 `ipv6 address` 才恢复（show ipv6 interface 看是否带 [DUP]）。
- **重置接口 global 地址会丢该接口 OSPFv3 关联**（`ipv6 ospf N area` 不在 show ipv6 ospf interface 输出），需重新 `ipv6 ospf 1 area X`。
- **区域汇总用 `/32` 不是 `/48`**：`2026:X::/48` 只覆盖第 3 段=0；区域网段是 `2026:X:12/23/31::`，要用 `2026:X::/32` 才覆盖。
- **FRR vtysh `show` 分页**会卡住后续命令，批量发命令前先确认回到 `frr#` 提示符（卡住时发 `q`）。

**持久化**：Cisco `do write memory`、FRR vtysh `write memory`、Ubuntu base64 追加 `/etc/network/interfaces` 的 `iface ethN inet6 static` 段。

相关：[[fullmesh-single-gateway-loop]]（Docker 单网关明细路由避环）、[[gns3-ws-console-usage]]（Linux 设备配置/改文件 base64）。
