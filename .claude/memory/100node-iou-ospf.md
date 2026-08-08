---
name: 100node-iou-ospf
description: 100-node-iou 项目 6×IOU L3 部分网状 OSPFv2/v3 单区部署、编址规则与接口映射
metadata: 
  node_type: memory
  type: project
  originSessionId: ee3ebd53-fd0a-4b8d-95a2-6f23d4a46007
  modified: 2026-08-07T15:36:50.172Z
---

100-node-iou（project_id `d82d5ee5-65c6-49fa-873f-bdb0790b393a`）：6 台 IOU L3（IOS 17.15.1，模板 `affef95e-aa9c-48e5-bf8f-497dd0fe3493`，名 R-1~R-6），**11 链路部分网状**（非完全 full-mesh 的 15 链路；每节点 3-5 邻居）。单 Area0，OSPFv2 + OSPFv3（AF 模式）双栈。

**编址规则（自行设计）**：
- Loopback0：`10.1.0.N/32` + `2026::N/128`（N=路由器号）。
- 点对点链路 R_A↔R_B：IPv4 `10.1.AB.0/30`、IPv6 `2026:AB::/64`，**小号路由器取 `.1`/`::1`**，大号取 `.2`/`::2`（AB=两端编号拼接，如 R1-R2→12）。

**接口↔链路映射**（由 link_list 推导，接口名 Ethernet0/x、新增的 R2-R5 用 Ethernet1/0）：
- R-1：e0/0↔R2(12,.1) · e0/1↔R4(14,.1) · e0/2↔R5(15,.1)
- R-2：e0/0↔R1(12,.2) · e0/1↔R3(23,.1) · e0/2↔R4(24,.1) · e0/3↔R6(26,.1) · e1/0↔R5(25,.1)
- R-3：e0/0↔R2(23,.2) · e0/1↔R6(36,.1) · e0/2↔R5(35,.1)
- R-4：e0/0↔R5(45,.1) · e0/1↔R1(14,.2) · e0/2↔R2(24,.2)
- R-5：e0/0↔R6(56,.1) · e0/1↔R4(45,.2) · e0/2↔R1(15,.2) · e0/3↔R3(35,.2) · e1/0↔R2(25,.2)
- R-6：e0/0↔R3(36,.2) · e0/1↔R5(56,.2) · e0/2↔R2(26,.2)

**OSPF 配置（每台相同模板）**：
- 全局 `ipv6 unicast-routing`
- 每个接口（含 Loopback0）：`ip address`/`ipv6 address` + `ip ospf 1 area 0` + `ospfv3 1 ipv6 area 0`
- **transit 接口额外**：`ip ospf network point-to-point` + `ospfv3 network point-to-point`（AF 模式下网络类型命令**无 pid 前缀**，已验证可接受）→ 立即 FULL、无 DR 选举、priority 显示 0
- `router ospf 1` / `router ospfv3 1` 各设 `router-id 10.1.0.N`（显式设置，避免被更高的 transit 接口 IP 如 10.1.14.1 抢占）
- IOS 17.15 OSPFv3 必须用 AF 模式，传统 `ipv6 router ospf`/`ipv6 ospf` 已弃用——见 [[mark-test-ipv6]]

**验证（2026-08-07）**：每协议 11/11 邻接全 `FULL/-`；R-2/R-5 各 5 邻居、其余各 3-4；R-1→R-6、R-3→R-4（非直连）loopback 双栈 ping source loopback0 全 100%；R-2↔R5 直连新链路 e1/0 双向 FULL；6 台 `do write memory` 已持久化。

**结构副本（带配置）**：项目现构成 **4×3 的 mesh 矩阵**（mesh0~11 共 12 组 × 6 节点 = 72 节点 / 132 链路）：mesh0=R-1~R-6 原配运行 OSPF；mesh1~11=R-7~R-72 为结构拷贝，与 R-1~R-6 同拓扑同端口映射、225px 网格（4 列×3 行，每 mesh 占 3 节点列×2 节点行），app_id/console 独立。`node_duplicate` **会连同 IOU nvram/startup-config 一起复制**，故每副本启动即带与源 R-N 相同的 IP（10.1.0.N/2026::N）、hostname（R-1~R-6）与 OSPF 配置——**多副本同时启动会 IP/router-id 重复冲突**；链路不复制，需 `link_create` 重建（已重建）。当前仅 R-1~R-6 运行，其余 stopped。要让副本独立成网需改 IP/hostname（如换 10.2.0.0/16 + 2027::）。

**工具坑**：`device_show_run` 对**同一设备发 2 个条目**时，两条会返回相同（通常是后一条）输出——验证时**每台设备只放 1 条命令**。`show ip route ospf | count` 在该 IOS 报 `% Incomplete command`（`| count` 不可用）。新增链路后接口默认 `no ip address / shutdown`，需配地址 + `no shutdown` 才会进入 OSPF。

**批量复制脚本**：`mcp-manual-test/replicate_mesh.py`（用 .venv/bin/python 跑；参数 --project/--source/--grid WxH/--place right|down|origin/--spacing/--dry-run；自动从 link_list 发现源 mesh 拓扑与 3×2 布局、碰撞检测、link_create 分块 ≤100/批；负坐标用 `--origin=X,Y` 等号形式）。**`.env` 的 GNS3_MCP_URL 是本机** `http://127.0.0.1:3080/v3/mcp/transport/sse`（192.168.1.3 是旧服务器地址，会连不上）。

**GNS3 dev5 新限制**：服务器升到 3.1.0.dev5 后，**`node_duplicate` 拒绝复制运行中的节点**（409 "Cannot duplicate node data while the node is running"；dev4 时代允许，所以早期复制成功）。复制前必须 stop 源节点（脚本已内置该检查）。2026-08-07 已用脚本在左侧复制 mesh12~15（R-73~R-96：左列 4 层 row0~3，x=-1830..-1380），项目共 **16 组 mesh，96 节点 / 176 链路**。

**⚠ 512 节点硬顶**：IOU 的 application_id 空间 1~512，**同一 compute 所有已打开项目的 IOU 节点总数 ≤512**（409 "Cannot create a new IOU node (limit of 512...)"）。10×10（600 节点）不可行。2026-08-07 最终建成 **85 组 mesh = 510 节点 / 935 链路**（帧 = origin(-1830,-555) 的 10×10，row0-7 满 10 列 + row8 前 5 列；中断批次残节点 R-511 已删）。脚本 `--repair-links` 可扫帧补缺失链路、报告残缺组（链路端点签名 sorted 需 `key=str`）。

相关：[[mark-test-ipv6]]（同环境 OSPFv3 AF 语法）、[[gns3-mcp-broken-tools]]（device_command_run 坏，用 device_config_send + do 前缀跑 write/ping）、[[gns3-mcp-double-envelope]]。
