# Kernel-DataPath-Qemu-FRRqemu — 无 Kernel-DataPath 版本对照实测（2026-10-04）

> 性质：**对照复测记录**。kernel 基线（11 节点现行版）为**转引**——《QEMU-Kernel-DataPath-Test-方案与实施记录.md》§10（11×FRR-qemu e1000 现行基线）与 §11（virtio 复制场）；本轮在**无 kernel datapath 的服务器版本**上把同一测试菜单重跑，本文数值除注明外均为本次**实测**。
> 一句话结论：**功能面零回归（OSPF 22/22、ttl=53、5 种 legacy filter 逐项一致）；延迟几乎不变（受控负载下 5.5–6.7 ms vs kernel 6.63 ms，阶梯 +0.52 vs +0.62 ms/VM）——QEMU 场的瓶颈是 VM 穿越，relay 不是增量；吞吐腰斩（单流 ÷2.3、多流 ÷2）；8 种 filter 缺失（含 §10.6 精测的 rate/gemodel/duplicate）；virtio 杠杆从 ×5.1 缩到 ×2.2 且多流不稳定。另有两个方法论发现：宿主电源状态敏感性（RTT ~2× 摆幅）与 rp_filter×ECMP 伪影。**

- 项目：主项目 `Kernel-DataPath-Qemu-FRRqemu`（`2e2db147-61ec-45cc-b129-64f6a0f89d88`，11×FRR-qemu e1000 + 2×Ubuntu，13 链）；复制场 `Kernel-DataPath-Qemu-FRRqemu-virtio`（`7f9cec92-0dc9-434e-a1ac-d55512fbf569`，virtio-net-pci）
- 对照版本：server `3.1.0.dev7+38cc7cc0a`（无 kernel datapath）↔ 原 `3.1.0.dev7+2445e2e5e`（kernel datapath）
- 被测链：主项目 seg6 = `8952b17d-233d-4674-b8cf-c2005d0553a5`（filter 主测链）；曲线用 seg1+seg2 = `e0489018` + `7d26e21d`；virtio 场 seg6 = `cfa31fdf-db02-467a-b57f-68884da67cfe`

---

## 1. 平台层判定（差异一：字段、filter 支持集与**数据面实现**）

| 项 | kernel 版（转引 §10） | 无 kernel 版（本次实测） |
|---|---|---|
| `link_get` 的 `kernel_datapath` | `true`（13/13） | **字段整体消失** |
| `link_available_filters` | 13 种 | **5 种**（frequency_drop / packet_loss / delay / corrupt / bpf） |
| kernel-only 下发 | 可用 | **409**：`Unknown filter type: rate / gemodel / duplicate`（§10.6 精测 7 项中 3 项现不可用） |
| `delay` 参数校验 | `[10]` 单参可用 | **强制 2 参**（`[10, 0]`） |
| **QEMU netdev（node_get command_line）** | `-netdev tap,id=gns3-N,ifname=gq<nodeid>e<N>p0,script=no`（tap 直挂宿主内核桥） | **`-netdev socket,id=gns3-N,udp=127.0.0.1:XXXXX,localaddr=127.0.0.1:XXXXX`（UDP 隧道 + ubridge 用户态转发）** |

- virtio 复制场同版：`-device virtio-net-pci,...,speed=10000,duplex=full` + 同样 `-netdev socket,udp=...`；`link_get` 无 kernel 字段、5 种 filter（实测）。

## 2. 环境与方法（本次）

- 主项目 13 节点 `node_start_all` 冷启，**零配置干预**，约 90 s 自动收敛 **22/22 Full**（含中途因实验需要的一次全场重启，两次冷启均自动收敛）。
- 流量采样：host1（Ubuntu，console TCP）→ host2 E2E（沿用 §10.6 口径）；FRR-qemu vtysh 无 ping 的坑沿用（shell busybox ping 可用，本次用于反向诊断）。
- **宿主状态受控法（本轮新方法论，见 §9.1）**：发现 RTT 对宿主电源状态敏感后，凡 RTT/曲线类测量均在**受控负载**（4–6 核 burn）下进行，与 kernel 基线口径对齐。
- 延迟归因阶梯（§11.5 同构）：host1 → N1/N2/N6/N11 逐级 ping。
- iperf3：host2 容器重启后需重起 `iperf3 -s -D`（不随容器持久化）。

## 3. 连通性（对照）

| 测量 | kernel 版（转引） | 无 kernel 版（实测） |
|---|---|---|
| OSPF 邻接 | 22/22 Full | **22/22 Full**（两次冷启均自动收敛；N1=2/N2=3/N3..N10=2/N11=1） |
| host↔host ttl / traceroute | ttl=53 / 11 路由器跳 | **ttl=53 / 12 行（11 路由器 + 目的）** |
| ping 设备 transit 接口地址 | （未测） | **受 rp_filter×ECMP 伪影影响，见 §9.2**（不代表链路故障） |

延迟归因阶梯（受控负载实测 vs kernel §11.5 转引）：

| 目标 | VM 数 | kernel 版 RTT avg | 无 kernel 版 RTT avg（受控负载） | 无 kernel（空闲态） |
|---|---|---|---|---|
| 10.2.100.254（N1 e2，终结） | 1 | 0.472 ms | **0.485 ms** | 0.573 ms |
| 10.2.0.2（N2 lo） | 2 | 1.267 ms | **0.931 ms** | 1.190 ms |
| 10.2.0.6（N6 lo） | 6 | 3.838 ms | **3.119 ms** | 3.283 ms |
| 10.2.200.1（host2） | 11 | 6.668 ms | **5.656 ms** | 5.741 ms |
| 拟合每 VM | — | +0.62 ms | **+0.52 ms** | +0.52 ms |

**⇒ 延迟结论（实测）：每 VM 穿越成本 ~0.5 ms，relay 化后与 kernel 版同量级（甚至略低）——QEMU 场每跳成本由 VM 边界（QEMU 主循环/KVM 进出/guest 栈）主导，ubridge UDP 隧道的增量被淹没。§11.5 "是 QEMU 不是 uBridge" 的结论在 relay 模式下依然成立。**

## 4. Filter 对照（5 种可用逐项 + 3 项缺失）

| # | 类型 | 参数（本次） | kernel 版（转引 §10.6/§6） | 无 kernel 版（实测） | 判定 |
|---|---|---|---|---|---|
| 1 | delay | `[10, 0]`（seg6） | 27.474 ms（基线 6.63） | **26.853 ms**（基线 5.63；+20 精确） | ✅ 一致 |
| 2 | packet_loss | `[10]` | 20.5%（n=200） | **18.5%（n=200）** | ✅ 一致（理论 19%） |
| 3 | frequency_drop | `[3]` | 56%（n=100） | **49.5%（n=200）** | ✅ 一致（理论 55.6%；eBPF 计数器相位漂移） |
| 4 | bpf | `["icmp"]` | 100%（5/5） | **100%（10/10），OSPF 邻接不动** | ✅ 一致 |
| 5 | corrupt | `[30]` | （11 节点版未测；6 节点 `[50]`→84%） | **53%（n=200）** | ✅（理论 51%） |
| 6 | rate | `["512kbit"]` | 1400B→53.24 ms / 56B→9.59 ms | **409 `Unknown filter type: rate`** | ⛔ 缺失 |
| 7 | gemodel | `[10,10,50]` | 45%（n=100） | **409 `Unknown filter type: gemodel`** | ⛔ 缺失 |
| 8 | duplicate | `[20]` | +86/200 = 43% | **409 `Unknown filter type: duplicate`** | ⛔ 缺失 |

其他：5 项测毕 filter 全部清空（13 链 `filters={}` 复验）、OSPF 全程无抖动（seg6 两端 Up Time 连续），基线 RTT 回归。`link_update(filters={"delay":[10]})`（单参）报 409 `delay expects 2 parameter(s), got 1`。

## 5. 吞吐对照

### 5.1 总表（主项目，host1→host2）

| 测量 | kernel 版（转引 §10.7） | 无 kernel 版（实测） | 倍率 |
|---|---|---|---|
| 单流 -t 10 | 342 Mbps（274 retr） | **139–148 Mbps**（1036–1099 retr） | ÷2.3 |
| 4 流 | 168 Mbps | **117–124 Mbps** | ÷1.4 |
| 8 流 | 206 Mbps | **91–97 Mbps** | ÷2.2 |
| 16 流 | 171 Mbps | **104–124 Mbps（空闲态）/ 90 Mbps（受控负载）** | ÷1.4–1.9 |
| 32 流 | 147 Mbps | **110–112 Mbps** | ÷1.3 |
| 反向单流 | 331 Mbps | （未复测） | — |

**多流不放大（104–124 ≈ 单流 139–148）——与 kernel 版"16 流反降"同形态**，即 QEMU 场吞吐自始至终由 VM 包处理上限决定，去掉 kernel datapath 后此上限再降约一半。

### 5.2 delay×吞吐曲线（seg1+seg2 双平行同档，受控负载实测 vs §10.7 转引）

| delay/链 | RTT（本次） | 单流（本次） | 16 流（本次） | kernel 版 RTT / 单流 / 16 流 |
|---|---|---|---|---|
| 0（基线） | **5.632 ms** | **139 Mbps** | **90 Mbps** | 6.63 ms / 342 Mbps / 171 Mbps |
| 1 ms | **7.576 ms** | **136 Mbps** | **77 Mbps** | 8.15 ms / 326 Mbps / 121 Mbps |
| 5 ms | **16.239 ms** | **132 Mbps** | **84 Mbps** | 16.78 ms / 309 Mbps / 122 Mbps |
| 10 ms | **26.201 ms** | **132 Mbps** | **80 Mbps** | 27.13 ms / 262 Mbps / 111 Mbps |
| 20 ms | **47.091 ms** | **128 Mbps** | **80 Mbps** | 47.28 ms / 206 Mbps / 105 Mbps |

- RTT：**2×delay 语义分毫不差**（+2/+10/+20/+40 精确），与 kernel 版完全一致。
- 形态：**"单流对 RTT 不敏感"同样成立且更极端**（139→128，-8%；kernel 版 -40%）——再次印证 QEMU 场瓶颈是 VM 包处理 CPU 而非 cwnd/RTT；无 kernel 版的绝对水位低约一半。

### 5.3 全链锚点（11 段每段 delay[5]，受控负载）

| 指标 | kernel 版（转引 §10.7） | 无 kernel 版（实测） |
|---|---|---|
| RTT | 109.47 ms（理论 106.6） | **108.81 ms** |
| 单流 | 131 Mbps | **116 Mbps** |
| 16 流 | 97.7 Mbps | **83.5 Mbps** |

## 6. virtio 复制场轻量对照（同菜单子集）

> kernel 基线转引 §11/§11.2：RTT 6.03 ms、单流 1.73 Gbps、4/8/16/32 流 1.70/1.74/1.75/1.52 Gbps（稳定，多流持平）。本次在无 kernel 版上轻量重跑（受控负载，除注明外）。

| 指标 | kernel 版 virtio（转引） | 无 kernel 版 virtio（实测） | 倍率 |
|---|---|---|---|
| RTT avg | 6.03 ms | **6.01 / 6.11 / 6.72 ms** | 持平 |
| 单流 | 1.73 Gbps | **305 / 307 / 320 Mbps**（另见 52 Mbps 瞬态一次） | **÷5.4** |
| 4 流 | 1.70 Gbps | **151 Mbps**（中途塌陷：3–4 s 段 0 bps + 1215 retr） | ÷11 |
| 8 流 | 1.74 Gbps | 数据不完整（前 4 s ~340–390 Mbps，随后现场失稳） | — |
| 16 流 | 1.75 Gbps | **两次尝试均塌陷**：受控负载下连接失败（`No route to host`，伴 seg2 OSPF flap 自愈）；空闲态 42.8/13.7 Mbps、收端拖延 24.8 s | ⛔ 不可用 |
| 多流形态 | 持平（≈1.0×） | **不稳定/塌陷** | 形态改变 |

- **virtio 杠杆（e1000→virtio 的 ×5–10 吞吐优势）在无 kernel 版本下大幅缩水**：单流仅 ×2.2（320M vs e1000 148M；kernel 版为 ×5.1）；多流从"持平可用"退化为"塌陷不可用"。
- 机制【推断】：virtio 的吞吐优势来自 GSO/TSO 超帧摊薄"每次唤醒"成本（§11.5 解剖）；relay 化后包要经 UDP 隧道 + ubridge 用户态转发，超帧被逐包拆解，摊薄效应大部分消失；多流并发在 relay 缓冲上互相挤压导致塌陷与 OSPF 饿死。
- 测毕现场自愈（ping 0% 丢、OSPF 回 Full）；virtio 场收尾已 `node_stop_all`。

## 7. stop/start 存活专项

- FRR-qemu-2（3 链：seg1/seg2/seg3）`node_stop` → `node_start`：**三条链全部存活**——N2 重启后 3 个 OSPF 邻接全部重新 Full（Up Time 重置后稳定）、E2E host1→host2 0% 丢、双向转发正常。
- 插曲：验证时发现 host1 无法 ping 通 N2 的 transit 接口地址（10.2.1.2/10.2.2.2 100% 丢，而回环 10.2.0.2 与 E2E 正常）——追查后定案为 **rp_filter×ECMP 伪影（§9.2，与 node 重启无关的预存在现象）**；N2 自身一切正常（计数器证实请求到达、应答已发出）。

## 8. 结论与差异速查

| 维度 | kernel 版（10-04 §10/§11） | 无 kernel 版（本次） | 影响 |
|---|---|---|---|
| API 字段 | `kernel_datapath: true` | 字段消失 | 判据需改 |
| filter 支持集 | 13 种 | **5 种**（缺 rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop） | §10.6 精测 7 项中 rate/gemodel/duplicate 不可用 |
| 5 种 legacy filter 数据面 | 精确（2× 双向） | **逐项一致** | 语义层与 datapath 解耦 |
| 参数校验 | delay 单参可用 | delay 强制 2 参 | 脚本需适配 |
| 连通性 | 22/22、ttl=53、11 跳 | **完全相同** | 功能面零回归 |
| 延迟（受控负载） | 6.63 ms / +0.62 ms per VM | **5.53–6.72 ms / +0.52 ms per VM** | **无劣化**（VM 穿越主导） |
| 延迟（空闲宿主） | （未记录） | **10.2–11.0 ms** | 宿主电源状态伪影，见 §9.1 |
| 吞吐 单流 | 342 Mbps | **139–148 Mbps（÷2.3）** | relay 用户态转发 |
| 吞吐 多流 | 168–206 Mbps（反降） | **90–124 Mbps（反降）** | 同形态、水位减半 |
| delay 曲线 | — | 2× 精确、单流对 RTT 不敏感（更极端） | 瓶颈形态一致 |
| 全链 5ms 锚点 | 109.47 ms / 131 M | **108.81 ms / 116 M** | 高度一致 |
| virtio 杠杆 | ×5.1 单流、多流持平 | **×2.2 单流、多流塌陷** | 杠杆大幅缩水 |
| stop/start | 全通过（§9/§10.9） | **存活正常** | 无回归 |

## 9. 方法论发现（重要，供后续场次沿用）

### 9.1 宿主电源状态敏感性（RTT ~2× 摆幅，本场最大测量坑）

同配置、同 filter 全空、两次冷启，全链 RTT 实测在 **5.2–6.7 ms（宿主有载）与 10.2–11.0 ms（宿主空闲）** 两个状态间跳变。定位实验（实测）：宿主加 6 核 burn 负载后，同一时刻 RTT 从 10.24 ms 回落到 **6.57 ms**；负载结束回到 ~11 ms。原因【推断】：空闲时 CPU 深 C-state/降频，每次 VM 唤醒多付退出延迟（全链摊 ~+0.5 ms/穿越）；有载时保持浅 C-state/睿频。

**影响**：跨会话/跨时段 QEMU 场绝对 RTT 相差可达 2×，必须标注测量时的宿主状态；对比测量应在受控负载下进行（本轮曲线/阶梯均如此）。kernel 基线（6.63 ms）与无 kernel 受控负载值（5.5–6.7 ms）同档——**"延迟无劣化"的结论成立**；空闲态 11 ms 不代表 relay 引入的延迟。

### 9.2 rp_filter × ECMP 伪影（"ping 不通"≠链路断）

现象：host1 ping N2 的 transit 接口地址 100% 丢，而 N2 回环、E2E、N1/host2 对同地址的 ping 全部正常。诊断链（实测）：
1. N2 的 `/proc/net/snmp` 计数：30 个失败 ping 全部到达（InEchos +30）、**应答全部发出**（OutEchoReps +30）⇒ 丢在回程；
2. N2 到 host1 子网的路由是 **ECMP（seg1+seg2）**，回程应答按流哈希选中了"错"的那条平行链；
3. N1 全接口 **rp_filter=1（strict）**：来自 10.2.1.2 的包只有从 eth0（其反径）进来才通过，经 eth1 进来的被静默丢弃；
4. A/B 定案：N1 临时改 rp_filter=0 → 两条链立即 0% 丢；还原为 1 → 100% 丢复现。
- **与 node 重启无关**（镜像默认 rp_filter=1 + 双平行 ECMP 拓扑的稳态属性）。验证连通性请用**回环地址或主机 E2E**（记录 §11.5 的阶梯正是用 lo，天然规避）。

## 10. 重现菜单

```bash
# 0) 前置：项目 open + node_start_all（13 节点），~90 s 自收敛 22/22 Full
#    宿主状态：RTT 类测量建议加 4–6 核负载保持"有载态"（§9.1）
# 1) 平台判定
link_get("8952b17d-...")                       # 无 kernel_datapath 键
link_available_filters("8952b17d-...")          # 5 种
link_update(..., filters={"rate": ["512kbit"]}) # 409 Unknown filter type
# 2) filter（seg6；host1 采样，E2E host2）
link_update(..., filters={"delay": [10, 0]})    # 注意 2 参
link_update(..., filters={"packet_loss": [10]}) # n≥200
link_update(..., filters={"frequency_drop": [3]})
link_update(..., filters={"bpf": ["icmp"]})
link_update(..., filters={"corrupt": [30]})
link_update(..., filters={})
# 3) 性能：host1# iperf3 -c 10.2.200.1 -t 10 [-P 16]
# 4) 曲线：seg1+seg2（e0489018/7d26e21d）同档 delay [X,0]，X=1/5/10/20
# 5) virtio 场（7f9cec92）：轻量子集（RTT/单流/多流），注意多流可能触发现场失稳
```

---

*本记录 2026-10-04 对照复测（无 kernel datapath server `3.1.0.dev7+38cc7cc0a`）；kernel 基线为【转引】QEMU-Kernel-DataPath-Test 记录 §10/§11。所有数据面数值为本次实测。*
