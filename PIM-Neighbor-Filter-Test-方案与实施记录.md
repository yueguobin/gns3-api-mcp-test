# PIM Neighbor Filter Test — 方案与实施记录（2026-09-24）

复现并验证 LinkedIn 文章 [What is the PIM neighbor filter list?（YuQi Zhao）](https://www.linkedin.com/pulse/what-pim-neighbor-filter-list-yuqi-zhao-ry2sf/) 的实验：在 PIM-SM 共享网段上，两台 LHR 互相配置 `ip pim neighbor-filter`，使彼此"看不见"对方的 PIM 报文 → 双 DR 同时转发 → 接收者收到重复组播；同时检验文章关于 Assert 机制与 IGMP querier 的结论。

- GNS3 项目：`PIM-Neighbor-Filter-Test`（project_id `b35c4369-e162-4d58-9783-a2347bc36e7d`）
- 平台/版本：4× 模板 "Cisco IOU L3"（`x86_64_crb_linux-adventerprisek9-ms.iol`），`show version` 实测 **Cisco IOS Software [IOSXE], Version 17.18.2 RELEASE SOFTWARE (fc3)**（X86_64BI_LINUX-ADVENTERPRISEK9-M，2025-12-19 编译）——模板名/文件名像老 IOU，实际是 IOL-XE 17.18.2；§4.4 的 Assert 行为即在此版本上测得
- 快照：`baseline-pim-sm-clean`（干净基线，filter 已移除、配置已 write memory、节点已停）
- 结论一句话：**文章核心结论全部复现成功；但"Assert 未触发"的表述在本平台不成立——实测 Assert 触发了、只是永远无法收敛（双方都自认 winner）**。

## 1. 文章实验 → GNS3 映射

| 文章元素 | 本环境实现 | 备注 |
|---|---|---|
| R1 = RP | IOU-R-1（R1），lo0=1.1.1.1 | 静态 RP `ip pim rp-address 1.1.1.1` |
| Publisher（源 10.10.10.122） | R1 lo1 = 10.10.10.122/32，ping 源地址 | **偏差**：源在 RP 本机，无 Register 过程（见 §6） |
| R2 = LHR（Gi2, 192.168.10.1） | IOU-R-2（R2）e0/1 = 192.168.10.1/24 | |
| R3 = LHR（Gi1, 192.168.10.2） | IOU-R-3（R3）e0/1 = 192.168.10.2/24 | |
| Subscriber（接收者） | IOU-R-4（HOST）e0/0 = 192.168.10.10/24，`ip igmp join-group 239.10.10.10` | **偏差**：用路由器 join-group 代替真实主机；重复判定用 ping 回包计数 |
| 组 239.10.10.10 | 同 | |
| R2/R3 的 ACL 10（只 permit 自己环回） | `permit 2.2.2.2` / `permit 3.3.3.3` + `ip pim neighbor-filter 10`（e0/1） | 与文章逐字一致 |

拓扑（全部 Cisco IOU L3 + 内置 Ethernet switch）：

```
                lo0 1.1.1.1 (RP)          lo1 10.10.10.122 (源)
                     ┌─────── R1 ───────┐
                  e0/0│                e0/1│
              10.1.12.0/24        10.1.13.0/24
                     │                  │
                e0/0 R2 ─────┐    ┌───── R3 e0/0
                lo0 2.2.2.2  │    │  lo0 3.3.3.3
                     e0/1    │    │    e0/1
                192.168.10.1 │    │ 192.168.10.2
                       ┌─────┴────┴─────┐
                       │  Switch1 (LAN) │
                       └───────┬────────┘
                           e0/0 HOST
                        192.168.10.10
                     join-group 239.10.10.10
```

节点/链路（默认命名）：IOU-R-1=R1、IOU-R-2=R2、IOU-R-3=R3、IOU-R-4=HOST、Switch1=LAN。
链路：R1 e0/0↔R2 e0/0、R1 e0/1↔R3 e0/0、R2 e0/1↔SW p1、R3 e0/1↔SW p2、HOST e0/0↔SW p3。

## 2. 基础配置（全部已 write memory）

三台路由器公共：OSPF area 0 全接口（含 loopback）、`ip multicast-routing`、`ip pim rp-address 1.1.1.1`、各互联接口 `ip pim sparse-mode`。HOST：无 PIM/无组播路由，仅 e0/0 加 `ip igmp join-group 239.10.10.10` + 默认路由指向 192.168.10.1。

R1：
```
hostname R1
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
 ip ospf 1 area 0
interface Loopback1
 ip address 10.10.10.122 255.255.255.255
 ip ospf 1 area 0
interface Ethernet0/0
 ip address 10.1.12.1 255.255.255.0
 ip pim sparse-mode
 ip ospf 1 area 0
interface Ethernet0/1
 ip address 10.1.13.1 255.255.255.0
 ip pim sparse-mode
 ip ospf 1 area 0
router ospf 1
 router-id 1.1.1.1
ip multicast-routing
ip pim rp-address 1.1.1.1
```
R2/R3 同构（lo0=2.2.2.2/3.3.3.3，e0/0=10.1.12.2/10.1.13.2，e0/1=192.168.10.1/.2）。HOST：`ip igmp join-group 239.10.10.10` + `ip route 0.0.0.0 0.0.0.0 192.168.10.1`。

实验开关（R2/R3 对称，ACL 号 10 只 permit 自己环回——环回根本不在该网段，等于"拒绝一切邻居"）：
```
ip access-list standard 10
 permit 2.2.2.2          ! R3 侧为 3.3.3.3
interface Ethernet0/1
 ip pim neighbor-filter 10
```

## 3. Phase 0 — 基线（无 filter）

| 验证项 | 结果 |
|---|---|
| PIM 邻居 | R2↔R3 在 e0/1 互见，各自 e0/0 见 R1 ✅ |
| DR | **R3**（192.168.10.2，LAN 最高 IP；文章写 R2 是 DR，见 §5 差异 2） |
| IGMP querier | R2（192.168.10.1，LAN 最低 IP）→ 基线就已证明 DR≠querier |
| IGMP 组状态 | R2/R3 的 e0/1 都有 239.10.10.10（双方都听见 HOST 报告） |
| mroute | R3（DR）：(*,G) SJC + (S,G) JT，e0/1 Forward；R2（非 DR）：(*,G) SP、OIL Null |
| 数据面 | `R1#ping 239.10.10.10 source Loopback1 repeat 10` → **10 发 10 收、无重复** ✅ |

细节彩蛋：基线时 R2 e0/1 组播入计数=10（R3 转发到 LAN 的副本被 R2 收到、RPF 拒收仅计数）——这正是 Assert 的触发素材，但基线里 R2 不在转发该 (S,G)，所以不触发 Assert，符合协议。

## 4. Phase 1 — 加 filter（实验核心）与 Phase 2 — 撤销恢复

### 4.1 邻居互隐（文章结论 1 ✅）
filter 下发后 **<30s** 双方邻居表里对方即消失（各只剩 R1）。意外：**并不需要等 105s hello hold 超时**——配置 neighbor-filter 时 IOS 主动清除了不合格的既有邻居（比文章/文档直觉更干脆）。

### 4.2 双 DR（文章结论 2 ✅）
```
R2: PIM DR: 192.168.10.1 (this system)   neighbor count: 0   neighbor filter: 10
R3: PIM DR: 192.168.10.2 (this system)   neighbor count: 0   neighbor filter: 10
```

### 4.3 重复组播包（文章结论 3 ✅，200% 实锤）
```
R1#ping 239.10.10.10 source Loopback1 repeat 10
Reply to request 0 from 192.168.10.10, 3 ms
Reply to request 0 from 192.168.10.10, 3 ms     ← 每个 echo 两份
...（20 行回包，10 发）
```
计数器（双侧镜像）：R2/R3 的 (10.10.10.122, 239.10.10.10) 各 Forwarding 10 包、各 RPF failed ~11（收到对端副本拒收）。

### 4.4 Assert 行为（⚠️ 与文章不一致——本文档最重要发现）
文章称"Assert 没有触发，mroute 无 A 标志"。本平台（IOL，IOS-XE 17.18.2）实测：
```
R2: (10.10.10.122, 239.10.10.10) ... Ethernet0/1, Forward/Sparse, flags: A
R3: (10.10.10.122, 239.10.10.10) ... Ethernet0/1, Forward/Sparse, flags: A
```
**双方 (S,G) 出接口都带 A（Assert winner）且都持续转发**。解释：收到对端数据副本这一触发条件成立 → 各自发起 Assert；但对端的 Assert 报文（PIM type 5）也被 neighbor-filter 丢弃 → 双方都收不到挑战、都判自己获胜 → **选举永不收敛的双赢家**，重复包无限持续。文章"未触发"的表述不准确（至少对本 IOS 版本）：准确说法是"触发了、但消息交换被过滤、永远无法收敛"。证据链：双方 A 标志 + 双方持续 Forward + 200% 回包 + 双方 RPF failed 计数（触发素材在流入）。

### 4.5 IGMP querier 独立（文章结论 4 ✅）
filter 后 R3 仍是 DR，但 `IGMP querying router is 192.168.10.1`（R2）。IGMP 查询者选举走 IGMP 一般查询（224.0.0.1），与 PIM Hello 无关，neighbor-filter 对其零影响。DR 选举与 querier 选举是两套独立机制 ✅。

### 4.6 撤销恢复（文章未做，补充验证）
`no ip pim neighbor-filter 10` + `no ip access-list standard 10`：
- ~40s 内 R2/R3 邻居互见恢复（等下一个 30s hello 周期），DR 回到唯一（R3）；
- 重复包在一个 Join/Prune 周期内消失（恢复后首个 echo 曾出现一次暂态双份，R2 的 join 剪枝滞后，属正常收敛）；
- R2 的 (S,G) 回到 `PJT / OIL Null`，A 标志清除。

## 5. 与文章结论对照总表

| # | 文章结论 | 复现结果 |
|---|---|---|
| 1 | 邻居表互隐（各只剩 RP 侧） | ✅ 一致 |
| 2 | 双方都自认 DR | ✅ 一致 |
| 3 | 接收者收到重复组播 | ✅ 一致（ping 回包 200%） |
| 4 | **Assert 未触发、无 A 标志** | ❌ **不一致：双方都有 A 标志、都在转发——Assert 触发但被过滤无法收敛（双赢家）** |
| 5 | DR 选举与 IGMP querier 选举独立 | ✅ 一致（querier 始终是 R2=最低 IP，与谁当 DR 无关） |
| 6 | （文章叙述）R2 基线时是 DR | ❌ IOS 按 LAN 最高 IP 选 DR，R3(.2) 当选；文章编址下不可能是 R2(.1)，疑为文章笔误或平台差异 |

## 6. 复现过程中的问题与偏差记录（方法学）

1. **源端简化**：文章的 Publisher 在 RP 之外（有 First-Hop/Register 过程）；我们用 R1 lo1 当源（源=RP），绕过 Register。被测机制在 LHR 侧（双 DR/重复转发/Assert），该简化不影响结论；如需全流程可再加一台源侧路由器。
2. **接收端简化**：用 IOU `ip igmp join-group` 代替真实 Subscriber，以 ping 回包计数（200%）判定重复，代替文章的流量观测。ICMP 回包能精确计数，判定反而更定量。
3. **Assert 观测手段受限**：MCP `device_show_run` 按契约拦截 `debug`（防控制台挂死），无法像文章环境那样看 debug；改用 mroute A 标志 + 转发计数 + RPF failed 计数三件套，证据等效。
4. **行内 ping 无 `ttl` 关键字**：该镜像（IOS-XE 17.18.2）`ping ... ttl 8` 报 Invalid input；默认 TTL=255 足够，去掉即可。另：模板名 "Cisco IOU L3" 有迷惑性——`show version` 实为 IOS-XE 17.18.2，跨版本引用本实验结论时以此为准。
5. **filter 的生效时延与预期相反**：预期要等 hello hold（105s）老化，实测配置即清除既有邻居（<30s）；但撤销恢复时确实要等一个 hello 周期（~30-40s）邻居才回来。做时间敏感实验时注意这两个不对称。
6. **恢复暂态**：撤销 filter 后第一个 echo 可能仍有双份（R2 的 (S,G) join 要等 Join/Prune 周期剪除），验证"恢复完成"要等一个 J/P 周期（≤60s）再下结论。

## 7. 实验菜单（重放步骤）

前置：打开项目 → `node_start_all` → 等 ~1 分钟收敛（配置已持久化、快照可回滚）。
```
# 基线
R2/R3: show ip pim neighbor ; show ip pim interface e0/1 detail ; show ip igmp interface e0/1
R1:     ping 239.10.10.10 source Loopback1 repeat 10        # 10 收
# 加 filter（R2 侧）
R2: conf t
 ip access-list standard 10
  permit 2.2.2.2
 int e0/1
  ip pim neighbor-filter 10
# 加 filter（R3 侧，permit 3.3.3.3 同构）
# 等 ~30s 后验证
R2/R3: show ip pim neighbor            # 对方消失
R2/R3: show ip pim interface e0/1 det  # 双 this system DR
R1:     ping 239.10.10.10 source Loopback1 repeat 10        # 20 收 = 200%
R2/R3: show ip mroute 239.10.10.10     # 双 A 标志（Assert 双赢家）
R2/R3: show ip mroute 239.10.10.10 count  # 双侧 Forwarding+RPF failed
# 撤销
R2/R3: int e0/1 ; no ip pim neighbor-filter 10 ; exit ; no ip access-list standard 10
# 等 ~60s（hello + J/P 周期）后复测：10 收、邻居互见、单 DR
```

## 8. 重建 checklist（从零）

1. `project_create PIM-Neighbor-Filter-Test`；
2. 4× 模板 `Cisco IOU L3`（12678fbc-8d34-444a-b533-40d9de97a1aa）+ 1× 内置 `Ethernet switch`，默认命名；
3. 5 条 ethernet 链路（见 §1 端口表）；
4. `node_start_all`，等 45s；
5. 按 §2 推送配置（device_config_send，IOS 尾部 `do write memory`）；
6. 等收敛后按 §7 复放；收尾 `node_stop_all`（4 IOU）+ snapshot。

---
*Built & verified 2026-09-24 via GNS3 MCP（全程仅走 MCP 接口）。*
