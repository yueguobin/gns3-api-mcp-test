# QEMU-Kernel-DataPath-Test 方案与实施记录

> 2026-09-30 建成并全量验证（6 节点）。项目 `Qemu-Kernel-DataPath-test-FRRqemu`（ID `2e2db147-61ec-45cc-b129-64f6a0f89d88`）。
> 目的：验证 GNS3 3.1 dev 的 kernel-datapath 链路在 **QEMU 节点**上的实现与效果，与《Docker-Kernel-DataPath-test-FRRDocker》（11×FRRDocker）互为对照。
> 本文所有数据面结论除明确标注"转述"外，均为实测（证据：各步 console/link API 原始输出）。
>
> **⚠️ 现行状态（2026-10-04 起）：项目已原地扩展至 11×FRR-qemu，与 Docker 版逐段同构。§1–§9 为 6 节点建成期原文（历史记录），其拓扑/编址/链路清单已被 §10 取代；现行拓扑、编址、filter 与性能结论一律以 §10 为准。**（原 6 节点快照 `baseline-qemu-kernel-datapath-clean` 仍在快照列表中，可整体回滚到 6 节点态。）
> **§11 = 性能优化专节：e1000 → virtio-net-pci 的 A/B 实测（吞吐 ×5–10，主项目未改动，载体为复制项目 `Kernel-DataPath-Qemu-FRRqemu-virtio`）。**

## 1. 背景与问题

Docker 版实验场已证明 docker↔docker 链路 `kernel_datapath=true` 且 13 种 packet filter 全部生效。悬而未决的问题：

1. QEMU↔QEMU 链路是否同样走内核数据面（tap 直挂）？
2. kernel-datapath 专属 filter（rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop）在 QEMU 链路上是否同样开放且数据面精确？
3. QEMU 混合链路（qemu↔docker）如何判定？
4. QEMU 链路的延迟/吞吐量级与 docker 版差多少？

## 2. 平台

- GNS3 server 3.1.0.dev7，单 compute `local`
- **FRR-qemu 模板**（2026-09-30 14:27 新装）：`frr-8.2.2.qcow2`，Alpine Linux，8×e1000，256MB，IDE 盘，console=telnet
  - console 直接落 **vtysh**（`frr#`），`exit` 回 root shell（`frr:~#`，root/root），`vtysh` 再进
  - busybox 工具箱：有 ss/traceroute/nc，**无 iperf3/tcpdump/ethtool**
  - watchfrr 全家桶在跑（zebra/ospfd/bgpd/…），`net.ipv4.ip_forward=1` 出厂已开
- 主机：Ubuntu Docker Guest ×2（iperf3/ping/traceroute 齐全）

## 3. 拓扑与编址

```
host1(10.2.100.1) ── FRR-qemu-1 ══╪══ FRR-qemu-2 ── FRR-qemu-3 ── FRR-qemu-4
                        eth2=10.2.100.254   │ (eth0=10.2.1.0/30 + eth1=10.2.6.0/30 双平行)
                                            └─ FRR-qemu-5 ── FRR-qemu-6 ── host2(10.2.200.1)
```

- Loopback `10.2.0.N/32`；链段 `10.2.{1..6}.0/30`（seg1/seg6 为 1↔2 平行链）；主机网 10.2.100/200.0/24（网关 .254）
- OSPFv2 单区域：每台 `router ospf` + `ospf router-id 10.2.0.N` + `network 10.2.0.0/16 area 0`，transit 接口 `ip ospf network point-to-point`
- 持久化：6 台 `write memory`（/etc/frr/frr.conf）；主机 `/etc/network/interfaces`（busybox 分列语法）
- 快照：`baseline-qemu-kernel-datapath-clean`（3da371d3）

### link_id 清单

| 链路 | link_id | 说明 |
|---|---|---|
| N1 e0 ↔ N2 e0 | `e0489018-cca3-48f8-8a9a-6c69d5bc67fc` | seg1（平行 1） |
| N1 e1 ↔ N2 e1 | `7d26e21d-ffe6-407d-918d-62da36613e4d` | seg6（平行 2） |
| N2 e2 ↔ N3 e0 | `a0e96fb3-8231-4e26-932a-2b9c03c651fe` | seg2（filter 主测链） |
| N3 e1 ↔ N4 e0 | `cc6d608c-6144-4fce-8f3c-45109c371430` | seg3 |
| N4 e1 ↔ N5 e0 | `0382d4e7-7441-4de8-bafb-bbcd610e0501` | seg4 |
| N5 e1 ↔ N6 e0 | `8952b17d-233d-4674-b8cf-c2005d0553a5` | seg5 |
| N1 e2 ↔ host1 e0 | `a372023f-56e5-4f13-b211-b871e6920603` | 混合链 qemu↔docker |
| N6 e1 ↔ host2 e0 | `b37b89c3-f28b-419e-83bb-33e9c7d3c11d` | 混合链 qemu↔docker |

## 4. kernel datapath 判定（问题 1/3）

- **qemu↔qemu**：link_get → `kernel_datapath: true`（seg1 冒烟首验，后全链一致）
- **qemu↔docker 混合**（host1 链）：`kernel_datapath: true`
- 实现证据：qemu 命令行 `-netdev tap,id=gns3-0,ifname=gq<nodeid>e<N>p0,script=no` —— QEMU 网卡直接挂宿主 tap，uBridge 内核桥接，filter 走内核 tc/eBPF
- `link_available_filters`：13 种全开放（含 8 种 kernel-datapath 专属），与 docker 链完全一致

## 5. 路由与端到端验证

- OSPF 邻接：N1=2、N2=3、N3/N4/N5=2、N6=1，全部 Full（链路侧合计 6 段邻接，与拓扑一致）
- N1 路由表：10.2.0.2..6/32 全部双下一跳（via 10.2.1.2 + via 10.2.6.2）——平行链 ECMP 成立
- host1→host2：5 发 5 收 0% 丢，ttl=58，traceroute 7 跳（.254→10.2.6.2→10.2.2.2→10.2.3.2→10.2.4.2→10.2.5.2→host2），ECMP 哈希走 seg6

## 6. Filter 实测（问题 2，数据面验证；15–18 项为晚间补测）

换算规律与 Docker 版一致：**filter 双向各生效一次**（RTT 丢包=1−(1−L)²，RTT delay=2×单向，rate 按帧长=IP+14B 序列化）。

| # | filter（作用链） | 配置 | 实测 | 理论/判定 |
|---|---|---|---|---|
| 1 | delay（seg1 单段） | [10] | RTT 20.88–21.16ms | 2×10+0.9 底噪 ✓ |
| 2 | delay（全部 6 段） | [5] | RTT 53.85ms | 2×5段×5+4.6=54.6 ✓ |
| 3 | delay（全部 6 段） | [10] | RTT 104.86ms | 2×5×10+4.6=104.6 ✓ |
| 4 | delay+jitter+dist（seg2） | [10,3,normal] | avg 24.8 / mdev 4.9 / [17.8,37.1] | 2×10+4.6；双向 jitter 叠加 ✓ |
| 5 | packet_loss（seg2） | [10] | 18%（100 样本） | 1−0.9²=19% ✓ |
| 6 | rate（seg2） | [512kbit] | 1400B：48.79ms；56B：6.63ms | 2×(1442×8/512k)+底噪≈49.7；2×(98×8/512k)+4.6≈7.7 ✓ |
| 7 | frequency_drop（seg2） | [3] | 54%（100 样本） | 1−(2/3)²=55.6%（eBPF 每 N 精确）✓ |
| 8 | gemodel（seg2） | [10,10,50] | 47%（100 样本） | 单向 p/(p+r)×(1−h)=25%→RTT 43.75% ✓ |
| 9 | window_drop 三参（seg2） | [0,60000,100] | 100% 全死 | 判别实验：filter 活 ✓ |
| 10 | window_drop 三参（seg2） | [20000,3000,100] | seq98–127 连续 30 丢，时长 3.0s，窗外 0 丢 | outage=3000ms 精确；start 以 filter 应用时刻起算 ✓ |
| 11 | duplicate（seg2） | [20] | +42 DUP/100 包 | 双向各 20%≈40 ✓ |
| 12 | bpf（seg2） | [icmp] | 100%（10/10 全丢） | ✓ |
| 13 | corrupt（seg2） | [50] | 84%（100 样本） | 坏包校验和不过→按丢包计，理论 75%，netem 位翻转语义内 ✓ |
| 14 | quota（seg2） | [20000,100] | seq0–13 通、14 起全死 | 20000B÷1442B/帧≈13.9 帧硬断崖 ✓ |
| 15 | reorder（seg2，配合 delay=[20]） | [50,0,10] | 到达序乱序（11 先于 9/10 等 42 处偏移），300/300 收齐 0 丢 | 对照 delay-only 300/300 有序；reorder 生效 ✓ |
| 16 | limit（seg2，delay=[50,0] 基准） | limit=[10] vs [1000] | 10 路并发突发 600 包（~1000pps）：limit10 丢 73–80%；limit1000 丢 0%；单流在队 ~6/方向不触阈 | 队列深度尾丢语义 ✓ |
| 17 | seed（host1↔N1 静默链） | packet_loss=[20]+seed（换值重下发多轮） | 同 seed 两轮 85/85 丢包序列逐位相同（md5 一致）；异 seed 图案不同 | seed 包级可复现 ✓；同值重设不重置 RNG（见下） |
| 18 | window_drop 四参（host1↔N1 静默链） | [15000,3000,100,8000] | 4 完整窗：周期 8.000s、窗长 2.91–3.02s、窗内 100% 丢、窗外零丢 | 周期窗精确 ✓ |

15–18 项于 2026-09-30 晚补测完成（此前仅 Docker 版逐项验证过；本 QEMU 实验场复测确认跨平台一致）。

### seed 可复现性与"同值重设不重置 RNG"（补测发现）

在 host1↔N1 静默链（方法论见下）做的判定实验（全部实测）：

| 轮次 | 操作 | 结果 |
|---|---|---|
| X | seed=12345 首用 | 85/200 丢，md5 `18297743…` |
| W | seed=99999 | 77/200 丢，图案不同（与 X 差 55 行） |
| Z | 换回 12345（前值 99999，**非**同值） | **与 X 逐位相同**（md5 一致、diff=0） |
| A | seed=42 首用 | 120/300 丢 |
| B | 同值 {20,42} 重下发 | 与 A 差 72 行（RNG 未重置） |
| Y | 同值 {20,12345} 重下发 | 与 Z 差 41 行（RNG 未重置） |

结论：seed 能实现包级可复现（同 seed 同图案、异 seed 异图案，X/W/Z 三连坐实）；但**同值重设 filter 是 no-op，RNG 状态不重置**（B/Y 接着上一轮 RNG 继续跑）。这是 controller 层"同值 filters PUT 短路"的**已知行为**（修复仅对含 `window_drop` 的集合开例外：`new_filters != self.filters or "window_drop" in new_filters`），非新 bug——非 window_drop 的同值重发不会重建 qdisc，故 RNG 不重置。复现实验配方：先换一个 seed 值（或清空 filters）再下发目标值。

### 静默链路方法论（干净 filter 实验）

seg2 上有 N2/N3 每 10s 的 OSPF hello 会消耗 RNG 抽签，seed 复现实验必须换无干扰链路：**host1↔N1**（对端是主机、本无 OSPF 邻接），临时给 N1 eth2 设 `passive-interface`（show 显示 "No Hellos"，网段仍正常通告、不影响路由），测完已还原并 write memory。编排用"自计时脚本"（host1 侧 `sleep 12`，期间从 MCP 下发 filter）保证 apply→首包窗口零流量。

### window_drop 编排延迟坑（重要）

start=3000/5000 的短窗两次测得 0% 丢包——**不是 filter 失效**，是 MCP link_update → (模型往返) → console 连接 → ping 启动的编排链路耗时 ~7–10s，ping 开跑时窗口已过。对策：start 留 ≥15s 余量，或用 start=0 判别 + 长窗时间线分析。Docker 版"疑坏系时序错过"的结论在 QEMU 版复现。

## 7. 性能基线（问题 4，对照 Docker 版）

| 指标 | QEMU 6 跳（本项目） | Docker 11 跳（对照） |
|---|---|---|
| host↔host RTT | **4.58 ms**（ttl=58） | 0.36 ms（ttl=53） |
| 每跳延迟 | ~0.7 ms（e1000 模拟） | <0.1 ms |
| iperf3 单流 | **609 Mbps**（cwnd≈218KB） | 2.22 Gbps |
| iperf3 16 流 | **440 Mbps（不升反降）** | 19.4 Gbps |
| 全链 delay 5ms 单流 | 317 Mbps | 1.64 Gbps |
| 全链 delay 10ms 单流 | 90 Mbps；-w 4M→124 Mbps | 466 Mbps |

结论：

- QEMU 每跳开销比 docker 高一个量级（e1000 设备模拟 + Alpine 内核转发），**瓶颈在 VM 转发路径，不在 kernel datapath**（filter 对 docker/qemu 链同等精确）
- 16 流反而低于单流：e1000 单队列 + VM 上下文切换串行化，与 docker 版"多流聚合上涨"形态相反
- 吞吐 ∝ 1/RTT、加窗部分恢复的 TCP 规律与 docker 版一致

## 8. 坑清单（QEMU/FRR-8.2.2 特有）

1. vtysh 无 `ping`、无 `show ip interface brief`（用 shell ping / `show interface brief`）
2. `write memory` 提示 "this version of vtysh never writes vtysh.conf" 属正常（写 /etc/frr/frr.conf）
3. console 窄屏回绕严重：长命令/长输出落 /tmp 文件再 grep；console 管道偶发吞输出（iperf3 tail -2 空、awk 空输出均遇过）
4. FRR VM console 落 vtysh 而 docker FRR 落 shell——推送脚本要区分模式（shell 下先 `vtysh`，vtysh 下配完 `exit` 回 shell 收尾）
5. window_drop 短窗 vs 编排延迟（见 §6）
6. qemu 节点启动 ~45–60s（比 docker 慢），批量 start 后等一分钟再配
7. **同值重设 filter 是 no-op，seed RNG 不重置**——复现实验必须换值再换回（见 §6 补测发现）
8. **`ping -O` 在发送间隔 < RTT 时对每包都打 "no answer yet"**（在途未回），不能当丢包计数；仅间隔 ≥ RTT 时该行才等价真丢包。丢包序列提取应配合"received 集合的补集"或 stats 行
9. 该镜像 ping 实际发包间隔下限 ~10ms（`-i 0.002` 不生效：50 包耗 462ms）；压队列要并发多路 ping（10 路 ~1000pps）
10. 补测在 host1↔N1 链路做过 seed/window4 实验，N1 的 `passive-interface eth2` 为临时设置、已还原（write memory）

## 9. 复验与快照

- 全部 filter 清除后 OSPF 全 Full 复验（N2=3/3）、端到端回基线
- 快照 `baseline-qemu-kernel-datapath-clean` 于全停后创建，随后 node_start_all 恢复，重启后 OSPF/主机配置自动恢复（frr.conf + /etc/network/interfaces 持久化）

### node stop/start 连通性专项（2026-10-01 实测，全部通过）

Docker 版曾踩过 stop/start 必废链路 L2 的大坑（ubridge `br_delbr` 裸删桥孤儿化对端端口，已修）；QEMU 走 tap 路径（`_remove_kernel_taps`），单独复验：

| 用例 | 重启对象 | 链路 | 结果 |
|---|---|---|---|
| A | UbuntuDockerGuest-1（docker 主机，单链） | host1↔N1 | eth0 IP 自动恢复（interfaces 持久化）、网关 0% 丢、E2E 0% 丢 ✓ |
| B | FRR-qemu-2（3 链：双平行对 N1 + 到 N3） | seg1+seg6+seg2 | N1 见 2×Full(10.2.0.2)、N3 见 Full(10.2.0.2)、E2E 0% 丢（RTT 3.64ms）✓ |
| C | FRR-qemu-1（3 链：双平行对 N2 + host1 侧） | seg1+seg6+host1 链 | N2 见 3×Full（10.2.0.1 双平行全活 + 10.2.0.3）、host1 网关 0% 丢、E2E 0% 丢 ✓ |

- 收尾复验：重启后的 N1 自身 2×Full（10.2.0.2）、链尾 N6 1×Full（10.2.0.5），全网邻接回基线
- 重启耗时：QEMU 节点 boot + OSPF 收敛 ≈80s；docker 主机 ≈30s
- 结论：**QEMU tap 路径不存在 Docker 曾有过的孤儿化问题**（与 09-30 ubridge 修复后的 Docker 侧复验一致）；FRR 配置由 frr.conf、主机由 /etc/network/interfaces 自动恢复
- 副作用记录：FRR VM 重启后 console tty 落点重置为 vtysh（推 shell 命令前需先 `exit`）

---
*Built & verified 2026-09-30 via GNS3 MCP。数据面结论均为实测；Docker 版转述结论已标注。*

---
---

# §10 扩展至 11 节点（2026-10-04，现行基线）

> 本节所有数据均为 2026-10-04 本次实测（MCP link/node API 原始返回 + 设备 console 输出）。6 节点版旧结论被引用处均已标注【沿用 09-30】。

## 10.1 背景与目的

6 节点场（§1–§9）是 Docker 版 11 节点场的"缩比对照"。本轮按需求**原地扩展至 11×FRR-qemu**，与 `Kernel-DataPath-Docker-FRRDocker`（11×FRRDocker）**逐段同构**，用于：

1. 同节点数/同跳数（11 节点、10 段中转）下 QEMU vs Docker 的性能矩阵直接逐格对照；
2. 11 条链路的 kernel 判定与 filter 能力普查；
3. 代表性子集 filter 数据面精测（6 节点版 13 种已全测，本轮按"全链普查 + 代表性子集"策略）；
4. 重编号改造后的持久化（frr.conf）与 stop/start 连通性复验。

**范围声明（证据来源）**：本轮数据面精测覆盖 7 种 filter（delay / packet_loss / rate / bpf / frequency_drop / gemodel / duplicate）；其余 6 种（corrupt / reorder / seed / limit / quota / window_drop）**本轮未重测**，相关结论仍以 6 节点版 §6 为准【沿用 09-30】，仅在能力普查层面确认其在 11 条链上全部开放。

## 10.2 改造内容（原地扩展）

| 项 | 内容 |
|---|---|
| 新增节点 | 5×FRR-qemu（FRR-qemu-7..11，模板 `56fead79-e29c-4397-a1dd-a6c3f2063eb5`，Alpine/8×e1000/256MB；默认命名一次到位，无竞态） |
| 链路改造 | 删旧尾链 N6 e1 ↔ host2 e0（旧 `b37b89c3-…`）；新建 6 条：N6-N7、N7-N8、N8-N9、N9-N10、N10-N11、N11-host2 |
| 重编号 | 现有 5 段共 10 个接口 IP 重排，**对齐 Docker 版 seg 编号**（seg1/seg2 = 1↔2 双平行，seg3..seg11 沿链） |
| 配置通道 | 11 台打 `device_type:cisco_ios_telnet` tag → `device_config_send` **直通 vtysh 批量下发**（含 `write memory` 落 /etc/frr/frr.conf）；shell 层（读 /etc/network/interfaces）仍走 ws console |

改法（每接口，vtysh 配置模式）：`no ip address <旧>` → `ip address <新>` →（transit 口）`ip ospf network point-to-point` → `end` → `write memory`。实测 `write memory` 回显 `Integrated configuration saved to /etc/frr/frr.conf`。

**实测确认：FRR-qemu 的 `/etc/network/interfaces` 全为注释样例，接口 IP 完全由 frr.conf（zebra）驱动**——改 IP 只需 vtysh + write memory，无 OS 层"旧地址残留"风险。

## 10.3 拓扑与编址（现行）

```
host1 ── FRR-qemu-1 ══╪══ FRR-qemu-2 ── 3 ── 4 ── 5 ── 6 ── 7 ── 8 ── 9 ── 10 ── 11 ── host2
10.2.100.1   eth2=.254   │  (seg1 + seg2 为 1↔2 双平行 ECMP)                    eth1=.254  10.2.200.1
```

- Loopback `10.2.0.N/32`；链段**按串接顺序** `seg1..seg11 = 10.2.N.0/30`（近 1 端取 .1）
- 主机网 `10.2.100.0/24`（host1 .1 ↔ N1 e2 .254）、`10.2.200.0/24`（N11 e1 .254 ↔ host2 .1）
- OSPFv2 单区：每台 `router ospf` + `ospf router-id 10.2.0.N` + `network 10.2.0.0/16 area 0`（host 网段落在 /16 内自动收编），transit 全 `ip ospf network point-to-point`
- 持久化：11 台 `write memory`；主机 `/etc/network/interfaces`

### 接口 ↔ 链段对照

| 链段 | 网段 | A 端 | B 端 |
|---|---|---|---|
| seg1 | 10.2.1.0/30 | N1 e0 (.1) | N2 e0 (.2) |
| seg2 | 10.2.2.0/30 | N1 e1 (.1) | N2 e1 (.2) |
| seg3 | 10.2.3.0/30 | N2 e2 (.1) | N3 e0 (.2) |
| seg4 | 10.2.4.0/30 | N3 e1 (.1) | N4 e0 (.2) |
| seg5 | 10.2.5.0/30 | N4 e1 (.1) | N5 e0 (.2) |
| seg6 | 10.2.6.0/30 | N5 e1 (.1) | N6 e0 (.2) |
| seg7 | 10.2.7.0/30 | N6 e1 (.1) | N7 e0 (.2) |
| seg8 | 10.2.8.0/30 | N7 e1 (.1) | N8 e0 (.2) |
| seg9 | 10.2.9.0/30 | N8 e1 (.1) | N9 e0 (.2) |
| seg10 | 10.2.10.0/30 | N9 e1 (.1) | N10 e0 (.2) |
| seg11 | 10.2.11.0/30 | N10 e1 (.1) | N11 e0 (.2) |
| host1 网 | 10.2.100.0/24 | N1 e2 (.254) | host1 e0 (.1) |
| host2 网 | 10.2.200.0/24 | N11 e1 (.254) | host2 e0 (.1) |

### node_id 清单（新增 7..11）

| 节点 | node_id | console |
|---|---|---|
| FRR-qemu-1 | `e59655d6-87cd-4915-8df8-6bb857617fb6` | 5000 |
| FRR-qemu-2 | `1373186d-8b95-4e43-8e7d-8e36904ed8fc` | 5005 |
| FRR-qemu-3 | `42397b9d-5ed7-4b84-b447-57056343a7a4` | 5006 |
| FRR-qemu-4 | `c6378bf5-5062-40d2-b5c9-afbcf01c9463` | 5014 |
| FRR-qemu-5 | `d4cbe854-2843-4d45-a20b-ba91aea78cfd` | 5012 |
| FRR-qemu-6 | `39a2862d-659c-4640-a4f7-1559f43b34e3` | 5015 |
| FRR-qemu-7 | `8a05baa2-7ae2-4c4b-b0d9-b511243fcd3a` | 5020 |
| FRR-qemu-8 | `d6ca06c9-1b7b-49f3-a216-77d1c818fcb7` | 5023 |
| FRR-qemu-9 | `0b28ec3e-c732-4bf9-ac13-08fe61b47d5b` | 5026 |
| FRR-qemu-10 | `04d316f0-ccc8-45f9-a55b-bae6ad4d637e` | 5029 |
| FRR-qemu-11 | `b57a7d91-4f5d-40a5-a22b-ff4f13118fe8` | 5032 |
| UbuntuDockerGuest-1 | `73d9e9a1-00c3-434e-a719-90adcc53549a` | 5018 |
| UbuntuDockerGuest-2 | `fe87229f-2755-4ad5-b5de-e1d389987d53` | 5019 |

### link_id 清单（13 条，全部 `kernel_datapath: true`）

| 链路 | link_id | 说明 |
|---|---|---|
| seg1 N1 e0 ↔ N2 e0 | `e0489018-cca3-48f8-8a9a-6c69d5bc67fc` | 平行 1 |
| seg2 N1 e1 ↔ N2 e1 | `7d26e21d-ffe6-407d-918d-62da36613e4d` | 平行 2（与 seg1 ECMP） |
| seg3 N2 e2 ↔ N3 e0 | `a0e96fb3-8231-4e26-932a-2b9c03c651fe` | |
| seg4 N3 e1 ↔ N4 e0 | `cc6d608c-6144-4fce-8f3c-45109c371430` | |
| seg5 N4 e1 ↔ N5 e0 | `0382d4e7-7441-4de8-bafb-bbcd610e0501` | |
| seg6 N5 e1 ↔ N6 e0 | `8952b17d-233d-4674-b8cf-c2005d0553a5` | **filter 主测链（链中段）** |
| seg7 N6 e1 ↔ N7 e0 | `5a0ae2e9-7c33-4fe3-9b72-87c93887f382` | 新建 |
| seg8 N7 e1 ↔ N8 e0 | `798cef8c-acdd-4698-a495-93a9fb311c0c` | 新建 |
| seg9 N8 e1 ↔ N9 e0 | `90e3516c-3b9b-49c9-bc02-6b426a0f8d62` | 新建 |
| seg10 N9 e1 ↔ N10 e0 | `8f878553-e0b5-4766-841d-1db9454690fd` | 新建 |
| seg11 N10 e1 ↔ N11 e0 | `0ac76211-866c-4892-b2e7-fb840d1c0d1a` | 新建 |
| host1 N1 e2 ↔ host1 e0 | `a372023f-56e5-4f13-b211-b871e6920603` | 混合链 qemu↔docker |
| host2 N11 e1 ↔ host2 e0 | `47a423f6-d588-4824-8404-7e691484755f` | 新建（原 N6 侧旧链已删） |

## 10.4 路由与端到端验证

- **OSPF 邻接 22/22 Full**：N1=2、N2=3、N3–N10=2、N11=1（每条链两两 Full，与 Docker 版一致）
- **host1 → host2：traceroute 11 个路由器跳 + 1 个主机跳**（`.254 → 10.2.1.2 → 10.2.3.2 → … → 10.2.11.2 → 10.2.200.1`），ping 20/20 `0% 丢`、**ttl=53**（64−11）
- **N1 对远端 /32 双下一跳 ECMP**：`show ip route 10.2.0.11/32` → `* 10.2.1.2 via eth0` + `* 10.2.2.2 via eth1`
- N6 路由表：左半（.1–.5、10.2.100.0/24）走 eth0，右半（.7–.11、10.2.200.0/24）走 eth1，metric 逐跳 +100，无环路

## 10.5 kernel datapath 与 filter 能力普查

- **13/13 链路全部 `kernel_datapath: true`**（含 5 条新建链与重建的 host2 链）
- **13/13 链路 `link_available_filters` 均返回全部 13 种**（frequency_drop / packet_loss / delay / corrupt / bpf / rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop），含全部 8 种 kernel-only 类型
- 实现证据（node_get 的 qemu 命令行）：`-netdev tap,id=gns3-N,ifname=gq<nodeid>e<N>p0,script=no` —— QEMU 网卡直挂宿主 tap，filter 走内核 tc/eBPF

## 10.6 filter 数据面精测（seg6 链中段，7 项，E2E host1→host2）

换算规律与 6 节点版/Docker 版一致：**filter 双向各生效一次**（RTT 丢包 = 1−(1−L)²、RTT delay = 2×单向、rate 按帧长 = IP+14B 序列化）。

| # | filter | 配置 | 实测 | 理论/判定 |
|---|---|---|---|---|
| 1 | delay | [10] | RTT min/avg/max = 24.477/27.474/29.082 ms（基线 6.63） | 6.63+2×10=26.6 ✓ |
| 2 | packet_loss | [10] | **20.5%**（200 包样本；另轮 100 包样本 12% 属抽样波动） | 1−0.9²=19% ✓ |
| 3 | frequency_drop | [3] | **56%**（100 包） | 1−(2/3)²=55.56% eBPF 精确 ✓ |
| 4 | bpf | ["icmp"] | **100%**（5/5 全丢） | ✓ |
| 5 | rate | ["512kbit"] | 1400B：53.24 ms；56B：9.59 ms | 理论 51.7 / 9.66（按帧长序列化）✓ |
| 6 | gemodel | [10,10,50] | **45%**（100 包） | 单向 p/(p+r)×(1−h)=25% → RTT 43.75% ✓ |
| 7 | duplicate | [20] | **+86/200 = 43%**（另轮 50 包样本 +32/50=64%，见坑 §10.9-5） | 双向各 20% → RTT +44% ✓ |

测毕 7 项后：filter 全部清空回 `{}`、OSPF 无抖动（seg6 两端 9m+ 未断）、基线 RTT 6.07 ms / iperf 329 Mbps 回归正常。

## 10.7 性能矩阵（对齐 Docker 版方法）

### 基线（filter 全清）

| 指标 | 实测 |
|---|---|
| host↔host RTT | **6.63 ms**（min/avg/max/mdev = 3.683/6.628/7.947/1.011，20 包） |
| ttl / 跳数 | ttl=53；traceroute 11 路由器跳 |
| iperf3 单流 | **342 Mbps** 发 / 340 收（-t 10，274 retr） |
| iperf3 反向单流 | 331 / 328 Mbps（对称） |
| iperf3 4/8/16/32 流 | **168 / 206 / 171 / 147 Mbps**（-t 8；retr 519 / 1554 / 2327 / 4166） |

**多流不升反降**（342 → 168/206/171/147），重传随流数暴涨——e1000 单队列 + VM 上下文切换串行化，与 6 节点版形态一致【沿用 09-30 同结论】，与 Docker 版"多流聚合至 19.4 Gbps"相反。

### delay × 吞吐曲线（seg1+seg2 双平行链同档 delay，对齐 Docker 版做法）

| delay/链 | RTT | 单流 | 16 流 |
|---|---|---|---|
| 0（基线） | 6.63 ms | 342 Mbps | 171 Mbps |
| 1 ms | 8.15 ms | 326 Mbps | 121 Mbps |
| 5 ms | 16.78 ms | 309 Mbps | 122 Mbps |
| 10 ms | 27.13 ms | 262 Mbps | 111 Mbps |
| 20 ms | 47.28 ms | 206 Mbps | 105 Mbps |

**关键差异（vs Docker 版）**：QEMU 场单流吞吐对 RTT **不敏感**（0→20 ms 仅降 40%），Docker 场同实验从 2.22 G 崩到 262 M（降 88%）。⇒ **QEMU 的瓶颈是 VM 包处理 CPU（每跳 ~0.6 ms 模拟开销），不是 cwnd/RTT**；Docker 的瓶颈才是 RTT。这解释了为何"QEMU 加延迟不掉速、Docker 加延迟掉速"。

### 全链 delay 锚点（11 段每段 5 ms，与 6 节点版同档可比）

| 指标 | QEMU 11 节点（现行） | QEMU 6 节点【09-30】 |
|---|---|---|
| RTT | **109.47 ms**（理论 2×10 段×5+6.6=106.6） | 53.85 ms（2×5 段×5+4.6） |
| 单流 | **131 Mbps** | 317 Mbps |
| 16 流 | 97.7 Mbps | —（6 节点版未测该点） |

### 三场横向对照

| 指标 | **QEMU 11 节点（现行）** | QEMU 6 节点【09-30】 | Docker 11 节点【对照场】 |
|---|---|---|---|
| host↔host RTT | 6.63 ms | 4.58 ms | 0.36 ms |
| 每跳延迟 | ~0.6 ms | ~0.7 ms | <0.1 ms |
| ttl / traceroute | 53 / 11 路由器跳 | 58 / 7 跳 | 53 / 11 路由器跳 |
| iperf3 单流 | 342 Mbps | 609 Mbps | 2.22 Gbps |
| iperf3 16 流 | 171 Mbps（反降） | 440 Mbps（反降） | 19.4 Gbps（聚合） |
| 全链 delay 5ms 单流 | 131 Mbps | 317 Mbps | — |

结论（实测）：

- 同为 11 节点 10 段中转，**QEMU 每跳开销比 Docker 高一个量级**（e1000 设备模拟 + Alpine 内核转发），端到端吞吐约为 Docker 的 1/6.5（342M vs 2.22G）；
- 吞吐随跳数下降（6 节点 609M → 11 节点 342M），但**非线性 1/RTT**（若纯 1/RTT 应降至 421M），说明 QEMU 场是"CPU 吞吐上限 + RTT"双重限制；
- filter 对 docker/qemu 链同等精确（换算规律完全一致），**瓶颈始终在 VM 转发路径，不在 kernel datapath**。

## 10.8 坑清单（本轮新增）

1. **console tty 模式跨连接共享（新踩）**：ws console 里发 `exit` 会把该 VM 的常驻 tty 从 vtysh 掉到 root shell；随后 `device_config_send`（netmiko）连的是**同一个 tty**，配置命令全部执行失败（`-ash: interface: not found`）。修法：ws 里发 `vtysh` 把 tty 送回（或重连后先确认提示符）。
2. **FRR-qemu 可走 device 工具直通（本轮新增能力，效率大幅提升）**：给节点打 `device_type:cisco_ios_telnet` tag 后，`device_config_send`/`device_show_run` 对 FRR-qemu 的 vtysh 完全可用（FRR 8.2.2 兼容 IOS 语法推送 + `write memory` 落盘）；shell 层操作（如读 `/etc/network/interfaces`）仍需 ws console。6 节点时期"ws 逐条推送"的姿势不再是唯一选择。
3. **改主地址要 `no ip address <旧>` 再 `ip address <新>`**，不要直接叠加（避免旧地址残留为 secondary）。
4. **FRR-qemu 的 `/etc/network/interfaces` 全为注释样例**——IP 由 frr.conf（zebra）驱动，改 IP 无 OS 层双地址风险（本次实测确认）。
5. **filter 判定样本量 ≥200**：packet_loss [10] 100 包样本测 12%、200 包样本 20.5%；duplicate [20] 50 包样本 +64%、200 包样本 +43%——短样本极易误判成"filter 不准"。
6. 其余 6 节点版坑（vtysh 无 ping、write memory 提示正常、console 窄屏回绕、QEMU 启动 45–60s、window_drop 编排延迟须 start≥15s、`ping -O` 坑）**继续有效**【沿用 09-30】。

## 10.9 快照与持久化复验（2026-10-04）

- 全部 filter 清空 → `node_stop_all` → 快照 **`baseline-qemu-kernel-datapath-11node-clean`**（`bb39ce6d-0cdd-436f-b341-ef5c6f230ede`）→ `node_start_all`，等待 ~80s 收敛后复验：

| 检查项 | 结果 |
|---|---|
| FRR-qemu-1 邻接 | 2×Full（**重编号后的新地址** 10.2.1.1 / 10.2.2.1 自动恢复） |
| FRR-qemu-6 / FRR-qemu-10 邻接 | 2×Full（seg6+seg7、seg10+seg11） |
| FRR-qemu-11 邻接 | 1×Full（10.2.11.1） |
| host1 → host2 | 10/10 收、**0% 丢**、RTT avg 6.49 ms |
| device 工具 | 重启后仍可用（console tty 自动落回 vtysh） |

⇒ **重编号后的 11 台接口 IP 全部由 frr.conf 自动恢复**、无 OS 层残留地址；stop/start 后链路无孤儿化问题【与 §9 的 QEMU tap 路径结论一致】。收尾状态：13 条链 `filters={}`、全部 `kernel_datapath=true`、OSPF 22/22 Full。

---
*§10 扩展与验证 2026-10-04 via GNS3 MCP（链路/节点/设备操作全程走 MCP：device_config_send / device_show_run / node_console+websocat / link_update / link_available_filters / snapshot_create）。数据面结论均为本次实测。*

---

# §11 QEMU 转发性能优化：virtio-net 网卡 A/B 实测（2026-10-04）

> 本节为性能优化专节，全部数据为本次实测。测试载体：独立复制项目 `Kernel-DataPath-Qemu-FRRqemu-virtio`（ID `7f9cec92-0dc9-434e-a1ac-d55512fbf569`），**现行 11 节点主项目未改动**。

## 11.1 背景：瓶颈定位（来自 §10 的实测证据）

§10 测得 QEMU 场性能受限的三条证据：每跳 ~0.6ms（Docker 同拓扑 <0.1ms）、**吞吐对 delay 不敏感**（+20ms RTT 单流仅降 40%，Docker 场降 88%）、多流反降。⇒ 瓶颈是 **QEMU 的设备模拟 + VM 边界**（e1000 每包陷入用户态模拟 MMIO），不是 kernel datapath、不是 cwnd/RTT。

**第一杠杆 = 换半虚拟化网卡**。前提确认（实测）：FRR-qemu guest 内核 `5.15.83-0-virt`（Alpine linux-virt）自带 `virtio_net.ko`，`/sys/bus/virtio` 总线已注册。

## 11.2 A/B 做法与结果

复制项目 → 11 台 FRR-qemu 的 `adapter_type` 由 `e1000` 改为 **`virtio-net-pci`**（其余全同：同镜像、1 vCPU/256MB、同拓扑同编址、同测量口径）。改后启动，接口名保持 eth0..eth7、frr.conf 的 IP 自动恢复、22/22 OSPF 收敛正常。

| 指标（host1→host2，11 节点） | e1000（§10 基线） | **virtio-net-pci** | 倍率 |
|---|---|---|---|
| ping RTT avg（20 包） | 6.63 ms | 6.03 ms | 0.91× |
| 每跳延迟 | ~0.6 ms | ~0.55 ms | 基本不变 |
| iperf3 单流 | 342 Mbps | **1.73 Gbps** | **×5.1** |
| iperf3 反向单流 | 331 Mbps | 1.70 Gbps | ×5.1 |
| iperf3 4 流 | 168 Mbps | 1.70 Gbps | ×10.1 |
| iperf3 8 流 | 206 Mbps | 1.74 Gbps | ×8.4 |
| iperf3 16 流 | 171 Mbps | 1.75 Gbps | ×10.2 |
| iperf3 32 流 | 147 Mbps | 1.52 Gbps | ×10.3 |
| 16 流重传 | 2327 | 6356 | — |
| **多流形态** | **不升反降（0.5×）** | **持平（≈1.0×）** | 形态改变 |

**结论（实测）**：
- **吞吐提升 5–10 倍**（单流 ×5.1，多流 ×8–10），且"多流反降"形态消失——**e1000 设备模拟确为吞吐主瓶颈**；
- **延迟几乎不变**（6.63→6.03ms）——低速率下的每跳 ~0.6ms 由 VM 调度/上下文切换决定，**换网卡解决吞吐、不解决单包时延**；
- filter 无回归：seg6 挂 `delay [10]` → RTT 27.79ms（+20 精确）；13/13 链仍 `kernel_datapath=true`（filter 装宿主 tap，与 guest 网卡型号无关）；
- 与三场对照的新位置：**virtio 版 QEMU 11 节点单流 1.73 G ≈ Docker 版 2.22 G 的 78%**（e1000 版只有 15%）。

## 11.3 复现要点与坑（实测）

1. `adapter_type` 必须**停机状态**下改（node properties 的 `properties.adapter_type`），重启即生效——QEMU 命令行变为 `-device virtio-net-pci,...,speed=10000,duplex=full`；
2. **`project_duplicate` 会重新生成全部 node_id / link_id / MAC**（用旧 id 直接 404），复制后必须重新取 id；
3. `project_duplicate(reset_mac_addresses=true)` 在当前服务器版本报类型错误（bool 传给了 path 参数）——用默认值即可（MAC 同样会重新生成）；
4. 复制体首次启动 OSPF 收敛需 ~60–90s，期间 ping 有丢包，勿误判为 virtio 故障；
5. 复制体的 docker 主机需重新拉起 `iperf3 -s -D`（不随容器持久化）。

## 11.4 第二杠杆实测：vCPU 1→2 + RAM 256→512MB（无收益，略负）

在同一 virtio 场把 11 台 FRR-qemu 的 `cpus`/`maxcpus` 1→2、`ram` 256→512（其余不动），重启复测。Guest 内实测确认生效：`nproc=2`、`free -m` total **480 MB**。

| 指标（host1→host2） | virtio @1 vCPU/256M | **virtio @2 vCPU/512M** | 变化 |
|---|---|---|---|
| ping RTT avg | 6.03 ms | 6.06 ms | 持平 |
| iperf3 单流 | 1.73 Gbps | **1.49 Gbps** | **−14%** |
| 4 流 | 1.70 Gbps | 1.52 Gbps | −11% |
| 8 流 | 1.74 Gbps | 1.56 Gbps | −10% |
| 16 流 | 1.75 Gbps | 1.55 Gbps | −11% |
| 32 流 | 1.52 Gbps | 1.48 Gbps | 持平 |
| 反向单流 | 1.70 Gbps | 1.47 Gbps | −14% |
| 单流重传 | 196 | **37** | 明显改善 |

复测（同场第二轮）：单流 1.51 G、16 流 1.42 G——与该配置首轮一致（稳定在 1.42–1.56 G 区间）。

**结论（实测）**：**加大 vCPU/内存没有收益、反而一致低 10–15%**（7 个测量点全部同向，非噪声）。原因【推断】：瓶颈本就在**宿主侧包路径**（QEMU 主循环 / tap / uBridge），guest 侧不缺 CPU；单队列 virtio 的收包路径仍只有一条，多出的 vCPU 带来调度/同步开销而吞吐反降（重传数大幅下降说明 guest 端更从容，问题不在 guest）。
⇒ **QEMU 场的最优已知配置 = virtio-net-pci + 1 vCPU / 256MB**；该结论已实测，vCPU/RAM 杠杆不再列入待验证。

**收尾**：测毕已用 `snapshot_restore` 把 virtio 场回滚到 `baseline-qemu-virtio-clean`（实测验证：`adapter_type` 保持 virtio-net-pci、`cpus/maxcpus` 回 1、`ram` 回 256），现场即最优配置态。

## 11.5 瓶颈归因：uBridge 还是 QEMU？（2026-10-04 实测阶梯）

从 host1 对逐级变远的目标各 ping 20 包（virtio 场、回滚后最优配置态）：

| 目标 | 单向路径 VM 数 | RTT avg（ms） | 增量 |
|---|---|---|---|
| 10.2.100.254（N1 e2，终结） | 1 | **0.472** | — |
| 10.2.0.2（N2 lo） | 2 | 1.267 | +0.795 |
| 10.2.0.6（N6 lo） | 6 | 3.838 | +0.64/VM（区间） |
| 10.2.200.1（host2） | 11 | 6.668 | **+0.62/VM**（首尾拟合） |

**线性度极好：每增加 1 个转发 VM，RTT +0.62 ms ⇒ 单向单次 guest 穿越 ≈ 0.31 ms**（首个终结型穿越略低 ≈0.24）。11 VM 全链 6.67 ms ≈ 拟合值，无异常跳变。

归因判据（全部实测）：

1. **无 VM 参照**：同宿主、同机制（GNS3 内核桥 + 两端点）的 docker↔docker 直连链 RTT 仅 **0.067 ms**【Mixed-Kernel-DataPath-Test 10-04 实测】——桥 + veth 全套 <0.1 ms。
2. **uBridge 不在逐包路径上**（kernel-datapath 链路）：qemu `-netdev tap` 直挂宿主 tap，两端 tap/veth 由**宿主内核桥**转发；tc/netem/eBPF filter 逐 ms 精确生效（§10.6/§11.2）即为内核转发的直接证据。uBridge/GNS3 只负责建桥/拆桥，不泵包。（uBridge 用户态泵包的是 relay 型链路——串口/旧版/跨 compute，本项目的以太链全不是。）
3. **每跳 0.6 ms 的构成**：0.62 ms（VM 代价）中 ≥90% 属 **QEMU 侧**——tap I/O 唤醒 QEMU 主循环 + VM entry/exit + guest 内核栈处理；桥转发本身 µs 级。e1000 与 virtio 每跳延迟相同（§11.2）⇒ 成本不在网卡模拟，而在 **VM 边界机制本身**。
4. 剩余不可分割项【推断】：0.31 ms/穿越内部（QEMU 主循环唤醒 vs guest 栈处理）无法用现有工具再拆——需 vhost-net（把 tap 处理从 QEMU 主循环下沉到内核线程）做对照才能分离，GNS3 3.1 未暴露该开关。

**结论（实测）：是 QEMU（VM 穿越）的问题，不是 uBridge 的问题。** uBridge 管理的内核桥全程只贡献 <0.1 ms 量级；每跳 0.6 ms 几乎全部花在 22 次 guest 进出上。要压延迟只剩 vhost-net 一个已知杠杆。

### 机制解剖：tap fd 在用户态，copy 到底贵不贵？（2026-10-04 分析）

GNS3 现行为**经典 tap 模式**（实测捕获的 qemu 命令行 `-netdev tap,…` 无 `vhost=on`）。每个包每次 guest 穿越的成本构成：

```
[前一跳 tap 队列]
  → QEMU 主循环被 epoll 唤醒           [WAKEUP]  ← 主体（几十~几百 µs）
  → read(tapfd)：内核→用户态 copy      [COPY #1] ← µs 级
  → virtio 后端 memcpy 进 guest RAM    （进程内 memcpy，非保护边界）
  → 注入 IRQ + KVM entry / VM exit     [VM 进出]
  → guest 内核 RX/TX softirq + 转发
  → QEMU write(tapfd)：用户态→内核     [COPY #2]
  → tap → 宿主内核桥 → 下一跳 tap
```

- 真正跨保护边界的 copy **每次穿越仅 2 次**（tap fd 的 read/write，ping 包 ~µs 级）；QEMU↔guest RAM 那步是进程内 memcpy（guest RAM 即 QEMU 自身 mmap），不跨界。
- **成本按"每次唤醒"计、不按"每字节"计**：围绕 copy 的编排（主循环唤醒+线程调度+KVM 进出+softirq）为主导，copy 本身占零头。

**满载自洽检验【推断】**：1.73 Gbps ÷ 64 KB GSO/TSO 超帧 ≈ 3375 帧/s/跳 ≈ **0.30 ms/穿越——与空闲单包阶梯测得的 0.31 ms（上文）是同一常数**。即满载时 TCP 靠 offload 把 ~44 个 MSS 打包成一个 64 KB 超帧、一次唤醒全带走（摊薄 44 倍）；**e1000 无 TSO/GSO，每包全额付费**（吞吐崩到 342 Mbps）。"延迟两代网卡相同、吞吐差 5 倍"正是按唤醒计费的指纹。（guest 为 busybox 无 ethtool，offload 状态未能直接核对，故标推断；数值自洽性强。）

**与"uBridge 无责"的统一**："桥在内核"只保证 uBridge 进程与桥转发不进用户态；tap 的**端点服务**仍在用户态——那是 **QEMU 的用户态**。包路径上唯一的用户态进程 = QEMU 自己（每跳醒 2 次、copy 2 次、进出 VM 2 次）。

**vhost-net 的意义**：把 vring 处理交给内核线程（`/dev/vhost-net`），包 tap↔virtio 全程不出内核——两次 copy 与主循环唤醒**同时消失**（TX 另有 zerocopy 路径）。它也是分离 0.31 ms 中 copy/wakeup 占比的唯一干净对照实验；前提是给 gns3server 的 QemuVM 在 tap netdev 后追加 `,vhost=on`（服务端小改）。

## 11.6 尚未验证的后续杠杆（推断，未实测）

| 杠杆 | 预期 | 依据 |
|---|---|---|
| guest 内核调优（tx_queue_len↑、backlog↑） | 小幅 | 推断 |
| **vhost-net** | **直接针对 §11.5 实测的 0.31 ms/穿越**（tap 处理出 QEMU 主循环） | 推断；GNS3 3.1 未暴露开关，`options` 注入会与自动生成的 `-netdev` 冲突，待验证 |
| 吞吐进一步：MTU 9000 | 减少 pps，间接提吞吐 | 推断；需全链统一改 MTU，改变实验语义 |
| ~~vCPU / RAM 加大~~ | ~~改善多流上限~~ | **已实测证伪（见 §11.4，反而 −10–15%）** |

**快照**：`baseline-qemu-virtio-clean`（`e7c68594-121e-4fa8-a12c-1ead859e57fc`）。复制项目节点/链路 ID 与本项目主文档 §10.3 的清单**一一对应但 UUID 不同**（名称相同）。

---
*virtio A/B 2026-10-04 via GNS3 MCP（project_duplicate / node_update properties.adapter_type / device 工具 / link_update）。数据均为本次实测。*
