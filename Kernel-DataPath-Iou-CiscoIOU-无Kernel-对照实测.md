# Kernel-DataPath-Iou-CiscoIOU — 无 Kernel-DataPath 版本对照实测（2026-10-04）

> 性质：**对照复测记录**。kernel 基线（11 节点现行版）为**转引**——《IOU-Kernel-DataPath-Test-方案与实施记录.md》§10（11×IOU 现行基线）与 §5/§6（6 节点时代 filter 全测）；本轮在**无 kernel datapath 的服务器版本**上把同一测试菜单重跑，本文数值除注明外均为本次**实测**。
> 一句话结论：**功能面零回归**（OSPF 22/22、ttl=53、ECMP、5 种 legacy filter 逐项一致、串口 relay 对照不变）；**性能面几乎零劣化**（单流 128–131M vs kernel 126M，受控负载 RTT 2.23ms vs 1.91ms 同量级）——IOU 的瓶颈本就是用户态转发进程，kernel→relay 的切换被淹没；IOU 以太链 13 种 filter 整体回落 **5 种**（与串口 relay 同集，含 §10.6 精测的 rate/duplicate 现 409）。另复现**宿主电源状态敏感性**（空闲 4.8–5.0ms ↔ 受控负载 2.2–2.3ms，双向可复现）——QEMU 场同款方法论坑在 IOU 场同样成立。

- 项目：`Kernel-DataPath-Iou-CiscoIOU`（`9c00ff33-e555-4a8d-8e48-f14d1ed7b7d0`，11×Cisco IOU L3 + 2×Ubuntu Docker 主机，14 链）
- 对照版本：server **`3.1.0.dev7+38cc7cc0a`（无 kernel datapath）** ↔ 原 **`3.1.0.dev7+506a6bc94`（IOU kernel datapath 特性版）**
- 被测链：seg6 = `510bd4ec-afff-4bf7-9d54-6d123104f66c`（R5 e0/1 ↔ R6 e0/0，filter 主测链）；混合链 host1 = `7c1e22ff-2710-47be-af46-2f672ce5c375`；串口 relay = `409f12ac-83bf-44f1-9563-e587565e8004`（R2 S2/0 ↔ R3 S2/0，10.3.250.0/30）

---

## 1. 平台层判定（差异一：字段、filter 支持集与数据面归属）

| 项 | kernel 版（转引 §10.5/§4） | 无 kernel 版（本次实测） |
|---|---|---|
| `link_get` 的 `kernel_datapath` 字段 | 以太 `true`（13/13）/ 串口 `false` | **字段整体消失**（三类链路返回中均无此键） |
| `link_available_filters`（IOU↔IOU 以太链 seg6） | **13 种** | **5 种**：frequency_drop / packet_loss / delay / corrupt / bpf |
| `link_available_filters`（IOU↔docker 混合链 host1） | 13 种 | **5 种**（同上） |
| `link_available_filters`（串口 relay 链） | 5 种（旧版） | **5 种**（不变） |
| kernel-only 下发（rate/gemodel/duplicate 抽查） | 以太链可用 | **409**：`Invalid packet filter parameters: Unknown filter type: rate / gemodel / duplicate`（无迁移指引——kernel 版 relay 链的 409 曾带"删链重建可转 kernel"指引，本版本无） |
| `delay` 参数校验 | `[50]` 单参可用（jitter 缺省） | **强制 2 参**：`delay expects 2 parameter(s), got 1`；`[50, 0]` 可用 |

**数据面归属判定（推断，证据链）**：IOU 的 kernel datapath 原实现是 `iol_bridge add_nio_tap` 锚点（内核 tap+桥）；本版本该特性随 kernel datapath 一起移除，IOU 以太链回落 **uBridge relay**。实测证据：原 13 种 filter 的以太链现与串口 relay 链**返回完全相同的 5 种 legacy 集合**；`kernel_datapath` 字段消失（与 Docker/QEMU 场同款）。**IOU 场因此是三场里唯一"filter 能力整体降级"的**——docker/qemu 只丢 kernel-only 8 种（其 legacy 5 种两版相同），IOU 是把 kernel 时代的 13 种全部换成 5 种。

## 2. 环境与方法（本次）

- 全部 13 节点 `node_start_all` 冷启，**零配置干预**，NVRAM/主机持久化自动生效，约 35–60s 自动收敛 **22/22 Full**。
- **宿主状态受控法（沿用 QEMU 场 §9.1 教训）**：发现 E2E RTT 在空闲/负载两态摆动 ~2.1× 后（见 §7），凡 RTT 对比均标注宿主状态；吞吐测量在受控负载（host1/host2 各 3 个 `yes` burner，共 6）下进行。
- 流量采样：host1（Ubuntu，本地 console TCP 127.0.0.1:5092）iputils ping（`-i 0.05`）；IOS 侧探针走 `device_show_run`（`ping x repeat N timeout T`，显示粒度 1ms）。丢包类样本 n=200（沿用 ≥200 口径）。
- 吞吐：host1→host2 iperf3（host2 容器重启后重起 `iperf3 -s -D`）；单流 `-t 5`、4/8/16 流 `-P N -t 5`。

## 3. 连通性（对照）

| 测量 | kernel 版（转引 §10.4） | 无 kernel 版（实测） | 差异 |
|---|---|---|---|
| OSPF 邻接 | 22/22 FULL | **22/22 FULL**（全程保持，filter 测试期间无震荡） | 无 |
| host1→host2 ttl / traceroute | ttl=53 / 11 路由器跳 | **ttl=53 / 12 行（11 路由器 + 目的）** | 无 |
| R1 对远端 ECMP | 双下一跳（e0/0+e0/1，metric 101） | **双下一跳保持**（10.3.1.2 / 10.3.2.2，metric 101） | 无 |
| 串口 relay 链（R2→10.3.250.2） | 基线 ~22ms（6 节点时代 §6） | **20/20/22ms，0% 丢** | 无 |

## 4. Packet Filter 对照（5 种可用逐项 + 8 种不可用）

| # | 类型 | 参数（本次） | kernel 版（转引） | 无 kernel 版（实测） | 判定 |
|---|---|---|---|---|---|
| 1 | delay（IOU↔IOU seg6） | `[50, 0]` | 单跳 100/101/102ms（§10.6） | **单跳 100/100/102ms**（基线 1/1/1ms，2×50+1） | ✅ 分毫一致 |
| 2 | delay（IOU↔docker 混合链） | `[10, 0]` | 21.04ms（§6，基线 0.76） | **20.496/20.988/21.362ms**（基线 0.723，Δ=20.27=2×10） | ✅ 一致 |
| 3 | delay（串口 relay） | `[50, 0]` | 121ms（§6，基线 22） | **120/120/121ms**（Δ≈99=2×50） | ✅ 一致（relay 行为两版不变） |
| 4 | packet_loss | `[10]` | E2E 15%（170/200，§10.6） | **E2E 18.5%（163/200）** | ✅ 一致（理论 19%，同 1σ） |
| 5 | frequency_drop | `[3]` | E2E **55.5%**（89/200，§10.6） | **E2E 51%（98/200）+ 49%（102/200）两轮** | ⚠️ 小差额（见下） |
| 6 | corrupt | `[30]` | 6 节点时代 `[50]`→73.3%（理论 75%） | **E2E 52.5%（95/200）**（理论 51%） | ✅ 一致 |
| 7 | bpf | `icmp[icmptype]==8` | 过 seg6 100% 丢、近端 20/20、邻接不动（§10.6） | **过 seg6 E2E 0/20（100% 丢）、到 R5 近端 10/10、OSPF 全程 FULL** | ✅ 选择性一致 |
| 8–13 | rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop | — | 逐项可用且精确（§10.6 精测 rate 45ms / duplicate +43% 等） | **409 拒绝（不可用）** | ⛔ 功能缺失（整组回落到 relay） |

**frequency_drop 的 ~50% vs 55.6% 小差额（实测 + 推断）**：无 kernel 版本三个场（docker 52.5% / qemu 49.5% / IOU 49–51%，均 n=200）一致落在 ~50%，而 kernel 版三个场都是 55.5–55.6% 分毫精确（理论 1−(2/3)²=55.56%）。【推断】relay（uBridge 用户态）的 frequency 计数器口径与 eBPF 版不同（计数集合/方向/相位之一），属**实现差异而非精度漂移**——三场独立复现同向偏离，非抽样噪声。换算规律（双向各生效一次、RTT 丢包 1−(1−L)²）在可用 filter 上依然成立。

## 5. 性能对照（本次实测 vs §10.7 转引）

| 指标 | kernel 版（转引 §10.7） | 无 kernel 版（实测） | 差异 |
|---|---|---|---|
| 单流（host1→host2） | 126 Mbps（retr 1541） | **131 / 129 / 128 Mbps**（retr 562/530） | **基本持平**（重传大幅下降，见下） |
| 4 流 | —（未测） | **189 Mbps**（retr 2178） | — |
| 8 流 | 272 Mbps 聚合（retr 8472） | **209 / 181 Mbps**（retr 3634/3414） | ~-25%（跨会话口径，见上） |
| 16 流 | —（未测） | **206 / 203 Mbps**（retr 5553） | — |
| 多流形态 | 8 流 > 单流 ×2.2 | **4/8/16 流全落在 ~180–210M 平台（> 单流 ×1.5）** | 形态保持（多流补偿仍在），平台略低 |

- **单流持平且重传显著下降**（1541→530）：relay 逐帧转发虽慢，但**不产生 kernel 版那种链接级丢包/超时反馈**（kernel 版高重传疑与 veth/tap 队列或 stats 口径有关【推断】），TCP 反而更从容。net 效果：可用吞吐两版同级。
- RTT 与阶跃（受控负载 6 burner 下）：E2E **min/avg/max/mdev = 1.387/2.230/5.575/0.696 ms** vs kernel 1.913；单跳 host1↔R1 **0.541–0.555ms**（kernel 时代 ~0.76，跨会话口径）。**每跳增量与 kernel 版同量级**——IOU 每跳成本主体是 IOL 用户态转发进程（socket→ubridge→桥逐帧），relay 化不新增量级【推断：与 QEMU 场 §9.1 结论同族——瓶颈在平台本体，不在 datapath】。
- 未测：delay×吞吐曲线（kernel 版 IOU 11 节点基线无此项，保持菜单对齐）。

## 6. stop/start 存活专项（IOU-R-9，镜像 §10.9 用例）

- `node_stop` → R8/R10 方向静默（dead 计时器走完即消）→ `node_start`：**NVRAM 自恢复**（e0/0=10.3.9.2、e0/1=10.3.10.1 均 up/up）→ R9 自身 **2×FULL**（R8/R10）、R8/R10 双向见它 FULL → **E2E 50/50 0% 丢、RTT 1.738ms**。
- 结论：relay 化后 IOU 节点 stop/start 锚点生命周期**无回归**（kernel 版 §10.9 通过；本版本链路走 relay，机制不同，同样自愈）。

## 7. 方法论发现：宿主电源状态敏感性在 IOU 场复现（重要）

同会话内四态 A/B（host1→host2，100 包/次，同一配置零改动）：

| 状态 | E2E RTT avg | 单跳 host1↔R1 |
|---|---|---|
| 冷启后、宿主无负载（burner=0） | **4.782 ms** | （未测） |
| 受控负载（host1+host2 各 3 burner） | **2.230 ms** | 0.555 ms |
| 只留 host2 3 burner | **2.296 ms** | 0.541 ms |
| 再次全空闲（停 burner 后 ≥5 min） | **4.974 ms**（单跳 0.723） | 0.723 ms |

- **双向可复现**：加负载 → 快（~2.2ms），去负载 → 慢（~4.8–5.0ms），排除了"启动瞬态"解释（首测 4.78 与 5 分钟后空闲 4.97 一致）。
- 与 QEMU 场 §9.1 同款现象（该场 10.2–11.0ms ↔ 5.5–6.7ms）：【推断】宿主空闲深 C-state/降频使每个转发进程唤醒多付 ~0.2–0.25ms；24 核机器上仅 3 个 busy 核即可压住深睡态。
- **口径纪律**：IOU 场 RTT/曲线类测量今后必须标注宿主状态或加受控负载；跨场对比只看"同状态口径"的数字（本文对照表均取受控负载态 vs kernel 记录；kernel 记录当年宿主状态未标注，跨会话绝对值仅指示性【沿用汇总文档口径】）。

## 8. 结论与差异速查

| 维度 | kernel 版（转引） | 无 kernel 版（本次） | 影响 |
|---|---|---|---|
| API 字段 | 以太 `true` / 串口 `false` | 字段消失 | 判据不可再用；filter 集合（13 vs 5）成为唯一区分手段 |
| filter 支持集 | 以太 13 / 串口 5 | **全部 5** | IOU 以太链 rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop 全不可用（**三场中降级最重**） |
| 5 种 legacy 数据面 | 精确（2× 双向） | **逐项一致**（delay 2×、loss/corrupt/bpf 同族） | 语义层与 datapath 解耦 |
| frequency_drop 精度 | 55.5–55.6% 精确 | **~50%（三场一致小差额）** | relay 计数器口径差异【推断】 |
| 连通性 | 22/22、ttl=53、ECMP | **完全相同** | 功能面零回归 |
| RTT（受控负载） | 1.91ms（0.87/1.91/3.88） | **2.23ms**（1.39/2.23/5.58） | 同量级（跨会话仅指示性） |
| 单流吞吐 | 126M（retr 1541） | **128–131M（retr ~530）** | **持平**，重传大幅下降 |
| 多流吞吐 | 8 流 272M | 4/8/16 流 ~180–210M 平台 | 形态保持、平台略低 |
| 串口 relay | 5 filter、delay[50]→121ms | **同（120–121ms）** | 无变化 |
| stop/start | 通过（§10.9） | **通过（R9 复验）** | 无回归 |

**总评**：IOU 是三场对照中"**功能降级最明显、性能影响最小**"的一场——13→5 种 filter 是实打实的能力损失，但吞吐/RTT 几乎不动，佐证 IOU 平台瓶颈在 IOL 用户态转发进程本体（§10.7 结论"瓶颈在 IOU 用户态转发，不在 kernel datapath"在 relay 化后依然成立）【推断】。

---

## 9. 重现菜单

```bash
# 0) 前置：项目 open + node_start_all（13 节点），~1 min 自收敛 22/22 FULL
# 1) 平台判定
link_get("510bd4ec-...")                       # 无 kernel_datapath 键
link_available_filters("510bd4ec-...")         # 5 种（三类链路同）
link_update(..., {"rate": ["512kbit"]})        # 409 Unknown filter type（无指引）
link_update(..., {"delay": [50]})              # 409 expects 2 parameter(s)

# 2) 5 种 filter（seg6，单跳探针 R5 ping 10.3.6.2；丢包类 E2E n=200）
link_update(..., {"delay": [50, 0]})           # 单跳 100/100/102ms
link_update(..., {"packet_loss": [10]})        # E2E ~18.5%
link_update(..., {"frequency_drop": [3]})      # E2E ~50%（kernel 版 55.5%）
link_update(..., {"bpf": ["icmp[icmptype]==8"]})  # 选择性 100% 丢
link_update(..., {"corrupt": [30]})            # E2E ~52.5%
link_update(..., {})                           # 清空复核（0% 丢、~1.8–2.3ms 受控负载）

# 3) 性能（host1 console：研究机本地 TCP 127.0.0.1:5092；宿主受控负载 6×yes）
host1# ping -c 100 -i 0.05 10.3.200.1          # 受控负载 ~2.2ms / 空闲 ~4.9ms
host1# iperf3 -c 10.3.200.1 -t 5 [-P 4|8|16]
# 4) 串口 relay：link_update("409f12ac-...", {"delay": [50, 0]}) → R2 ping 10.3.250.2 ≈120ms
# 5) stop/start：node_stop/start(IOU-R-9) → NVRAM 自恢复 + 2×FULL + E2E 0%
```

---

*本记录为对照复测（2026-10-04），全部数据面数值为本次在无 kernel datapath 服务器（`3.1.0.dev7+38cc7cc0a`）上的【实测】；kernel 基线为【转引】《IOU-Kernel-DataPath-Test-方案与实施记录.md》§5/§6/§10（2026-10-01/10-04 / server `3.1.0.dev7+506a6bc94`）。*
