# Kernel-DataPath 性能与 Packet Filter 汇总（跨场地口径统一）

> 汇总日期：2026-10-04
> 性质：**二手汇总文档**——本文所有数据转引自 §0 列出的实验记录（各记录内标注为实测），本文未新跑任何实验；引用处保留原记录的【实测】/【推断】标注。
> 一句话结论：**四类节点（docker/qemu/iou/dynamips）的以太链全部走 kernel datapath、13 种 filter 跨平台精确；性能差异全部来自各平台"本体"（VM 穿越 / 用户态转发 / 指令模拟 / 转发进程），与 kernel datapath 无关。**

---

## 0. 来源与口径说明

本文来源（均为本仓库文档）：

| 场地 | 文档 |
|---|---|
| Docker 11×FRRDocker | [Packet-Filter-Test 方案与实施记录](Packet-Filter-Test-方案与实施记录.md) + 项目 README（`Docker-Kernel-DataPath-test-FRRDocker`） |
| QEMU 11×FRR-qemu（e1000 / virtio） | [QEMU-Kernel-DataPath-Test 方案与实施记录](QEMU-Kernel-DataPath-Test-方案与实施记录.md) |
| IOU 11×Cisco IOU | [IOU-Kernel-DataPath-Test 方案与实施记录](IOU-Kernel-DataPath-Test-方案与实施记录.md) |
| Dynamips 11×c7200 | [Dynamips-Kernel-DataPath-Test 方案与实施记录](Dynamips-Kernel-DataPath-Test-方案与实施记录.md) |
| 混合节点 + Ethernet switch | [Mixed-Kernel-DataPath-Test 方案与实施记录](Mixed-Kernel-DataPath-Test-方案与实施记录.md) |
| SRL/FRR/XRd 混合 NOS 6-hop | [Kernel-DataPath-Docker-MixedNOS 方案与实施记录](Kernel-DataPath-Docker-MixedNOS-方案与实施记录.md) |

口径注意：

1. **跨会话绝对 RTT 仅指示性**（不同会话宿主负载不同，IOU 文档明示；同会话内相对结论自洽）。
2. 各文档"每跳"的推导口径略有差异（有的=RTT/跳、有的=单向/跳、有的来自不同节点数的测量），**跨行对比只看数量级**，精确对比用同表同场数据。
3. 6 节点版数据为历史基线（QEMU/IOU/Dynamips 均已原地扩为 11 节点，旧快照保留可回滚）。
4. ping 设备接口地址测的是**本地响应**而非转发路径（MixedNOS 方法论教训）；凡"过路流量"吞吐/时延测量均在表中注明路径。

---

## 1. 实验矩阵总览

| 项目（project_id） | 载体 | 规模 | 建成 | 数据面实现 |
|---|---|---|---|---|
| `Docker-Kernel-DataPath-test-FRRDocker`（d1ab2349） | FRRDocker 容器（FRR 10.3） | 11 节点 / 10 段中转 | 09-30 | veth + 宿主内核桥 |
| `Kernel-DataPath-Qemu-FRRqemu`（2e2db147） | FRR-qemu（e1000，Alpine） | 6 → 11 节点 | 09-30 / 10-04 扩 | `-netdev tap` 直挂宿主 tap |
| `Kernel-DataPath-Qemu-FRRqemu-virtio`（7f9cec92） | 复制场，virtio-net-pci | 11 节点 | 10-04 | 同上（网卡 A/B 用） |
| `Kernel-DataPath-Iou-CiscoIOU`（9c00ff33） | Cisco IOU L3 | 6 → 11 节点 | 10-01 / 10-04 扩 | `iol_bridge add_nio_tap` 锚点 |
| `Dynamips-Kernel-DataPath-test-Cisco7200`（796d08d4） | c7200（IOS 15.2(4)M11） | 6 → 11 节点 | 10-01 / 10-04 扩 | 每以太口持久 TAP 锚点 |
| `Mixed-Kernel-DataPath-Test`（bc54cfdf） | 7 种节点 + Ethernet switch | 9 节点 / 9 链 | 10-04 | 混合（含 switch 端口） |
| `Kernel-DataPath-Docker-MixedNOS`（b322be35） | SRL + FRR + XRd 交错 docker | 14 节点 / 13 链 | 10-04 | 全 docker kernel 链 |

四场 11 节点实验场逐段同构：11 节点线形链、seg1/seg2 为 1↔2 双平行 ECMP、两端 Ubuntu 主机、OSPFv2 单区 22/22 Full、ttl=53（64−11）、traceroute 11 路由器跳。

---

## 2. kernel datapath 判定与 filter 支持（跨场实测）

| 链路/节点类型 | 以太链 kernel | 串口链 | 开放 filter 数 |
|---|---|---|---|
| Docker 节点（FRRDocker / Ubuntu / SRL / XRd / IOL-XE） | ✅ true | — | 13/13 |
| QEMU 节点（e1000 / virtio 同） | ✅ true（tap 直挂） | — | 13/13 |
| IOU 节点 | ✅ true（iol_bridge tap 锚点） | ❌ false（relay） | 以太 13 / 串口 5 |
| Dynamips 节点 | ✅ true（持久 TAP） | ❌ false（relay） | 以太 13 / 串口 5 |
| Ethernet switch 端口 | ✅ true（842f1eecb 起，含 switch↔switch） | — | 13/13 |
| 跨类型混合链（qemu↔docker、dynamips↔docker、IOU↔docker、SRL↔FRR↔XRd） | ✅ true | — | 13/13 |

- **13 种 filter**：frequency_drop / packet_loss / delay / corrupt / bpf / rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop（后 8 种为 kernel-only）。
- **relay 链（串口）仅 5 种旧版**：frequency_drop / packet_loss / delay / corrupt / bpf；下发 kernel-only → HTTP 409 带指引（删链重建可转 kernel）。
- `link_available_filters` 是某 filter 在**当前链路**可用性的权威答案。

---

## 3. 转发性能

### 3.1 11 节点同构场总表（host↔host，ttl=53，均转引自各场实测）

| 载体 | RTT avg | 每跳（记录原文口径） | iperf3 单流 | 多流形态 | 瓶颈判定 |
|---|---|---|---|---|---|
| **Docker FRRDocker** | **0.36 ms** | <0.1 ms | **2.22 Gbps**（cwnd≈200KB/RTT 限制） | 16 流 19.4 G / 32 流 20.2 G（聚合；全链共享瓶颈 ≈20 G） | 不塌：宿主内核路径 |
| **QEMU e1000** | **6.63 ms** | ~0.6 ms | **342 Mbps**（274 retr） | 4/8/16/32 流 = 168/206/171/147 M（**反降**） | VM 边界 + e1000 每包全额付费 |
| **QEMU virtio-net-pci**（复制场） | 6.03 ms | ~0.55 ms | **1.73 Gbps**（×5.1） | 4–16 流 ≈1.70–1.75 G（**持平**），32 流 1.52 G（×10） | 换卡解决吞吐不解决时延 |
| **IOU** | **1.91 ms**（0.87/1.91/3.88/0.51） | ~0.62 ms | **126 Mbps**（1541 retr） | 8 流 **272 M 聚合**（×2.2，较 6 节点版"反降"反转） | IOL 用户态转发串行化 |
| **Dynamips c7200** | **521 ms**（364/521/635/74） | ~45 ms | **524 Kbps 发 / 114 K 收** | 8 流 629 K/69 K | MIPS 模拟 + idle-sleep（30ms 片）；TCP RTO 崩塌 |

Docker 场补充（项目 README 实测）：并发双源（host1+host3 各 16 流）9.60+10.5=20.1 Gbps **共享不叠加**；1 跳直连（仅过 FRR-1）单流 9.8 G / 16 流 73.9 G（宿主内存路径上限）。

Docker 场 delay×吞吐曲线（eth5+eth6 双平行链同档 delay）：

| delay/链 | RTT | 单流 | 16 流 |
|---|---|---|---|
| 0 ms | 0.36 ms | 2.22 Gbps | 19.8 Gbps |
| 1 ms | 2.26 ms | 1.64 Gbps | 3.78 Gbps |
| 5 ms | 10.5 ms | 883 Mbps | 1.03 Gbps |
| 10 ms | 20.5 ms | 466 Mbps | 614 Mbps |
| 20 ms | 40.7 ms | 262 Mbps | 388 Mbps |

QEMU 场同实验（seg1+seg2 同档 delay）：0/1/5/10/20 ms → 单流 342/326/309/262/206 M、RTT 6.63/8.15/16.78/27.13/47.28 ms——**单流对 RTT 不敏感（仅降 40%）**，Docker 场同区间降 88% ⇒ 两者瓶颈不同源（见 §3.4）。

### 3.2 6 节点历史基线（扩链前）

| 指标 | QEMU 6 | IOU 6 | Dynamips 6 |
|---|---|---|---|
| host↔host RTT | 4.58 ms（ttl=58） | 3.71 ms（ttl=58） | ~234 ms（ttl=58） |
| 单流 | 609 Mbps | 247 Mbps（2541 retr） | 524 K / 259 K |
| 多流 | 16 流 440 M（反降） | 8 流 209 M（反降） | 16 流 559 K / 167 K |
| 全链 delay 5ms 单流 | 317 Mbps | — | — |

### 3.3 单节点 / 单穿 / 短路径（归因测量）

| 测量 | 路径 | 吞吐 | 延迟 | 出处 |
|---|---|---|---|---|
| docker↔docker 直连基线 | 零路由器（veth+内核桥） | **12.7–12.8 Gbps** | 0.067–0.099 ms | Mixed / MixedNOS |
| 经 Ethernet switch（docker↔docker） | Switch1 纯 L2 | 12.8 Gbps（无损） | 0.05–0.9 ms | Mixed |
| **纯 XRd 段** | A — XRd-2 — U-R6 | **740 Mbps** | ~0.37 ms/单穿 | MixedNOS |
| **纯 SRL 段** | A — SRL-1 — U-R1 | **62 Mbps**（≈5.2kpps@1500B） | ~0.15 ms/单穿 | MixedNOS |
| FRR docker 全链 11 跳 | 线形链 | 2.2 Gbps | 0.36 ms（~0.016 ms/跳，原文口径） | Docker README / MixedNOS |
| 混合 NOS 6-hop 全链 | S-F-X-S-F-X | 66 Mbps | 3.13 ms（≈0.52 ms/跳） | MixedNOS |
| IOU 单跳（host↔R1） | 用户态转发 | — | ~0.76 ms（6 节点版） | IOU |
| QEMU VM 穿越（virtio 阶梯） | 每 +1 转发 VM | — | **RTT +0.62 ms（单向 0.31 ms/穿越）** | QEMU §11.5 |
| 交换机段 RTT（U1 ping 各节点接口） | 经 Switch1，1 L2 跳 | — | R1(dynamips) 24.7 / FRR 0.08 / IOU 0.46 / IOL-XE 0.68 / SRL 1.83 / XRd 0.87 / U2 0.87 ms | Mixed（含设备本地响应，非纯转发） |

MixedNOS 归因阶梯（probe 主机法，全部串行实测）：

| 阶梯 | 路径 | 吞吐 | RTT |
|---|---|---|---|
| L0 直连基线 | A ↔ U-R1，零路由器 | **12.7 Gbps** | 0.099 ms |
| L1 纯 XRd | B — XRd-2 — U-R6 | **740 Mbps** | 0.84 ms |
| L2 纯 SRL | A — SRL-1 — U-R1 | **62 Mbps** | ~0.4 ms |
| M1~M6 深阶梯 | A → U-R1 … A → U-R6（1~6 hop） | 61~81 Mbps 全平坦 | — |
| 全链 6 hop | A — S-F-X-S-F-X — B | 66 Mbps | 3.1 ms |

### 3.4 归因结论（各记录原文判定）

1. **慢在各平台本体，不在 kernel datapath**：filter 精度跨 docker/qemu/iou/dynamips 完全一致（见 §4），而每跳延迟差 3 个数量级（docker <0.1ms → dynamips ~45ms）。
2. **QEMU 归因定案**：docker↔docker 过同机制内核桥仅 0.067 ms ⇒ 每跳 ~0.6 ms 几乎全是 **QEMU VM 穿越**（tap I/O 唤醒主循环 + KVM 进出 + guest 栈）；uBridge/内核桥 <0.1 ms 无责；kernel-datapath 链 uBridge 不逐包泵包。
3. **virtio vs e1000**：吞吐 ×5–10、延迟几乎不变（6.63→6.03 ms）——成本按"每次唤醒"计（virtio 靠 GSO/TSO 64KB 超帧摊薄 ~44 倍；e1000 无 offload 每包付费）【推断，数值自洽】；**vCPU 1→2 + RAM 512M 实测无收益反降 10–15%**，最优已知配置 = virtio + 1 vCPU / 256MB。
4. **Dynamips 慢在 hypervisor 本体**：每跳 ~45 ms 与模板 idle-sleep（30 ms 片）量级一致；relay 串口链每跳 ~49 ms（对照实测）同量级，排除 datapath 因素；进程 CPU 仅 ~4.7%（idlepc 生效）。
5. **SRL 容器是 docker 混合场唯一吞吐瓶颈**（一次穿越 12.7G→62M，200 倍降幅；多流不涨 + 阶梯平坦 = 固定每包瓶颈）；但只塌吞吐不塌延迟（0.15 ms/穿 < XRd 0.37 ms）。
6. **交换机 L2 转发本身无性能问题**；其 filter 曾静默失效（见 §4.4），已于 10-04 修复。

---

## 4. Packet Filter 实验数据

### 4.1 支持矩阵与语义

| 链路类型 | 支持 | 语义 |
|---|---|---|
| kernel datapath 以太链（docker/qemu/iou/dynamips/混合链/switch 链） | **13/13** | **双向各生效一次**：RTT 丢包 = 1−(1−L)²、RTT delay = 2×单向 |
| relay 链（串口/旧路径） | **5 种**（frequency_drop / packet_loss / delay / corrupt / bpf） | kernel-only → 409 带指引 |
| **switch 终结链（10-04 修复后）** | 13/13 | **单侧单向**：delay[50] → RTT **+50ms**（非 +100）；frequency_drop[3] 有效丢包 ≈1/3（非 55.6%）。端点顺序无关、stop/start 持久、清空可回基线 |

### 4.2 换算公式（后续实验直接用）

| 类别 | 公式 |
|---|---|
| 丢包类（loss/corrupt/frequency/gemodel/quota/window/bpf） | **RTT 丢包 = 1−(1−L)²**（L = 单向失效率） |
| delay | **RTT = 2×delay**（实测精确到 0.1 ms） |
| delay+jitter | **mdev ≈ √2 × jitter**（双向各摊一次抖动） |
| rate | **RTT ≈ 2×(帧字节数×8÷rate)**，帧 = IP 包长 + 14B 以太头（84B ping → 98B） |
| gemodel（新语义） | 单向 L = **p/(p+r)×(1−h)**（p=good→bad、r=bad→good、1−h=坏态丢包率） |
| frequency_drop | 单向 L ≈ 1/N（近似；链上其它流量推进计数器致相位漂移） |

### 4.3 13 种 filter 逐项实测（按类型横向对照）

**丢包 / 损伤类**

| filter | 配置 | 理论（往返） | Docker 11（09-30 全量） | QEMU 11（6 节点版补测） | IOU 11（6 节点版补测） | Dynamips 11（6 节点版补测） |
|---|---|---|---|---|---|---|
| packet_loss | [10] / [30] | 19% / 51% | [30]→**56%±7%**（n=50） | **20.5%**（200 包；100 包样本 12%） | 15%（100 包，1σ 内） | **19.0% 分毫不差**（200 包） |
| frequency_drop | [3] | 55.56% | 61.9%（n=21）；直连链复验 55.33% | **56%**（100 包） | **55.5%**（89/200） | 58% / 56%（两轮 200 包） |
| corrupt | [30] / [50] | 51% / 75% | 53.3%（n=15） | 84%（100 包） | 73.3%（60 包） | 33%（20/60，1.5σ 内；旁证 OSPF 校验和错） |
| bpf | icmp echo req | 100% 丢 | 100%，OSPF 邻接不动 | 100%（10/10） | 0/20（选择性，邻接 Full） | 0/10（选择性） |
| gemodel | [10,10,50] | 43.75% | [100,10,10]→23.8%（n=21，预测 17.4%）；[10,30,100]→51.6%（预测 43.75%） | 47%（100 包） | 46%（100 包） | 66% / 64%（突发方差大，如实记录） |
| duplicate | [20] / [50] | +44% / DUP | [50]→15 收 +11 DUP（最多 3 份） | **+43%**（200 包；100 包曾 +64%） | **+43%**（+86/200；100 包 +36） | **+45%**（+90/200；100 包曾 +62%） |
| quota | [20000,100]，1400B | ≈13.9 帧断崖 | [2000,100]→前 15 通→全丢 | 前 13.9 帧断崖 | 前 13 帧断崖 | 前 14 帧断崖 |

**时延 / 速率 / 队列 / 随机类**

| filter | 配置 | 理论 | Docker 11 | QEMU 11 | IOU 11 | Dynamips 11 |
|---|---|---|---|---|---|---|
| delay | [50]（6 节点版用 [5]/[10]） | 2×单向 | **100.18 ms**（mdev 0.095） | [10]→27.47 ms（基线 6.63） | 单跳 100/101/102 ms（基线 1 ms） | avg 131 ms（基线 37） |
| delay+jitter | [10,3,normal] / [50,20,normal] | mdev≈√2×j | [50,20] mdev **27.2**（理论 28.3） | avg 24.8 / mdev 4.9 | avg 23.31 / mdev **4.54** | 20/59/96 ms |
| rate | [512kbit] / 1400B | 2×帧长序列化 | [64k]→24.68 ms；[256k]→6.24 ms | 53.24 ms（56B→9.59） | 45 ms（56B→6.64） | avg 90 ms |
| reorder | [50,0,10]+delay | 倒置 + RTT 双峰 | [50,25,5]→18.75% 单腿，RTT 双峰 50/100 | 有序→大量倒置，300/300 收齐 | 大量倒置，300/300，pipe 5 | 100/100 收齐，8 处倒置 |
| limit | [10] vs [1000] | 队列深度尾丢 | —（09-30 版叠加组合验证） | limit10 丢 73–80%；limit1000 丢 0% | 47–53% vs 0% | 74–77% vs 0% |
| window_drop 三参 | [15000,3000,100] | 精确 outage | [8000,6000,100]→**精确 6 连丢** | 3.0 s 精确（30 连丢） | 3.107 s 缺口 | 3.145 s 黑洞 |
| window_drop 四参 | [·,3000,100,8000] | 周期 8 s | [5000,3000,100,10000]→每周期 3 s 分毫不差 | **8.000 s 周期精确**（4 完整窗） | **8.0 s 精确**（5 窗） | 8.17/7.90/8.02 s（4 窗） |
| seed | 配合 loss | 包级可复现 | —（含 window_drop 同值重设修复） | 换值再换回**逐位相同（md5 一致）**；同值重设 no-op | **需先 `no cdp run`** 才复现 | A/C **diff=0** |
| suspend | true/false | 链路黑洞/恢复 | — | — | 原生 anchor admin-down：100% 丢 → 恢复 0% 丢 | 挂起 0/5 → 恢复 5/5 |
| relay 串口 delay | [50] | 2×（relay 也双向） | — | — | Δ≈99 ms（基线 22 ms） | Δ≈100 ms（基线 4/49/64） |

其他场景实测：多 filter 可叠加（delay+packet_loss+seed+limit 同链同时生效互不干扰）；全链 6 段同挂 delay[5]（QEMU）RTT 53.85 ms ✓、11 段各 [10]（Dynamips）min Δ=+217 ms ≈ 理论 +200 ✓、6 段 [5]（IOU）55.40 ms ✓。

### 4.4 交换机链专项（Mixed-Kernel-DataPath-Test，10-04）

- **修复前（现场，已作废）**：经 Switch1 的 8 条上行链全部 `kernel_datapath: true`、13 种 filter 全开放、API 回显设置值，但**数据面零效果**——delay[50]×6 / bpf[icmp] / frequency_drop[-1]（全丢）均无任何影响，`link_reset` 无效；而**同项目直连链（U1↔U2）同 filter 精确生效** ⇒ 缺陷定位为"凡链路一端是 ethernet_switch 节点，filter 静默失效"。
- **修复方式（转述团队）**：kernel datapath mixin 单点 ownership 门控（对端不再对共享锚点做破坏性 reconcile）；2110 单测 + 378s 全量 e2e 通过。
- **修复后复验（实测）**：delay[50] → 50.1 ms 稳定（mdev 0.034，含 switch-first 原故障顺序）；bpf[icmp] → 100% 丢；frequency_drop[3] → 40%/30%（合计≈1/3）；清空回基线、stop/start 持久、删建重建正常、端点顺序无关、直连链无回归（100.27 ms = 2×）。
- **收尾基线（U1 经交换机 ping）**：R1(dynamips) 24.7 / FRR 0.08 / IOU 0.46 / IOL-XE 0.68 / SRL 1.83 / XRd 0.87 / U2 0.87 ms；直连链（docker↔docker）0.067 ms / 12.8 Gbps。

### 4.5 读数据必读的方法论坑（汇总自各场）

1. **样本量 ≥200 再下结论**：packet_loss[10] 100 包测 12% / 200 包 20.5%；duplicate[20] 50 包 +64% / 200 包 +43%；Dynamips 100 包 +62% / 200 包 +45%。
2. **window_drop "过时不候"**：start 自 filter 生效时刻起算；MCP→console→ping 编排链 3–10 s ⇒ start 留 **≥15 s** 余量，或改用四参周期形态；同值重设短路已修（window_drop 集合开例外，可直接"重来"）。
3. **seed 同值重设是 no-op**（RNG 不重置）⇒ 复现配方 = **换值再换回**（或先清空 filters）。
4. **CDP/keepalive 帧消耗 netem RNG**：IOU 需先 `no cdp run` 才能包级复现（CDP 干扰坑）；Dynamips pcap 亦见 cdp/keepalive（该场 R1 已持久化关 CDP）。
5. **静默链方法论**：干净 filter 实验用无 IGP 的 host 链（临时 `passive-interface`），避免 OSPF hello 掺入计数器/RNG。
6. **高丢包 ARP 黑障**：`Destination Host Unreachable` 由本机生成（ARP 自身被 filter 掉），统计丢包率时剔除。
7. **高丢包打断 OSPF 邻接**（4 连丢 hello 触发 dead timer，~40 s 自愈）；corrupt 50% 会震荡邻接，测完等收敛再测下一项。
8. **frequency_drop 相位漂移**：every-N 计数器对链上全部帧计数（OSPF hello/keepalive/CDP 混入），精确验证需静默链。
9. 测量工具坑：ping 间隔下限 ~10 ms（压队列需并发多路）；`ping -O` 在发送间隔 < RTT 时误报；`rate` 反推必须用二层帧长（IP+14B，用 IP 长度会系统性偏低 ~14%）；dynamips console 回放取**末条** summary；长 ping 走本地 console TCP。

---

## 5. 已作废的旧结论（勘误，勿引用）

| 旧结论 | 现状 | 依据 |
|---|---|---|
| switch↔switch 回落 relay（仅 5 种 filter） | **作废**：现 kernel true + 13 种 | Mixed §4（842f1eecb 上现场复核） |
| IOL-XE docker 链路恒 relay | **作废**：现 kernel true + 13 种 | Mixed §4 |
| IOU 以太链不支持 delay/corrupt | **作废**：13 种全支持且实测精确 | IOU 文档 |
| 交换机终结链路 filter 静默失效 | **已修复**（ownership 门控），现精确生效；语义=单侧单向 | Mixed §5.4 |
| "ping 路由器接口可测转发路径" | **作废**：本地响应非转发，归因须用 probe 过路流量 | MixedNOS §5 |

---

## 6. 出处索引

- 生成命令/口径细节、node_id/link_id 清单、快照名：见各场《方案与实施记录》§3/§10 与项目 README。
- 快照：Docker `baseline-*`（见项目 README）、QEMU `baseline-qemu-kernel-datapath-11node-clean`（bb39ce6d，6 节点旧 `3da371d3` 保留）、virtio `baseline-qemu-virtio-clean`（e7c68594）、IOU `baseline-iou-kernel-datapath-11node-clean`（7d94a923）、Dynamips `baseline-dynamips-kernel-datapath-11node-clean`（4f259e7b）、Mixed `baseline-mixed-kernel-datapath-clean`（500704a7）、MixedNOS `baseline-mixednos-6hop-with-probes`（ad69c9b6）。

---

*本文为 2026-10-04 跨场地汇总（数据转引自 §0 各实验记录，未新跑实验）。如需单个结论的原始输出，请回溯对应记录。*
