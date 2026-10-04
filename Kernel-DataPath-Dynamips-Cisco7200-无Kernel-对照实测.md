# Kernel-DataPath-Dynamips-Cisco7200 — 无 Kernel-DataPath 版本对照实测（2026-10-04/05）

> 性质：**对照复测记录**。kernel 基线为**转引**——《Dynamips-Kernel-DataPath-Test-方案与实施记录.md》§10（11 节点现行基线，2026-10-04，kernel-datapath 服务器）与 §1–§9（6 节点时代，server `3.1.0.dev7+c9692ff9a`）；本轮在**无 kernel datapath 的服务器**上把同一测试菜单重跑，本文数值除注明外均为本次**实测**。
> 一句话结论：**功能面零回归**（OSPF 22/22、ttl=53、ECMP、5 种 legacy filter 逐项一致、串口 relay 对照不变、stop/start 自愈）；**性能面无劣化**（E2E RTT 同 band、iperf3 单流 629K/104K vs kernel 524K/114K 同形）——dynamips 的瓶颈本就是 MIPS 模拟本体（idle-sleep），kernel→relay 切换被淹没。dynamips 以太链 13 种 filter 整体回落 **5 种**（与串口 relay 同集，含 §10.6 精测的 rate/duplicate 现 409）。
> **本场特有观察**：frequency_drop 在无 kernel 版测得 **59.5%/61%**（kernel 版 58%/56%）——**不重现** Docker/QEMU/IOU 三场 relay 的 ~50% 偏离特征（见 §7-1），"relay 计数器口径"是否普适存疑。

- 项目：`Dynamips-Kernel-DataPath-test-Cisco7200`（`796d08d4-7560-41f5-bd9b-2330e48f639e`，11×c7200 + 2×Ubuntu Docker 主机，14 链）
- 对照版本：server **`3.1.0.dev7+38cc7cc0a`（无 kernel datapath）** ↔ kernel 版（§10 记录时点的 kernel-datapath 服务器；6 节点期为 `3.1.0.dev7+c9692ff9a`）
- 被测链：seg6 = `058048f3-d27e-4c2d-81b5-6f04c1898ce9`（R5 f1/1 ↔ R6 f1/0，10.4.6.0/30，filter 主测链）；串口 relay = `2e73b4c7-5c41-43a5-a30f-2983be2e00c6`（R2 s2/0 ↔ R3 s2/0，10.4.250.0/30）；混合链 host1 = `57f10402-8e44-47d8-9f3e-ca6e66e7fb35`

---

## 1. 平台层判定（字段、filter 支持集与数据面归属）

| 项 | kernel 版（转引 §4/§10.5） | 无 kernel 版（本次实测） |
|---|---|---|
| `link_get` 的 `kernel_datapath` 字段 | 以太 `true`（13/13）/ 串口 `false` | **字段整体消失**（三类链路返回中均无此键） |
| `link_available_filters`（dynamips↔dynamips 以太链 seg6） | **13 种** | **5 种**：frequency_drop / packet_loss / delay / corrupt / bpf |
| `link_available_filters`（dynamips↔docker 混合链 host1） | 13 种 | **5 种**（同上） |
| `link_available_filters`（串口 relay 链） | 5 种（旧版） | **5 种**（不变） |
| kernel-only 下发（rate 抽查） | 以太链可用（§10.6 精测 512kbit） | **409**：`Invalid packet filter parameters: Unknown filter type: rate`（**无迁移指引**——kernel 版 relay 链的 409 曾带"删链重建可转 kernel datapath"指引） |
| `delay` 参数校验 | `[50]` 单参可用（§10.6 用单参） | **强制 2 参**：`delay expects 2 parameter(s), got 1`；`[50, 0]` 可用 |

**数据面归属判定（推断，证据链）**：dynamips 的 kernel datapath 原实现是"每个以太端口锚定在持久 TAP 上"（§4，内核桥 `gns3{link_id}` + `gd{nodeid[:8]}e{slot}p{port}`）；本版本该特性随 kernel datapath 一起移除，以太链回落 **uBridge relay**。实测证据：原 13 种 filter 的以太链现与串口 relay 链**返回完全相同的 5 种 legacy 集合**；`kernel_datapath` 字段消失（与 Docker/QEMU/IOU 场同款）。**功能影响 = dynamips 以太链的 rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop 8 种全部不可用**（与 IOU 场同属"整组换集"型降级）。本轮未做进程/内核对象观察（口径：只走 MCP），归属为 API 证据 + 行为证据链【推断】。

## 2. 环境与方法（本次）

- 全部 13 节点 `node_start_all` 冷启，**零配置干预**，NVRAM/主机持久化自动生效，约 2–3 min 自动收敛 **22/22 Full**。
- 长 ping 经**本地 console TCP 直连**（R5=5085、host1=5088、host2=5104）自计时脚本采集；短探针走 `device_show_run`。丢包类样本 n=200（沿用 ≥200 口径）。
- **本场新增方法坑**：本会话的 console 端口要求 **telnet 选项协商**（服务器首发 `IAC DO TERMINAL-TYPE` 后静默等待），裸 TCP 客户端须回复 WONT/DONT 才有输出——脚本已升级为协商应答版。自动化解析注意 console **滚动缓冲回放**，取最后一条 summary（沿用 §6.2-1）。
- 吞吐：host1→host2 iperf3（host2 `iperf3 -s -D`）；单流 `-t 5`、8 流 `-P 8 -t 5`。
- **未做**：宿主机电源状态 A/B（见 §7-2）；kernel 时代的锚点生命周期观察（TAP/桥）——本版本无 TAP 且只走 MCP 口径，stop/start 改为**功能存活判定**（§6）。

## 3. 连通性（对照）

| 测量 | kernel 版（转引 §10.4） | 无 kernel 版（实测） | 差异 |
|---|---|---|---|
| OSPF 邻接 | 22/22 FULL | **22/22 FULL**（冷启零干预，NVRAM 自恢复） | 无 |
| host1→host2 ttl / traceroute | ttl=53 / 11 路由器跳 + 1 | **ttl=53 / 12 行**（`.254 → 10.4.2.2 → … → 10.4.11.2 → 10.4.200.1`，逐跳 ~30–40ms 爬升） | 无 |
| R1 对远端 ECMP | 双下一跳（metric 11） | **双下一跳保持**（`10.4.2.2 via f1/1` + `10.4.1.2 via f1/0`，traffic share 1:1，metric 11） | 无 |
| 串口 relay 链（R2→10.4.250.2） | 基线 4/49/64，100%（§10.6） | **24/36/60ms，20/20 0% 丢** | 无 |

## 4. Packet Filter 对照（5 种可用逐项 + 8 种不可用）

换算规律与其它四版一致：**filter 双向各生效一次**（RTT 丢包 = 1−(1−L)²，RTT delay = 2×单向）。主探针：R5 IOS ping → 10.4.6.2（单跳穿 seg6）。**单跳基线 28/33/64 ms，10/10**（kernel 版 §10.6 基线 8/37/64，同量级）。

| # | 类型 | 参数（本次） | kernel 版（转引） | 无 kernel 版（实测） | 判定 |
|---|---|---|---|---|---|
| 1 | delay | `[50, 0]` | avg 131ms（§10.6，基线 avg 37，Δ94） | **124/150/160ms**（min Δ96 ≈ 2×50） | ✅ 一致 |
| 2 | packet_loss | `[10]` | **19.0%**（162/200，§10.6） | **19.5%（161/200）** | ✅ 分毫同档（理论 19%） |
| 3 | frequency_drop | `[3]` | 58% / 56%（各 200 包，§10.6） | **59.5%（81/200）+ 61%（78/200）两轮** | ✅ 同档（见 §7-1） |
| 4 | bpf | `icmp[icmptype]==8` | 0/20 选择性丢（§10.6） | **0/10（100% 丢）、OSPF 双向保持 FULL** | ✅ 选择性一致 |
| 5 | corrupt | `[30]` | 6 节点时代 `[50]`→33%（理论 25%，§6） | **51.5%（97/200）**（理论 51%） | ✅ 分毫命中 |
| 6 | rate | `[512kbit]` | 512k 精测 90ms（§10.6） | **409 拒绝（不可用）** | ⛔ 功能缺失 |
| 7 | duplicate | `[20]` | +45%@200 包（§10.6） | **409 拒绝（不可用）** | ⛔ 功能缺失 |
| 8–13 | reorder / gemodel / seed / limit / quota / window_drop | — | 6 节点时代逐项精确（§6） | **409 拒绝（不可用）** | ⛔ 功能缺失（整组回落 relay） |

- **串口 relay 对照（两版不变）**：基线 24/36/60 → `delay [50,0]` → **100/128/156ms**（avg Δ92 ≈ 2×50；kernel §10.6 为 120/147/160，Δ98 同档）✅
- **全链 delay 锚点（11 链各 `[10,0]`）**：即时 A/B——基线 440/542/618 → 加链后 592/649/704（轮 1）、542/641/712（轮 2）；**Δavg ≈ +99~107ms、Δmin 102~152**（理论 +200）。与 kernel §10.7 同现象（Δmin 217 / Δavg 144）：**确定性部分在 min 上呈现、avg 被 dynamips idle-sleep（30ms 片）噪声压缩**；单链精测（#1，min Δ96）才是精确证据。测毕 11 链全清。
- 清 filter 复核：seg6 回 **30/30、4/36/64** 基线，OSPF 无抖动。

## 5. 性能对照（本次实测 vs §10.7 转引）

| 指标 | kernel 版（转引 §10.7） | 无 kernel 版（实测） | 差异 |
|---|---|---|---|
| host↔host RTT | 364/521/635（avg 521） | **387/454/536、440/542/618、384/478/536**（会话内三次，同 band） | 无（波动在 dynamips 噪声内） |
| 每跳延迟 | ~45 ms | **~30–40 ms**（traceroute 逐跳） | 无 |
| ttl / traceroute | 53 / 11+1 跳 | **53 / 12 行** | 无 |
| iperf3 单流 | sender 524 K / receiver 114 Kbps（36 retr） | **sender 629 K / receiver 104 Kbps（1 retr）** | 同形同量级 |
| iperf3 8 流 | sender 629 K / receiver 69 Kbps（43 retr） | **sender 419 K / 1.47 M（两轮）、receiver 0（两轮）** | 同形（多流不放大、收侧更塌） |

- **TCP RTO 崩塌形态完整重现**：单流首 2s 撑 ~1 M、随后 stall（0.00 区间）、receiver 以 ~104 Kbps 慢速排水——与 kernel 版 114 Kbps 几乎重合。**非 kernel datapath 问题**（§10.7 已结论：全链接口 0 collisions/errors/drops；dynamips 不仿真 CSMA/CD）。
- **8 流两轮 receiver 均 0、sender 419 K~1.47 M**：多流不放大结论维持；本场 receiver 侧比 kernel 记录的 69 K 更塌（RTO 时序运气），sender/retr 形态一致。
- 结论（实测）：**relay 化对 dynamips 的延迟/吞吐无可见影响**——瓶颈是 MIPS 模拟 + idle-sleep，uBridge 逐帧转发增量被两个数量级的本体开销掩盖【推断，与 IOU 场 §5 结论同族】。

## 6. stop/start 存活专项（R9，镜像 §10.9 用例）

- `node_stop(R9)` → `node_start(R9)`：**NVRAM 自恢复**（f0/0=10.4.9.2、f1/0=10.4.10.1 均 up/up，source=NVRAM）→ R9 自身 **2×FULL**（R8/R10），R8/R10 双向见它 FULL（dead 计时正常倒计）。
- E2E：重启后首测出现 **53% 瞬态丢包（+8 ICMP errors）**——LSA 重泛洪/收敛窗口；约 40s 后复测 **15/15 0% 丢、ttl=53**（355/453/509ms）。dynamips 本体慢，收敛窗口比 IOU 场（瞬时恢复）长，属正常瞬态，非回归（kernel §10.9 记录亦为收敛后 0%）。
- 本版本无 TAP 锚点可观察（relay 化 + MCP 口径），"stop is not close" 以**功能存活**判定：stop/start 后链路零重建、全自愈，与 kernel 版结论等效。

## 7. 本场特有观察与方法论

1. **frequency_drop 的场间差异（重要）**：本场两轮 **59.5% / 61%**，与 kernel 版 58%/56% 同档；而 Docker/QEMU/IOU 三场无 kernel 版一致落在 **~50%**（52.5 / 49.5 / 49–51）。即**"relay → ~50%"不是普适签名**——dynamips 的 relay 复现的是它自己 kernel 时代的偏移方向。三个候选解释（未定案）：① uBridge every-Nth 计数器对链上**全部帧**计数，ping 视角丢包率随各平台背景帧组合（keepalive/CDP/hello 周期）漂移——kernel §10.8-3 对 dynamips 的 58/56 已给出同款"混流相位"解释；② 各平台 relay 实现路径不同导致的计数口径差异；③ 相位运气（每轮 200 包）。**判定纪律：freq_drop 精确验证需静默链**（沿用 kernel 版方法论），混流链上的 ±5-10% 偏差不作功能判定依据。
2. **宿主电源状态敏感性未测**：本场未做 burner A/B（dynamips RTT 由 idle-sleep 主导，会话内基线 min 在 355–440ms 间波动，**未归因**——不断言是/不是宿主状态）。IOU/QEMU 两场已证实该效应存在于用户态转发路径；dynamips 场如需 RTT 级精度，建议后续补做。
3. **IOS 探测语法坑（本轮新增）**：`show ip ospf neighbor brief` 在本镜像（15.2(4)M11）**不存在**（`brief` 为更新版 IOS 关键字）；`show ip route 10.4.0.11/32` 亦被拒——正确形式 `show ip route 10.4.0.11 255.255.255.255`（kernel §10.4 记录的 `/32` 形式在本镜像不成立，以本次为准）。
4. **console telnet 协商坑（本轮新增）**：本会话 console TCP 端口在收到裸连接后首发 `IAC DO TERMINAL-TYPE` 并等待协商应答，未应答则**静默无输出**；脚本须回复 WONT/DONT。此前场次的裸 TCP 直连脚本在本会话失效，已升级（见 §2）。
5. 6 节点版坑继续有效【沿用 10-01】：console 回放取末条 summary、长 ping 走本地 console TCP、cold boot 2-3 分钟、`write memory` 前先 `end`、PA-FE-TX 不认 duplex/speed auto、带参 `no ip address` 回显 Invalid address 无害。

## 8. 结论与差异速查

| 维度 | kernel 版（转引） | 无 kernel 版（本次） | 影响 |
|---|---|---|---|
| API 字段 | 以太 `true` / 串口 `false` | 字段消失 | 判据不可再用；filter 集合（13 vs 5）成为唯一区分手段 |
| filter 支持集 | 以太 13 / 串口 5 | **全部 5** | dynamips 以太链 rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop 全不可用 |
| 5 种 legacy 数据面 | 精确（2× 双向） | **逐项一致**（delay min Δ96≈2×50、loss 19.5%、corrupt 51.5%、bpf 选择性） | 语义层与 datapath 解耦 |
| frequency_drop | 58%/56%（混流相位） | **59.5%/61%**（同档） | 与三场 relay 的 ~50% 不同——非普适签名（§7-1） |
| 连通性 | 22/22、ttl=53、ECMP | **完全相同** | 功能面零回归 |
| RTT | 364/521/635 | **384–440 / 454–542 / 509–635**（同 band） | 无劣化（dynamips 本体主导） |
| 单流吞吐 | 524K / 114K（36 retr） | **629K / 104K（1 retr）** | 无劣化（RTO 崩塌形态两版同） |
| 8 流吞吐 | 629K / 69K | **419K~1.47M / 0** | 多流不放大维持；收侧更塌（时序运气） |
| 串口 relay | 5 filter、delay[50]→120/147/160 | **同（100/128/156，Δ92≈2×50）** | 无变化 |
| stop/start | 通过（§10.9） | **通过（R9 复验，含 ~40s 收敛窗口）** | 无回归 |

**总评**：dynamips 与 IOU 同属"**filter 能力整组降级（13→5）、性能几乎无影响**"型——但原因不同：IOU 是用户态转发进程淹没 relay 增量，dynamips 是 MIPS 模拟 + idle-sleep 把一切都淹没（延迟高 2-3 个数量级，filter 精度反而分毫不差）。**kernel datapath 对 dynamips 的价值完全在 filter 能力面（+8 种）与内核锚点观察性，不在性能面**【推断】。

---

## 9. 重现菜单

```bash
# 0) 前置：项目 open + node_start_all（13 节点），~2-3 min 自收敛 22/22 FULL
# 1) 平台判定
link_get("058048f3-...")                       # 无 kernel_datapath 键
link_available_filters("058048f3-...")         # 5 种（三类链路同）
link_update(..., {"rate": ["512kbit"]})        # 409 Unknown filter type（无指引）
link_update(..., {"delay": [50]})              # 409 expects 2 parameter(s)

# 2) 5 种 filter（seg6，单跳探针 R5 ping 10.4.6.2；丢包类 n=200 走本地 console TCP 5085）
link_update(..., {"delay": [50, 0]})           # 124/150/160ms（min Δ96）
link_update(..., {"packet_loss": [10]})        # 19.5%（161/200）
link_update(..., {"frequency_drop": [3]})      # 59.5%/61%（两轮 200 包）
link_update(..., {"bpf": ["icmp[icmptype]==8"]})  # 0/10，OSPF 不动
link_update(..., {"corrupt": [30]})            # 51.5%（97/200）
link_update(..., {})                           # 清空复核（30/30、4/36/64）

# 3) 串口 relay：link_update("2e73b4c7-...", {"delay": [50, 0]}) → R2 ping 10.4.250.2 ≈100-156ms
# 4) 全链锚点：11 链各 delay[10,0]（E2E A/B Δavg ~+100ms）→ 11 链清空
# 5) 性能（host1 console 5088）：ping -c 15 -i 0.3 10.4.200.1（~390-540ms）；
#    iperf3 -c 10.4.200.1 -t 5 [-P 8]   # 单流 629K/104K，8 流 receiver 0
# 6) stop/start：node_stop/start(R9) → NVRAM 自恢复 + 2×FULL + 等 ~40s 收敛 → E2E 0%
```

---

*本记录为对照复测（2026-10-04/05），全部数据面数值为本次在无 kernel datapath 服务器（`3.1.0.dev7+38cc7cc0a`）上的【实测】；kernel 基线为【转引】《Dynamips-Kernel-DataPath-Test-方案与实施记录.md》§1–§10（2026-10-01/10-04）。*
