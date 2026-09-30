# QEMU-Kernel-DataPath-Test 方案与实施记录

> 2026-09-30 建成并全量验证。项目 `Qemu-Kernel-DataPath-test-FRRqemu`（ID `2e2db147-61ec-45cc-b129-64f6a0f89d88`）。
> 目的：验证 GNS3 3.1 dev 的 kernel-datapath 链路在 **QEMU 节点**上的实现与效果，与《Docker-Kernel-DataPath-test-FRRDocker》（11×FRRDocker）互为对照。
> 本文所有数据面结论除明确标注"转述"外，均为本次实测（证据：各步 console/link API 原始输出）。

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

---
*Built & verified 2026-09-30 via GNS3 MCP。数据面结论均为实测；Docker 版转述结论已标注。*
