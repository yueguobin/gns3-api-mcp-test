# IOU-Kernel-DataPath-Test 方案与实施记录

> 2026-10-01 建成并全量验证。项目 `Iou-Kernel-DataPath-test-CiscoIOU`（ID `9c00ff33-e555-4a8d-8e48-f14d1ed7b7d0`）。
> 目的：验证 GNS3 3.1 dev 的 kernel-datapath 链路在 **IOU 节点（Cisco IOU L3，非 IOL Docker）** 上的实现与效果，与《Docker-Kernel-DataPath-test-FRRDocker》《Qemu-Kernel-DataPath-test-FRRqemu》互为对照。
> 本文所有数据面结论除明确标注【转述】/【推断】外，均为本次实测（证据：各步 console/link API 原始输出）。服务端源码线索来自本地 gns3-server repo（HEAD `506a6bc94`），仅作背景标注。

## 1. 背景与问题

服务端本轮新增 IOU 的 kernel datapath（源码 commits：`f68b30fb7 feat(controller): offer IOU the kernel datapath`、`9d82de897 fix(iou): carry suspend from the NIO update body`、`506a6bc94 docs(iou)`）【转述·源码】。Docker/QEMU 两版实验场已分别验证，IOU 版悬而未决的问题：

1. IOU↔IOU 以太链路是否走内核数据面（`iol_bridge add_nio_tap` 锚点）？IOU↔docker 混合链路呢？
2. IOU **串口**链路（非以太端口）是否按设计留在 relay？
3. kernel 链上 13 种 filter 是否全开放且数据面精确？relay 串口链开放哪几种、kernel-only 是否被拒？
4. 历史悬案：IOU↔IOU 以太链的 filter 在 3.1.0a5 时代"API 接受但数据面未验"——现在落哪种数据面、是否精确？
5. suspend/resume 在 IOU kernel 链上是否原生生效（anchor admin-down）？
6. IOU 性能量级与 docker/qemu 差多少？
7. 节点 stop/start 后锚点生命周期是否自愈？

## 2. 平台

- GNS3 server 3.1.0.dev7+506a6bc94（单 compute `local`，`enable_kernel_datapath` 开启）
- **Cisco IOU L3 模板**（`12678fbc-8d34-444a-b533-40d9de97a1aa`）：镜像 `x86_64_crb_linux-adventerprisek9-ms.iol`，2×4 Ethernet + 2×4 Serial 适配器，IOS（IOU 17.x），console=telnet，tag `device_type:cisco_ios_telnet`
- 主机：Ubuntu Docker Guest ×2（`gns3/ubuntu:noble`，iperf3/ping 齐全）
- 本机 compute 已探测到 `iol_bridge add_nio_tap` 能力——否则链路会落 relay【实测：全部以太链 `kernel_datapath: true`】

## 3. 拓扑与编址

```
 host1 ── IOU-R-1 ══╪══ IOU-R-2 ── IOU-R-3 ── IOU-R-4 ── IOU-R-5 ── IOU-R-6 ── host2
(10.3.100.1)  (Eth0/2)  (Eth0/0+0/1 双平行)   (Eth0/2)   (Eth0/1)  ...    (Eth0/1) (10.3.200.1)
                          └─ R2 Serial2/0 ── R3 Serial2/0（relay 对照，不进 OSPF）
```

- Loopback `10.3.0.N/32`；链段 `10.3.{1..6}.0/30`（小号 .1）；串口 `10.3.7.0/30`；主机网 10.3.100/200.0/24（网关 .254）
- OSPFv2 单区域：每台 `router ospf 1` + `router-id 10.3.0.N`，接口级 `ip ospf 1 area 0`，transit 接口 `ip ospf network point-to-point`
- 持久化：6 台 `do write memory`（NVRAM，含 `no cdp run`，见 §6.7）；主机 `/etc/network/interfaces`（busybox 分列语法，node stop/start 自动应用）
- 快照：`baseline-iou-kernel-datapath-clean`（b6ad224b-58d8-4adb-abae-29ad7f89b6f8）

### link_id 清单

| 链路 | link_id | kernel |
|---|---|---|
| R1 e0/0 ↔ R2 e0/0（seg1） | `9ef44475-0562-4c50-8b73-219367715e26` | true |
| R1 e0/1 ↔ R2 e0/1（seg6） | `7733f5ad-208a-4b27-a199-bbf63515846a` | true |
| R2 e0/2 ↔ R3 e0/0（seg2，filter 主测链） | `393a8bba-0d7e-4a95-aabd-adc9245c8ae5` | true |
| R3 e0/1 ↔ R4 e0/0（seg3） | `8534c410-d3af-4e72-ba58-f73d7468d40c` | true |
| R4 e0/1 ↔ R5 e0/0（seg4） | `4f881e42-623c-488c-b7ad-0c292fb9d7f5` | true |
| R5 e0/1 ↔ R6 e0/0（seg5） | `510bd4ec-afff-4bf7-9d54-6d123104f66c` | true |
| R1 e0/2 ↔ host1（混合链 IOU↔docker） | `7c1e22ff-2710-47be-af46-2f672ce5c375` | true |
| R6 e0/1 ↔ host2（混合链 IOU↔docker） | `8abac282-376a-445d-a952-077b6698b2ff` | true |
| R2 S2/0 ↔ R3 S2/0（串口） | `409f12ac-83bf-44f1-9563-e587565e8004` | **false** |

## 4. kernel datapath 判定（问题 1/2）

- **7 条以太链全部 `kernel_datapath: true`**，含 **IOU↔IOU**（6 段）与 **IOU↔docker 混合**（2 条主机链）
- **串口链 `kernel_datapath: false`**（relay）——按"非以太端口逐端口排除"设计，节点其它以太端口不受影响（R2 同节点 3 条以太链仍 true）
- `link_available_filters`：kernel 链 **13 种全开放**（含 8 种 kernel-datapath 专属）；relay 串口链仅 5 种旧版（frequency_drop / packet_loss / delay / corrupt / bpf）
- 对 relay 串口链下发 kernel-only filter（gemodel）→ **HTTP 409**，报错带指引："...only run on a kernel-datapath link (tc netem on the veth host end); this link is wired on the uBridge relay — delete and recreate the link to switch it to the kernel datapath"

## 5. 路由与端到端验证

- OSPF 邻接 12/12 全 Full（R1=2、R2=3、R3=2、R4=2、R5=2、R6=1；串口不入 OSPF）
- R1 路由表：所有远端前缀双下一跳 `via 10.3.1.2 (e0/0)` + `via 10.3.6.2 (e0/1)`——双平行链 ECMP 成立
- host1→host2：100/100 收，0% 丢，**ttl=58**（6 台路由器各减 1），RTT avg **3.71ms**（min 1.69 / max 5.27 / mdev 0.71）
- 单跳基线：host1↔R1 ≈ **0.76ms**（即每个 IOU 节点的用户态转发开销 ~0.5-0.6ms/向）

## 6. Filter 实测（问题 3/4，全部【实测】）

换算规律与 Docker/QEMU 版一致：**filter 双向各生效一次**（RTT 丢包 = 1−(1−L)²，RTT delay = 2×单向）。测量方法：host1 `ping`（iputils，可 `-i 0.01` 快采样、`-D` 时间戳、DUP! 标记）；路径穿过 seg2（R2↔R3 唯一路径）。

| # | filter（seg2 除注明） | 配置 | 实测 | 理论/判定 |
|---|---|---|---|---|
| 1 | delay（host 链隔离） | [10] | RTT 21.04ms（mdev 0.10） | 2×10+基线 1.0 ✓ |
| 2 | delay（seg2） | [5] | RTT 14.27ms | 3.71+10 ✓ |
| 3 | delay（6 段全挂） | [5] | RTT 55.40ms | 3.71+2×5段×5=53.7，+1.7 见下 ✓ |
| 4 | delay+jitter+dist | [10,3,normal] | avg 23.31 / mdev 4.54 / [12.2,29.6] | 2×10+3.7；mdev≈√2×3 ✓ |
| 5 | packet_loss | [10] | 15%（100 样本） | 1−0.9²=19%（1σ 内）✓ |
| 6 | corrupt | [50] | 73.3%（60 样本） | 75% ✓ |
| 7 | frequency_drop | [3] | **55.56%**（90 样本） | 1−(2/3)²=55.56%，eBPF 精确 ✓ |
| 8 | bpf | [icmp[icmptype]==8] | 跨 seg2 100% 丢；到 R1 0% 丢 | 选择性 ✓；OSPF 邻接不动 ✓ |
| 9 | gemodel | [10,10,50] | 46%（100 样本） | 单向 p/(p+r)×(1−h)=25% → RTT 43.75% ✓ |
| 10 | rate | [512kbit] | 56B→6.64ms；1400B→49.08ms | 2×帧长×8/512k+3.7：6.8 / 48.8 ✓ |
| 11 | reorder | [50,0,10]+delay[20] | 到达序大量倒置（9→8、48→47、93→90-92…），跳队列包 RTT≈22-24ms，其余≈44.5ms；300/300 收齐 pipe 5 | reorder 生效 ✓ |
| 12 | duplicate | [20] | +36 DUP/100（个别 seq 三份） | 双向各 20%≈40 ✓ |
| 13 | quota | [20000,100]（1400B） | 前 13 帧通 → 断崖全丢 | 20000÷1442≈13.9 帧 ✓ |
| 14 | window_drop 三参 | [15000,3000,100] | seq 50–63 连丢，时间戳缺口 **3.107s**，窗外 0 丢 | outage 3000ms 精确；过时不候 ✓ |
| 15 | window_drop 四参 | [15000,3000,100,8000] | 5 个完整窗：窗长 3.0s、周期 **8.0s** 精确、窗外零丢 | 周期窗精确 ✓ |
| 16 | limit（delay[50] 对照） | limit=[10] vs [1000] | 4 路并发突发（~400pps、~20/方向在队）：limit10 丢 47-53%；limit1000 丢 0%（4×150/150） | 队列深度尾丢语义 ✓ |
| 17 | seed | host 链 packet_loss[20]+seed | §6.7 | 逐位可复现 ✓ |
| 18 | suspend（kernel 原生） | suspend=true/false | 挂起 100% 丢；恢复 0% 丢（3.5ms），邻接保持 Full | anchor admin-down ✓ |
| 19 | relay 串口 delay | [50] | RTT 121ms（基线 22ms，Δ≈99ms） | relay 旧 filter 同样双向各一次 ✓ |

### 6.1 全链 delay 叠加的轻微超加性【推断】

单段 5ms 测得 14.27（预测 13.71，+0.56）；5 段 5ms 测得 55.40（预测 53.71，+1.69，≈+0.34/段）。量级一致，判定为 qdisc 在途时 IOU 用户态转发调度的小额固定开销叠加，非 filter 不精确（host 链 10ms 段 21.04 vs 2×10+1.04 精确）。

### 6.2 seed 可复现性与 **CDP 干扰坑**（本轮新发现）

host1↔R1 静默链（无 OSPF）packet_loss[20]+seed：

| 轮次 | 操作 | 结果 |
|---|---|---|
| 1 | seed=12345 首用（CDP 开） | md5 `bb419021…` |
| 2 | seed=99999 | md5 `9335441d…`（图案不同，diff 172） |
| 3 | 换回 12345（前值 99999） | **未复现**（md5 `62b74959…`，diffvs1=101） |
| A | `no cdp run` 后 seed=54321 | md5 `ca19f5eb…` |
| B | seed=77777 | md5 `3fbea290…`（diff 156） |
| C | 换回 54321 | **与 A 逐位相同（md5 一致、diff=0）** ✓ |

结论：**关掉 CDP 后 seed 包级复现成立**（A/C 200 包图案零差异）。轮 1-3 的失败判定为 **IOS 在链路上周期性发送 CDP（及 Ethernet keepalive loop 帧）抢占 netem RNG 抽签**——FRR（docker/qemu 版）无此机制，所以是 IOU 平台特有的复现坑。捕获证据见 §6.5（pcap 中有 cdp/loop 帧）。**复现配方：先 `no cdp run`（本实验场 R1 已持久化关闭），再"换值再换回"下发 seed。**

### 6.3 window_drop 编排延迟（IOU 版复现）

MCP → console → ping 编排链 ~3-6s，start 必须留余量（本测试用 start=15000 稳过）；短 start 会整段错过窗口。与 Docker/QEMU 版同源。

### 6.4 ping 间隔下限

Ubuntu 镜像 ping `-i 0.01/-i 0.002` 实际间隔下限 ≈9.6ms（300 包耗时 2.89s）——与 QEMU/FRR 镜像 ~10ms 现象一致；压队列需并发多路（本测试 4 路 ≈400pps）。

### 6.5 链路抓包（kernel 链 capture）

`link_capture_start` → ping → `link_capture_stop`/`download` 正常；pcap 20 帧：ICMP 12、OSPF 4、**CDP 2、IOS Ethernet keepalive（loop, 0x9000）2** ——后两者即 §6.2 的 RNG 噪声源实证。

### 6.6 suspend/resume（服务端修复运行时复验）

`9d82de897 fix(iou): carry suspend from the NIO update body` 的运行时复验【实测】：挂起后跨链 ping 100% 丢（无 ICMP 错误、静默黑洞 = anchor admin-down 丢弃），恢复后立即 0% 丢；挂起时长 ~8s 内 OSPF 邻接保持 Full。若修复未生效，挂起链会继续转发（历史 bug 形态）。

### 6.7 说明

- CDP 关闭是本实验场的刻意设置（R1 全局 `no cdp run`，write memory 持久化），目的即 §6.2 的静默链；SEG 链上的 CDP 未关（不影响单链隔离实验）。
- R1/R2 的 OSPF 邻接在 >50% 丢包测试（corrupt 段）中保持 Full；frequency_drop 55% 下亦未触发 dead timer。

## 7. 性能基线（问题 6，对照 Docker/QEMU 版）

| 指标 | IOU 6 跳（本项目） | QEMU 6 跳（对照） | Docker 11 跳（对照） |
|---|---|---|---|
| host↔host RTT | **3.71 ms**（ttl=58） | 4.58 ms | 0.36 ms |
| 每跳 | ~0.62 ms（单跳 0.76ms 含主机侧） | ~0.7 ms | <0.1 ms |
| iperf3 单流 | **247 Mbps**（retr 2541） | 609 Mbps | 2.22 Gbps |
| iperf3 8 流 | **209 Mbps（反降）** | 440 Mbps（反降） | 19.4 Gbps |

结论：

- IOU 每跳开销与 QEMU 同量级（用户态转发：IOL fabric socket → uBridge 锚点 → 内核桥逐个穿帧），比 docker 高一到两个量级；**瓶颈在 IOU 用户态转发，不在 kernel datapath**（filter 精度与 docker/qemu 一致）
- 8 流反降：IOL 实例的用户态处理串行化，与 QEMU（e1000 单队列）同型，与 docker 聚合上涨相反

## 8. 坑清单（IOU 特有）

1. **CDP/keepalive 周期帧消费 netem RNG** → seed 复现必须 `no cdp run`（§6.2）
2. IOU 串口 `clock rate` 命令被镜像拒绝（`% Invalid input`），但链路 up/up、无需配置
3. IOU 重启很快（boot+OSPF 收敛 <20s，远快于 QEMU 的 ~80s）
4. `interface` 默认 `administratively down`，配置需 `no shutdown`
5. 本镜像 ping 无 `-c/-i`（IOS 语法 `repeat/timeout`）；IP 主机侧用 iputils ping 采样
6. `write memory` 首次提示 "overwrite NVRAM previously written by a different version" 属正常（确认后 [OK]）
7. `link_list` 的 `fields` 白名单不含 `kernel_datapath`（link_get/link_create 有）——MCP 层小不一致
8. 高丢包测试时注意 seg2 的 OSPF hello 会消耗 frequency_drop 的每-N 计数（相位漂移；eBPF 精确性实测不受影响，55.56% 分毫不差）

## 9. 复验、快照与 stop/start 专项

- 全部 filter 清除后基线复验：100/100 0% 丢、3.71ms、OSPF 12/12
- 快照 `baseline-iou-kernel-datapath-clean` 于全停后创建，随后 node_start_all 恢复，重启自愈验证：R1 2×Full、E2E 0% 丢 ✓
- **IOU 节点 stop/start 专项（问题 7，通过）**：重启 IOU-R-2（带 3 条 kernel 链 + 1 条 relay 串口）→ 重启后 R2 自身 3/3 Full、R1 见双平行 2×Full、R3 见 R2 Full、`link_get(seg1).kernel_datapath` 仍 true、Serial2/0 up/up 且 IP 自恢复、E2E 0% 丢。锚点（tap/bridge）在 stop 时清理、start 时重建、链路重挂，自愈无残留问题

---

*Built & verified 2026-10-01 via GNS3 MCP（filter/节点/链路控制与设备操作全程走 MCP；流量采样经本地 console TCP + host 侧脚本）。数据面结论均为实测；源码线索与对照版数据已标注来源。*
