# BGP-Bestpath-13Rules-FFR 实验方案与菜单

BGP 13 条选路原则实验场。项目 `BGP-Bestpath-13Rules-FRR`（9 节点 = 7×FRRDocker + 2×Ubuntu Guest，13 链，IPv4），建成 2026-11-21，快照 `baseline-bgp13-clean`。

## 1. 设计

一个前缀、五条候选路径、一台裁决路由器。测试前缀 `100.100.100.0/24`（H2 所在网段，R3 `network` 起源）从 5 条路径进入 R1（AS 100）：

| 路径 | 类型 | 途经 | AS_PATH | 下一跳 |
|------|------|------|---------|--------|
| P1 | eBGP | R1←R3 直连 | 200 | 10.0.13.3 |
| P2 | eBGP | R1←R4 直连（R4 经 AS200 iBGP 学自 R3） | 200 | 10.0.14.4 |
| P3 | eBGP | R1←R5 直连（R5 学自 R3） | 300 200 | 10.0.15.5 |
| P4 | iBGP | R1←R2（R2 学自 R3，next-hop-self） | 200 | 2.2.2.2 |
| P5 | iBGP | R1←R6（R6 学自 R4，next-hop-self） | 200 | 6.6.6.6 |

每条规则实验 = `neighbor shutdown` 只留两条候选 + 在指定位置改一个属性 → R1 看谁胜出。单变量、可回滚。

- **AS 100**（R1/R2/R6/R7）：OSPF area 0（R1–R2 / R1–R6 / R2–R6 / R6–R7）+ iBGP lo 对等。R7 平时只挂 R6 的 iBGP（RR 阶段才起源 100.100.200.0/24）
- **AS 200**（R3/R4）：源侧。R3=源A（network 起源），R4=源B；**同邻 AS 配对**是规则 6/10/11/13 的对照组
- **AS 300**（R5）：转接，制造 2 段 AS_PATH
- R1 将 10.0.101.0/24（H1 网段）network 进 BGP 供回程

## 2. 实施记录（2026-11-21）

- 9 节点 / 13 链一次建成；画布标注：3 个 AS 矩形 + 26 个链路两端地址标注 + 角色标签 + 信息块/路径表，坐标由 `labs/bgp13_layout.py`（复用 `gns3_label_layout` 引擎）解算，audit 0 违例 / 0 无解 / 0 越界
- 美化后处理（同日，坐标零改动）：AS 矩形上淡色底（红 0.07 / 蓝 0.05，圆角 10）；信息块与路径表垫白色卡片（88% + 浅灰蓝描边）；三个 AS 标题垫实色芯片、文字改白加粗——全部为 svg 样式更新或新增 z=0 底板，重算布局时脚本无需感知
- 配置三段式推送（console 直落 vtysh，尾部 `write memory`）：接口 → OSPF → BGP，全部无报错
- **基线验证全绿**：
  - OSPF area 0：R1: 2/2 Full、R6: 3/3 Full（R1/R2/R7）
  - R1 BGP 5/5 会话 Est（2 iBGP + 3 eBGP），FRR 10.3
  - `show bgp ipv4 unicast 100.100.100.0/24` = **Paths: (5 available, best #1)**，best = P1（10.0.13.3），iBGP 路径 localpref 100 / metric 10，P3（300 200）垫底
  - 数据面：H1 ping H2 0% loss ttl=62；traceroute = H1→10.0.101.1(R1)→**10.0.13.3(R3)**→H2，精确跟随 best 路径 P1
- 快照后重启复验：BGP 5 会话自动重建、五路径依旧、H1/H2 地址由 /etc/network/interfaces 开机自动加载（该镜像 ifup 可用）——**重启零人工恢复**

## 3. FRR 10.3 与 Cisco 13 条对照

| # | Cisco 规则 | FRR 10.3 | 备注 |
|---|-----------|----------|------|
| 1 | Weight 最高 | ✅ `neighbor X weight` / route-map `set weight` | 本地入向属性，不传播 |
| 2 | LOCAL_PREF 最高 | ✅ | iBGP 传播；eBGP 不传 |
| 3 | 本地起源优先 | ✅ network/aggregate/redistribute | weight 在它之前 |
| 4 | AS_PATH 最短 | ✅ | `as-path prepend` |
| 5 | Origin 最低 (i<e<?) | ✅ | network=i, redistribute=?, `set origin` 可改 |
| 6 | MED 最低 | ✅ 默认仅同邻 AS 比 | `bgp always-compare-med` 跨邻比；`bgp deterministic-med`；missing MED 默认当 0 |
| 7 | eBGP > iBGP | ✅ | 在 IGP metric 之前 |
| 8 | 到 NH 的 IGP metric 最低 | ✅ | `ip ospf cost` 调 |
| 9 | Multipath | 需显式 `maximum-paths` (+`bgp bestpath as-path multipath-relax` 跨 AS) | IOU 已有专场 |
| 10 | 最老 eBGP | ✅ 默认行为 | `bgp bestpath compare-routerid` 跳过直达 11 |
| 11 | Router-ID 最低 | ✅ | RR 场景 Originator-ID 代行 |
| 12 | Cluster-list 最短 | ✅ | 需 RR 拓扑（R7/R6/R2 层级） |
| 13 | 邻居地址最低 | 待实测 | FRR 文档顺序的最后一层，实测确认 |

前置类：有效下一跳（iBGP 不配 next-hop-self 时 NH 悬空=路径不可用）、AS 环路检测、FRR 默认 `ebgp-requires-policy`（本实验全部 `no bgp ebgp-requires-policy`）。

## 4. 实验菜单

> 通用姿势：改配置 → `clear bgp ipv4 * soft` 或等 ~5s → R1 `show bgp ipv4 unicast 100.100.100.0/24` 看 `>`；数据面 H1 `traceroute -n 100.100.100.2`。每条实验后**先回滚再做下一条**，回滚后核对 best 回到 P1。

### 测试00 基线（已完成）
全路径开放。best = P1。traceroute 走 R1→R3。

### 测试01 Weight 最高
- 配置（R1）：`router bgp 100` + `neighbor 10.0.14.4 weight 100` → **P2 胜**（压过先前的 best P1）
- 加码：改 `neighbor 10.0.15.5 weight 200` → **P3 胜**（AS_PATH 最长也照赢——weight 压一切）
- 验证：R1 show bgp best 变 10.0.14.4 → 10.0.15.5；H1 traceroute 翻 R4 → R5
- 回滚：`no neighbor X weight`

### 测试02 LOCAL_PREF 最高
- A（本机入向）：R1 route-map LP-IN `set local-preference 200`，`neighbor 10.0.14.4 route-map LP-IN in` → **P2 胜**
- B（教学点：LP 传播 + 顺序在 eBGP/iBGP 之前）：R2 上 `neighbor 10.0.23.3 route-map LP-IN in` set LP 500 → **P4（iBGP）压过 P1/P2（eBGP）**
- 回滚：no route-map in + `clear bgp ipv4 * soft`

### 测试03 本地起源优先
- 配置（R1）：`ip route 100.100.100.0/24 Null0`；`router bgp 100; address-family ipv4 unicast; network 100.100.100.0/24`
- 预期：**R1 本地路径全胜**（originator 局部路径 0.0.0.0）
- 回滚：`no network` + `no ip route`

### 测试04 AS_PATH 最短
- 现状即对照：P1（1 段）恒胜 P3（2 段）
- 配置（R3，出向对 R1）：route-map PREPEND `set as-path prepend 200 200 200`，`neighbor 10.0.13.1 route-map PREPEND out` → P1 变 4 段 → **P3 反超**，traceroute 翻 R5
- 回滚：no route-map out + clear soft

### 测试05 Origin 最低（i < e < ?）
- 隔离：R1 shutdown 对 R4/R5 的 neighbor → 只剩 P1(i) vs P4(i)…不对，先留 P1/P2：R1 shutdown 对 R5 + R2/R6 shutdown 对源侧 eBGP
- 配置（R4 侧制造 incomplete）：`ip route 100.100.100.0/24 Null0` + `redistribute static route-map ORI-OUT`（route-map `set origin incomplete`；R4 需先撤 R3→R4 的传递才有本地起源版本，或直接对 R4 出向 route-map `set origin incomplete`）
- 预期：**P1（i）胜**；再 `set origin egp` 玩中间档
- 回滚：no redistribute / no route-map out

### 测试06 MED 最低
- 同邻 AS（默认可比）：R3 出向 `set metric 100`、R4 出向 `set metric 50` → **P2 胜**
- 跨邻 AS（默认不比）：P1 vs P3 各 set metric，R1 加 `bgp always-compare-med` 后才生效
- 附注：`bgp deterministic-med` 对多路径比较顺序的影响；缺 MED 按 0（最好）
- 回滚：no route-map / no bgp always-compare-med

### 测试07 eBGP > iBGP
- 隔离：R1 `neighbor 10.0.14.4 shutdown` + `neighbor 10.0.15.5 shutdown`；R6 `neighbor 10.0.64.4 shutdown` → 剩 P1(eBGP) vs P4(iBGP)
- 预期：**P1 胜**；即便把 R1→2.2.2.2 的 IGP cost 调到 1（下一规则的手段）也不看——顺序在前
- 回滚：两处 no shutdown

### 测试08 到下一跳的 IGP metric 最低
- 隔离：R1 对三个 eBGP neighbor 全 shutdown → 剩 P4 vs P5（都 iBGP、NH=2.2.2.2/6.6.6.6）
- 配置（R1）：`interface eth3; ip ospf cost 10` + `interface eth4; ip ospf cost 100` → **P4 胜**（show bgp 中 P4 metric 10 < P5 metric 100+10）；对调 → **P5 胜**
- 回滚：`no ip ospf cost`（两接口）+ 恢复 eBGP neighbor
- 注：P5 的 metric = 10(eth4 直连 R6 的链路 cost 改变后…… R1 到 6.6.6.6 走 eth4 直连，cost=eth4 新值)——改 cost 后注意看 `show ip route 6.6.6.6` 确认路径与 cost 符合预期

### 测试09 Multipath（演示级）
- 配置（R1，保持 P4/P5 隔离态）：`address-family ipv4 unicast; maximum-paths 2` → **P4+P5 同装**（FRR 标 multipath）；`bgp bestpath as-path multipath-relax` 可放宽跨 AS 等价
- 数据面：H1 traceroute 见 ECMP 双第一跳（或连续 trace 轮换）
- 回滚：`no maximum-paths`

### 测试10 最老 eBGP 路径
- 隔离：测试07 的隔离态再留 P1/P2（R1 shutdown 对 R5，R2/R6 shutdown 对源侧）→ 属性全等，best = **先建立者**
- 操作：R1 `neighbor 10.0.13.3 shutdown` → `no neighbor 10.0.13.3 shutdown` → P1 重置为"新" → **P2 胜**
- 注：soft clear 不重置路径年龄，需邻居级硬重置
- 回滚：无残留

### 测试11 Router-ID 最低
- 前置：R1 `bgp bestpath compare-routerid`（跳过规则 10）
- 现状：R3 RID 3.3.3.3 < R4 4.4.4.4 → **P1 胜**；R3 改 `bgp router-id 9.9.9.9` + `clear bgp ipv4 *` → **P2 胜**
- RR 场景附注：反射路径用 Originator-ID 代行比较
- 回滚：`no bgp bestpath compare-routerid` + R3 RID 复原

### 测试12 Cluster-list 最短（RR 阶段，前缀 100.100.200.0/24）
- 配置：
  - R7：`ip route 100.100.200.0/24 Null0` + `network 100.100.200.0/24`
  - R6（RR-2，cluster 6.6.6.6）：`bgp cluster-id 6.6.6.6`；`neighbor 7.7.7.7 route-reflector-client`；`neighbor 1.1.1.1 route-reflector-client`
  - R2（RR-1，cluster 2.2.2.2）：`bgp cluster-id 2.2.2.2`；`neighbor 6.6.6.6 route-reflector-client`；`neighbor 1.1.1.1 route-reflector-client`
- 路径：R1 收两条——经 R6 反射（cluster-list len 1）vs 经 R2 级联反射（len 2）→ **短者胜**
- 验证：`show bgp ipv4 unicast 100.100.200.0/24` 逐路径比较 cluster-list；best = 经 R6
- 回滚：no route-reflector-client ×4（恢复基线 plain iBGP）

### 测试13 邻居地址最低（待实测确认 FRR 行为）
- 前置：测试11 态 + R3/R4 配**相同** RID（都 `bgp router-id 9.9.9.9`）+ compare-routerid → 平到最后一层
- 预期（Cisco 口径）：邻居 IP 低者胜，10.0.13.3 < 10.0.14.4 → **P1 胜**
- FRR 实际行为以实测为准（可能直接按 peer 地址或稳定 ID 处理），结果记回本文档
- 回滚：RID 双双复原

## 5. 已知坑（本实验场）

- FRR 默认 `ebgp-requires-policy`：不关掉 eBGP 零收发（全部已配 `no bgp ebgp-requires-policy`）
- iBGP 用 lo 对等必须 `update-source lo`；FRR 环回名是 `lo`
- R2/R6 对 R1 不配 `next-hop-self` → P4/P5 NH 悬空路径不可用（可作"有效下一跳"教学点）
- 规则 10 的路径年龄：soft clear 不重置，需 `neighbor shutdown`/`no shutdown` 或 `clear bgp` 硬重置
- MED 默认只比同邻 AS——R3/R4 同 AS 200 的设计正是为此
- vtysh `ping` 不自停（`-c` 可停）、console 会话状态跨连接保留（改配置前先 `end` 兜底）
- H1/H2（gns3/ubuntu:resolute）：bash + iproute2，`/etc/network/interfaces` 开机自动生效（实测）；node_file_write 对 docker 不可用，持久化走 console printf 重定向
- 画布标注重算：`python3 labs/bgp13_layout.py`（改 NODES/LINKS 后跑，audit 全净再落图；改画布前先读当前坐标）
