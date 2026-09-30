# BGP-Attributes-Test 方案与实施记录

> 2026-09-16 建成并全验证。目的：研究 BGP 邻居建立、路由通告、以及选路属性
> （weight / local-pref / AS_PATH / MED / origin / community 等）的行为。
> 平台：GNS3 `Cisco IOU L3`（x86_64_crb_linux-adventerprisek9-ms.iol，IOS 15.x）。
> 项目：`BGP-Attributes-Test`，project_id `7d6fe78c-7379-452b-b72a-020098ea8773`。

---

## 1. 设计目标与拓扑选型

研究属性需要**同一前缀的多条并行路径**，所以选双归属菱形（dual-homed diamond）：
R1/R2（AS100，"本 AS"）双上联 R3（AS200）和 R4（AS300），R3/R4 双下联 R5
（AS400，前缀源）。R1/R2 之间一条 iBGP。

- R1/R2 对 172.16.x 有 **4 条路径**（2 出口 × 2 上游）：任何选路属性都能做出可见切换
- R5 对 AS100 前缀有 **2 条回程路径**：入向流量工程（prepend / community）的观察点
- iBGP R1↔R2 承载 next-hop / LP 传播 / MED 止步等"属性传递规则"实验
- 改 `neighbor remote-as` 即可把 R4 变成 AS200（不动拓扑）→ MED 同邻 AS 变体

```
                R5 (AS400)
               ╱          ╲        lo0 192.168.0.5/32
             eBGP          eBGP    lo1-4 172.16.1-4.1/24（前缀源）
             ╱              ╲
        R3 (AS200)        R4 (AS300)
          ╱    ╲            ╱    ╲
        eBGP    eBGP      eBGP    eBGP
        ╱        ╲        ╱        ╲
      R1 ──iBGP── R2      (AS100)
```

7 条 eBGP/iBGP 会话：R1×3（R3/R4/R2-iBGP）、R2×3、R3×3、R4×3、R5×2，唯一会话共 7 条。

## 2. 节点与链路

| 节点 | node_id | console | 位置 |
|---|---|---|---|
| R1 | `4e6e3d4e-8270-4195-a2e4-ad98c17aec00` | 5000 | (-150,150) |
| R2 | `98ff7b62-b347-485f-bbb4-111535000a5f` | 5001 | (150,150) |
| R3 | `9fa6d42a-9720-4cb4-83ad-084611ae5580` | 5003 | (-250,-100) |
| R4 | `df24105d-3c78-482c-abf6-f396ec9c935c` | 5004 | (250,-100) |
| R5 | `51208084-a77d-4d1b-8f28-95d3b04eb0c2` | 5002 | (0,-300) |

console 端口在节点重建后会变，以 node_list 为准。

| 链路 | R-A 口 | R-B 口 | 网段 | .1 侧 | .2 侧 |
|---|---|---|---|---|---|
| R1–R3 | R1 e0/0 | R3 e0/1 | 10.13.0.0/30 | R1 | R3 |
| R1–R4 | R1 e0/1 | R4 e0/1 | 10.14.0.0/30 | R1 | R4 |
| R1–R2 | R1 e0/2 | R2 e0/2 | 10.12.0.0/30 | R1 | R2（iBGP） |
| R2–R3 | R2 e0/0 | R3 e0/2 | 10.23.0.0/30 | R2 | R3 |
| R2–R4 | R2 e0/1 | R4 e0/2 | 10.24.0.0/30 | R2 | R4 |
| R3–R5 | R3 e0/0 | R5 e0/0 | 10.35.0.0/30 | R3 | R5 |
| R4–R5 | R4 e0/0 | R5 e0/1 | 10.45.0.0/30 | R4 | R5 |

编址规则：互联 `10.XY.0.0/30`（X、Y 为两台编号，小编号取 .1）；loopback0
`192.168.0.R/32`（RID / ping 源）；R5 业务网 `172.16.R.0/24`（loR，留 /16 做聚合实验）。

## 3. 基线配置

接口配置略（见上表，全部 no shutdown）。BGP 基线如下，每台都有
`no auto-summary` / `bgp log-neighbor-changes` / `timers bgp 10 30`（默认 60/180 太慢，实验不友好）。

**R1（AS100）**
```
router bgp 100
 no auto-summary
 bgp log-neighbor-changes
 timers bgp 10 30
 neighbor 10.13.0.2 remote-as 200
 neighbor 10.13.0.2 description eBGP_to_R3_AS200
 neighbor 10.14.0.2 remote-as 300
 neighbor 10.14.0.2 description eBGP_to_R4_AS300
 neighbor 10.12.0.2 remote-as 100
 neighbor 10.12.0.2 description iBGP_to_R2
 neighbor 10.12.0.2 next-hop-self
 network 192.168.0.1 mask 255.255.255.255
```

**R2（AS100）**：同构，eBGP 邻居 10.23.0.2(AS200)/10.24.0.2(AS300)，
iBGP 10.12.0.1 + next-hop-self，`network 192.168.0.2 mask /32`。

**R3（AS200）**
```
router bgp 200
 no auto-summary
 bgp log-neighbor-changes
 timers bgp 10 30
 neighbor 10.35.0.2 remote-as 400
 neighbor 10.13.0.1 remote-as 100
 neighbor 10.23.0.1 remote-as 100
 network 192.168.0.3 mask 255.255.255.255
```

**R4（AS300）**：同构（AS300，邻居 10.45.0.2/10.14.0.1/10.24.0.1，network 192.168.0.4/32）。

**R5（AS400）**
```
router bgp 400
 no auto-summary
 bgp log-neighbor-changes
 timers bgp 10 30
 neighbor 10.35.0.1 remote-as 200
 neighbor 10.45.0.1 remote-as 300
 network 172.16.1.0 mask 255.255.255.0
 network 172.16.2.0 mask 255.255.255.0
 network 172.16.3.0 mask 255.255.255.0
 network 172.16.4.0 mask 255.255.255.0
 network 192.168.0.5 mask 255.255.255.255
```

要点：
- **network 必须显式带 mask**（见 §5 坑 1）
- 所有 lo0 /32 进 BGP → 全网 RID 互相可达，ping 一律 `source lo0` 保证回程有路
- 互联 /30 **不进** BGP：直连源 ping 跨 AS 会因回程无路由失败（教学点）
- next-hop-self 配在 R1↔R2 iBGP 上：eBGP 学来的路由进 iBGP 不改 NH，
  R2 对 10.13.0.2 等远端 NH 无路由 → 不配则路由 valid 但不可达

## 4. 实施实录与验证结果

时间线：项目/节点/链路建立 → 接口配置 → 逐链路 ping 7/7 通（首包 ARP 丢 1 个属正常）
→ BGP 配置 → 会话全 Est → **发现 172.16.x 零通告（坑 1），修复** → 全验证
→ `write memory` ×5 → 停机打快照 `baseline-7sessions` → 重启复验（持久化 OK）。

### 会话（7/7 Established）

R1 稳态：
```
Neighbor        V    AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
10.12.0.2       4   100      11      12     10   0    0 00:00:55    8
10.13.0.2       4   200      13      13     10   0    0 00:00:54    6
10.14.0.2       4   300      13      13     10   0    0 00:00:58    6
```

### 多路径（R1 对 172.16.1.0/24，3 条路径）

```
Paths: (3 available, best #3, table default)
  300 400
    10.12.0.2 from 10.12.0.2 (192.168.0.2)      ← iBGP：R2 转述其最佳（经 R4），NH 已被 next-hop-self 改写
      Origin IGP, metric 0, localpref 100, valid, internal
  200 400
    10.13.0.2 from 10.13.0.2 (192.168.0.3)      ← eBGP 直连 R3
      Origin IGP, localpref 100, valid, external
  300 400
    10.14.0.2 from 10.14.0.2 (192.168.0.4)      ← eBGP 直连 R4（当前 best）
      Origin IGP, localpref 100, valid, external, best
```

### 基线"掷骰子"现象（重要教学素材）

R1 的 RIB（不配任何属性时）：
```
B    172.16.1.0 [20/0] via 10.14.0.2     ← 走 R4
B    172.16.2.0 [20/0] via 10.13.0.2     ← 走 R3
B    172.16.3.0 [20/0] via 10.13.0.2
B    172.16.4.0 [20/0] via 10.13.0.2
```
逐前缀 best 不一致！三条路径 AS_PATH 同长（2）、origin 同 I、无 MED、IGP 度量同 0，
决胜落到 **"最老 eBGP 路径"**（oldest path，保稳定性），而每条前缀的 UPDATE 到达先后是
毫秒级竞态 → 结果近似随机。这正是后续 weight/LP/MED 实验要"治"的对象：
一旦属性有差别，选路立刻确定且可解释。

### E2E（重启后复验）

```
R1# ping 172.16.1.1 source loopback0 repeat 3   → 100%
R2# ping 172.16.2.1 source loopback0 repeat 3   → 100%
R5# ping 192.168.0.1 source loopback0 repeat 3  → 100%
```

## 5. 坑实录（本次新增）

1. **`network 172.16.1.0` 不带 mask = 有类 /16 解释**：IOS 把裸 network 按类别掩码
   （172.16 → /16）处理，RIB 无 172.16.0.0/16 精确匹配 → 零起源，且无任何报错。
   必须写 `network 172.16.1.0 mask 255.255.255.0`。
2. **traceroute 被 MCP device_show_run 禁用**（超时保护），验证路径改用
   `show ip route` / `show ip bgp x.x.x.x` + 指定源 ping。
3. 直连源 ping 跨 AS 失败是**特性不是 bug**：回程对端无直连网段路由，一律 `source lo0`。
4. ping 自己的另一个 loopback（R5→172.16.1.1）是本机自环，不能当 E2E 证据。
5. do write memory 首次会对 NVRAM 版本差异弹 confirm，netmiko 自动应答，无害。

## 6. 实验菜单（基线之上逐个做，做完恢复）

统一观察点：`show ip bgp 172.16.1.0`（逐路径属性）、`show ip route bgp`、
`show ip bgp summary`。恢复方式：`no` 掉增量配置，或停机后
`snapshot_restore baseline-7sessions`（快照 id `f9645a5a-5268-48db-8e39-8712c05b2c38`）。

### A. 邻居建立与状态机

| # | 实验 | 做法 | 预期 |
|---|---|---|---|
| A1 | 状态机 | `debug ip bgp`（控制台），`clear ip bgp *` 或 link 挂起 | Idle→Connect→Active→OpenSent→OpenConfirm→Est 逐态可见 |
| A2 | MD5 错配 | R1: `neighbor 10.13.0.2 password cisco`，R3 不配 | TCP 反复重置，会话卡 Idle/Active，日志 Connection reset |
| A3 | AS 号错配 | R1: `neighbor 10.13.0.2 remote-as 999` | Open 交换后 NOTIFICATION(bad peer AS)，回 Idle |
| A4 | iBGP 换 lo0 对等 | 双方 `neighbor 192.168.0.x remote-as 100` + `update-source Lo0` + 互指 /32 静态（BGP 自带路由亦可） | 会话重建；对比直连对等的差异 |
| A5 | eBGP multihop | R1↔R3 改 lo0 对等 + `ebgp-multihop 2` | 默认 TTL=1 不够，需显式放开 |
| A6 | 定时器 | `show ip bgp neighbor 10.13.0.2 | i timer`；两侧配不同 timers | 取双方较小值协商；link suspend 观察收敛节奏 |

### B. 通告与 next-hop

| # | 实验 | 做法 | 预期 |
|---|---|---|---|
| B1 | next-hop 黑洞 | 删 R1/R2 的 `neighbor ... next-hop-self` | 对侧 iBGP 路由 valid 但 NH 不可达（inaccessible），RIB 不装 |
| B2 | redistribute | R5: `redistribute connected route-map ONLY-172`（match lo1-4） | 前缀 origin 变 `?`（incomplete），与 network 起源 `i` 对比选路影响 |
| B3 | 阶段2 水平分割 | 加 R6 进 AS100，iBGP 全互联 R1/R2/R6 | R1 从 R2 学的 iBGP 路由不再转给 R6 → 需要 RR 或全互联 |

### C. 选路属性（核心，按 IOS 13 步顺序逐个叠加）

| # | 属性 | 做法 | 预期观察 |
|---|---|---|---|
| C1 | weight（Cisco 私有） | R1: `neighbor 10.13.0.2 weight 200` | R1 全部 172.16.x 立即切 R3；**只影响 R1 本机**，R2 不变 |
| C2 | local-pref | R1: `neighbor 10.13.0.2 route-map LP in` + `set local-preference 200` | AS100 整体统一走 R3（R2 的 best 也变）；LP 不出 AS |
| C3 | AS_PATH prepend | R5: `neighbor 10.35.0.1 route-map PRE out` + `set as-path prepend 1 1 1` | AS100 全部改走 R4（路径长度 2 vs 5）；反向 prepend 影响回程 |
| C4 | MED 变体 | 见下 | 同邻 AS 才比 MED |
| C5 | origin | route-map `set origin incomplete` | IGP(i) < EGP(e) < incomplete(?)，同长 AS_PATH 下决胜 |
| C6 | 汇总验证 | C1–C5 逐个叠加/删除 | 每步 `show ip bgp 172.16.1.0` 对照 13 步表 |

**C4 变体（MED 同邻 AS）**：默认 R1 从 AS200 和 AS300 各收一路，**MED 不参与比较**
（不同邻居 AS）。变体把 R4 改成 AS200：
```
R4: no router bgp 300 → router bgp 200（重建三个 neighbor，同 R3 模板）
R1: neighbor 10.14.0.2 remote-as 200   （替换 300）
R2: neighbor 10.24.0.2 remote-as 200
R5: neighbor 10.45.0.1 remote-as 200
R5: neighbor 10.35.0.1 route-map MED-LOW out （set metric 50）
R5: neighbor 10.45.0.1 route-map MED-HIGH out（set metric 150）
```
→ AS100 两侧同邻 AS 200，MED 生效统一走 R3；再加 `bgp always-compare-med` 对照。

### D. community

| # | 实验 | 做法 | 预期 |
|---|---|---|---|
| D1 | 默认不传 | R5: route-map `set community 400:100` | R1 `show ip bgp 172.16.1.0` 看不到 community |
| D2 | send-community | R5 侧 neighbor `send-community` | 逐跳都要配；漏一跳断一跳 |
| D3 | NO_EXPORT | R5: `set community no-export` | AS100 内 iBGP 仍传（R2 能见），但 R1/R2 不再传给 R3/R4 |
| D4 | NO_ADVERTISE | R5: `set community no-advertise` | 收到者（R3/R4）不传给任何 peer，R1/R2 根本收不到 |
| D5 | 按社区过滤 | R1: `ip community-list 1 permit 400:100` + route-map deny | 策略路由式按标处理 |

### E. 过滤

| # | 实验 | 做法 | 预期 |
|---|---|---|---|
| E1 | prefix-list | R5: `neighbor 10.35.0.1 prefix-list OUT in`? 方向注意——在 R1 入向 `distribute-list prefix IN-ONLY in` 只收 172.16.1-2 | R1 表里 .3/.4 消失 |
| E2 | as-path ACL | R1: `ip as-path access-list 1 deny _300_` + `neighbor 10.14.0.2 filter-list 1 in` | 拒掉经 AS300 的路径 |
| E3 | 出向过滤 | R5 对 R4 `prefix-list` out | R4→AS100 侧路由消失，AS100 只剩经 R3 的路径 |

### F. 聚合（R5）

| # | 实验 | 做法 | 预期 |
|---|---|---|---|
| F1 | summary-only | R5: `aggregate-address 172.16.0.0 255.255.0.0 summary-only` | AS100 只见 /16；`show ip bgp 172.16.0.0` 带 atomic-aggregate、AS_PATH 记 {400}? 末跳明细被抑制 |
| F2 | as-set | `aggregate-address ... as-set` | 聚合路径保留成员 AS_SET（community 也并集） |
| F3 | suppress-map | `aggregate-address ... suppress-map SUP` 只压 .3/.4 | 部分明细仍泄露 → 更细粒度控制 |

## 7. 观察命令速查

```
show ip bgp summary
show ip bgp 172.16.1.0              ! 逐路径属性（LP/MED/origin/community/best 原因）
show ip bgp                         ! 全表，*> 为 best、i 为 iBGP
show ip bgp regexp _400_            ! AS_PATH 正则过滤
show ip bgp neighbor 10.13.0.2 advertised-routes | routes
show ip bgp neighbor 10.13.0.2 | i timer|Last reset
show ip route bgp
clear ip bgp * soft                 ! 软重置（策略变更后 outbound）
```

## 9. 实验记录

### 9.1 C1 weight（09-16 实测）

基线（重启后竞态本轮统一落在 R4）：R1/R2 全部 172.16.x 分别经 10.14.0.2 / 10.24.0.2。

施加：R1 `neighbor 10.13.0.2 weight 200` + `clear ip bgp 10.13.0.2 soft in`（neighbor weight
改动需要 soft in 触发 route-refresh 才作用于已有路由）。

结果（~17s 收敛）：
- R1：4 条前缀全部切 10.13.0.2；`show ip bgp 172.16.1.0` 明细可见
  `Origin IGP, localpref 100, weight 200, valid, external, best`
- R2：完全不变（仍走 R4）——**weight 不进 UPDATE 报文，纯本地**，13 步第 1 位

结论：weight 是"只管自己"的旋钮，适合单点引导，无法做 AS 级策略。

### 9.2 C2 local-pref（09-16 实测）

施加：R1 `route-map LP-IN`（`set local-preference 200`）挂在 `neighbor 10.13.0.2 ... in` + soft in。

结果：
- R1 4 条全切 R3；`show ip bgp neighbor 10.12.0.2 advertised-routes` 可见 LP 列 = 200（随 iBGP 通告）
- R2：4 条全变 **`[200/0] via 10.12.0.1`** —— AD 200 = iBGP！R2 放弃自己直连 R4 的 eBGP
  （AD 20）改绕行 R1。**LP（第 2 步）压过 eBGP>iBGP（第 7 步）**，且 LP 在 AS 内 iBGP 全程
  传播、出 eBGP 即剥离（R3/R5 视角无 LP）

坑：第一次抓 R2 路由表比 BGP 更新早 1–2 秒，看到"R2 没跟随"的假象；BGP 表里
`localpref 200, valid, internal, best` 已经就位。**快照时序疑点先重查再下结论**。

结论：LP 是"AS 级出口策略"的标准旋钮——一处入向设置，全网出口统一。

### 9.3 C3 AS_PATH prepend（09-16 实测，含意外收获）

施加：R5 `route-map PRE-TO-R3`（`set as-path prepend ...`）挂 `neighbor 10.35.0.1 ... out` + soft out。

**发现 1（语法）**：`set as-path prepend 1 1 1` 的 `1` 被本版本 IOS 按**字面 AS 号 1**处理
（R1 视角 `200 400 1 1 1`），没有"自身 AS 占位符"语义。正式写法 `set as-path prepend 400 400 400`。
对选路无影响（只比长度），但会污染 AS_PATH 内容（as-path ACL `_1_` 会误匹配）。

**发现 2（选路确定化）**：prepend 后 AS100 全部 4 条统一走 R4——AS_PATH 长度（第 4 步）
首次产生差异，"掷骰子"消失。

**发现 3（过度 prepend 的反噬，本实验最大收获）**：prepend 3 次后稳态不是"AS100 走 R4"这么简单，
而是一级级级联：

1. R5→R3 路径长度变 4，R3 的 best 翻转成**回旋路径** `100 300 400` via R1（长度 3）
2. R3 对 R1/R2 只会转售这条含 AS100 的路径 → **被环检测拒收** → AS100 里 via-R3 路径
   整体消失（R1 从 3 路径变 2 路径，表版本都不动=纯撤离）
3. 数据面：R3 自己去 172.16.x 的流量走 R3→R1→R4→R5 大绕行（无环，但严重不对称）

教训：prepend 1–2 次是引导，3 次以上开始扭曲**上游自己的选路**——你把路拉长到连
中转 AS 都嫌弃，它会转头把流量绕回来。真实运营 prepend 过度的经典事故形态。

（注：`1 1 1` 与 `400 400 400` 在 R3 视角长度同为 4，稳态相同；中间快照恰好抓在级联完成前。）

恢复：撤 route-map + soft out，R1 回 3 路径、best 回 R4，E2E 100%。

### 9.4 13 步选路原则全系列实测（09-16，第 1/2 步见 §9.1/9.2）

统一观察点：R1 `show ip bgp 172.16.1.0`。每步施加→观察→还原，NVRAM 全程未动。

| 步骤 | 原则 | 实验 | 实测结果 |
|---|---|---|---|
| 3 | 本地起源优先 | R1 `ip route 172.16.1.0 ... Null0` + `network` | 路径变 `Local / 0.0.0.0 ... weight 32768, sourced, local, best`；**副作用见下"引流黑洞"** |
| 4 | AS_PATH 最短 | R5→R4 `set as-path prepend 400`（1 次） | `200 400`(长2) 胜 `300 400 400`(长3)，AS100 全网统一走 R3，确定化 |
| 5 | Origin 最低（i<e<?） | R5→R4 `set origin incomplete` | via-R4 变 `Origin incomplete`，best 稳落 IGP 侧 R3 |
| 6 | MED 最低 | R3→AS100 `set metric 100`、R4→AS500 | **默认：MED 100 输给 MED 500，best 钉在 500 侧**（不同邻居 AS 不比）；R1 `bgp always-compare-med` 一开立即翻 100 侧 |
| 7 | eBGP 优于 iBGP | R1 `neighbor 10.13.0.2/10.14.0.2 shutdown` | 仅剩 iBGP 上位（`valid, internal, best` + Not advertised to any peer）；R1 经 R2 转发 ping 100%；unshut 回 eBGP |
| 8 | 到 NH 的 IGP 度量最低 | 取证 | `10.12.0.0/30 is directly connected`——全部 NH 直连 metric 0，**本拓扑恒平局**；要区分需引入 IGP（如 lo0 对等+OSPF 开销） |
| 9 | 最老 eBGP 路径 | R1 `clear ip bgp 10.13.0.2`（硬复位） | best 翻向幸存的 R4（RFC 5004 稳定性偏好）；**soft in 不重置路径年龄，硬复位才重置** |
| 10 | RID 最低 | R1 `bgp bestpath compare-routerid` | 跳过 oldest，best 从 R4 翻 R3（.3<.4）；再把 R4 RID 改 192.168.0.2 又翻回 R4——RID 双向验证 |
| 11 | cluster-list 最短 | 理论 | RR 环境专属（ORIGINATOR_ID/CLUSTER_LIST 防 RR 环），阶段 2 加 R6 实测 |
| 12 | originator-id 最低 | 理论 | 同上，RR 专属 |
| 13 | 邻居地址最低 | R3、R4 RID 同设 192.168.0.2 制造第 10 步平局 | 两路径 RID 相等→11/12 对 eBGP 不适用→best 落 **10.13.0.2（更低邻居 IP）** |

### 9.5 13 步系列的附加发现

1. **MED 是 optional non-transitive 属性**：R5 发给 R4 的 MED 在 R4 转售给 AS100 时被丢弃
   （R1 的 via-R4 路径上看不到 metric）。要让 AS100 看到 MED，必须由 R3/R4 自己向 AS100 出向设置。
   这就是"上游向双归属客户发 MED"的标准姿势。
2. **引流黑洞（S3 副作用）**：R1 用 Null0 起源 172.16.1.0 后，R2 追着空 AS_PATH（长 0）的
   iBGP 路径把流量送到 R1 掉进 Null0（ping `UU` 0%）。起源别人的前缀=凭空造出"最优"路径吸引流量。
3. **oldest-path 的年龄语义**：route-refresh（soft in）刷新的内容不重置路径年龄（刷新后 best 不变），
   硬复位会话才重置——排障时判断"为什么还是走老路"要用这个区别。
4. 验证方法学：MED/oldest/RID 实验互相纠缠（改一处会刷新年龄），干净证明要用**对冲设计**
   （给当前 best 更差的属性值，看它是否仍获胜=证明该属性被无视）。

## 10. 重建 checklist

1. `project_create BGP-Attributes-Test`；IOU L3 模板 `12678fbc-8d34-444a-b533-40d9de97a1aa` 批量建 R1–R5（命名偏离默认名惯例，本实验必需；批量创建已串行化无竞态）
2. `link_create` 7 条（端口分配见 §2，全部 adapter 0）
3. `node_start` → 等 ~25s → 接口/loopback 配置（≤2 台/批，尾部 do write memory）
4. 逐链路 ping 验证 → BGP 基线（§3，network 必须带 mask！）
5. 验证：7/7 Est → R1 三路径 → lo0 源 ping E2E
6. 快照：node_stop_all → `snapshot_create baseline-7sessions` → start → 复验
