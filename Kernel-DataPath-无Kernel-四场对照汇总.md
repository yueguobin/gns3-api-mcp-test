# GNS3 3.1 dev — Kernel Datapath 与用户态 Relay 四场对照汇总（中文版）

> 本文为 `Kernel-DataPath-NoKernel-Comparison-EN.md` 的中文对应版（同内容同数据）。四场逐字段的完整原始记录见 §10 引用表；本文为跨场汇总。

**范围**：在四个仿真平台上，对同一套实验菜单做"kernel datapath 特性移除前 → 移除后"的对照复测：

| 平台 | 实验场 / 项目 | kernel datapath 版（基线） | 仅 relay 版（复测） |
|---|---|---|---|
| Docker 容器（FRR） | `Kernel-DataPath-Docker-FRRDocker` | `3.1.0.dev7+2445e2e5e` | `3.1.0.dev7+38cc7cc0a` |
| QEMU 虚拟机（FRR/Alpine） | `Kernel-DataPath-Qemu-FRRqemu`（+ `-virtio`） | `3.1.0.dev7+2445e2e5e` | `3.1.0.dev7+38cc7cc0a` |
| Cisco IOU（IOU L3） | `Kernel-DataPath-Iou-CiscoIOU` | `3.1.0.dev7+506a6bc94` | `3.1.0.dev7+38cc7cc0a` |
| Dynamips（c7200） | `Dynamips-Kernel-DataPath-test-Cisco7200` | kernel datapath 版（§10 记录时点） | `3.1.0.dev7+38cc7cc0a` |

**证据来源约定**：所有"仅 relay 版"数值均为 **2026-10-04/05 在 server `3.1.0.dev7+38cc7cc0a` 上的【实测】**（见四份分场报告）；所有"kernel 版"数值均为对既有基线记录的**【转引】**；标【推断】的为与实测一致的假说，非已证机制。**Mixed（混合 NOS）场经决定不做，不在本文范围内。**

四场采用同一拓扑形状：11 台路由器线形链 R1..R11、R1↔R2 双平行 ECMP、Loopback `10.x.0.N/32`、两端 Ubuntu Docker 主机、OSPFv2 单区；IOU/Dynamips 另有不进 OSPF 的串口 relay 对照链。

---

## 1. 摘要

1. **kernel datapath 已从 API 消失**：`link_get` 不再返回 `kernel_datapath` 字段；全部链路走 uBridge **用户态 relay**。
2. **filter 能力从 13 种砍到 5 种**（frequency_drop / packet_loss / delay / corrupt / bpf），**所有平台、所有链路**一致。8 种 kernel-only filter（rate、reorder、gemodel、duplicate、seed、limit、quota、window_drop）现一律 HTTP 409，且**无迁移指引**。
3. **功能面无回归**：22/22 OSPF 邻接、ttl=53、12 行 traceroute、ECMP、stop/start 存活——四场与 kernel 版完全一致。
4. **留存 5 种 filter 行为逐项不变**（双向各生效一次：RTT 丢包 = 1−(1−L)²、RTT delay = 2×单向）；delay 现**强制 2 参**（`[X, 0]`）。
5. **性能影响强烈依赖平台**：
   - **Docker：严重**。E2E RTT ×5–6；多流吞吐 ÷14–25；10–20 Gbps 级别塌缩到 ~1.3 Gbps 单源水位。
   - **QEMU：中等**。延迟不变（VM 穿越主导）；单流吞吐 ÷2.3；virtio 杠杆从 ×5.1 缩到 ×2.2，多流退化为不稳定。
   - **IOU / Dynamips：无可测影响**。两者的自身转发栈（IOL 用户态进程 / MIPS 模拟）本就慢于 relay，relay 被完全淹没。
6. **经验规律【推断】**：relay 引入 ~0.1–0.2 ms/段的固定穿越成本与约 1.2–3 Gbps 的单源吞吐上限；原生每跳成本低于该量级的平台不受影响。

---

## 2. 平台 / API 层变化

| 项 | kernel datapath 版 | 仅 relay 版（现行） |
|---|---|---|
| `link_get` → `kernel_datapath` | kernel 链 `true`、relay 链 `false` | **字段整体移除**（非 `false`） |
| `link_available_filters` | **13 种** | **5 种**（frequency_drop、packet_loss、delay、corrupt、bpf） |
| 下发 kernel-only filter | kernel 链可用 | **HTTP 409** `Invalid packet filter parameters: Unknown filter type: <name>`，**无指引文本**（kernel 版 relay 链的 409 曾提示"删链重建可转 kernel datapath"） |
| `delay` 参数校验 | `[50]` 单参可用（jitter 缺省） | **强制恰 2 参**：`delay expects 2 parameter(s), got 1` |
| 数据面 | 内核（tc netem / eBPF，各平台 tap/veth 锚定） | uBridge 用户态 relay（UDP 隧道） |

**实现证据**：QEMU 场可从 `node_get` 的 command_line 直接看到【实测】：`-netdev tap,ifname=gq<node>e<N>p0,script=no` 变为 `-netdev socket,id=gns3-N,udp=127.0.0.1:XXXXX,localaddr=…`。IOU/Dynamips 的 relay 回落为【推断】，证据链两点：`kernel_datapath` 字段消失；其以太链的 filter 集合与串口 relay 链完全同集（各自的内核锚点——IOU 的 `iol_bridge add_nio_tap`、Dynamips 的持久 TAP——随特性一并移除）。

---

## 3. 功能基线——四场零回归

| 测量 | kernel 版【转引】 | 仅 relay 版【实测】 |
|---|---|---|
| OSPF 邻接 | 22/22 Full | **22/22 Full**（冷启零干预，NVRAM / frr.conf 自恢复），四场一致 |
| host1→host2 ttl / traceroute | ttl=53 / 11 路由器跳 | **ttl=53 / 12 行**（11 路由器 + 目的） |
| ECMP | 对远端双下一跳 | **双下一跳保持**（R1 traffic share 1:1） |
| 全部测试后的无 filter 基线 | 干净 | **干净**（如 IOU 30/30 0%；Dynamips 30/30、4/36/64 ms） |

---

## 4. Packet Filter——5 存 8 失

### 4.1 留存五种：kernel 版 → relay 版（逐平台）

| filter | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| `delay` | [50,0]：100.179 → **100.625 ms**（mdev 0.088） | [10,0]：27.474 → **26.853 ms** | [50,0]：100/101/102 → **100/100/102 ms** | [50,0]：avg 131 → **124/150/160 ms**（min Δ96 ≈ 2×50） |
| `delay`+jitter | [50,20]：mdev 27.167 → **27.035** | — | — | — |
| `packet_loss` | [30] n=61：56% → **55.74%** | [10] n=200：20.5% → **18.5%**（理论 19%） | [10] n=200：15% → **18.5%** | [10] n=200：**19.0% → 19.5%**（161/200） |
| `corrupt` | [30] n=61：53.3% → **57.38%** | [30] n=200：（6 节点期 [50] 84%）→ **53%** | [30] n=200：**52.5%** | [30] n=200：**51.5%**（理论 51%） |
| `bpf`（`icmp[icmptype]==8`） | 100% 丢、OSPF 不动 | 100% 丢、OSPF 不动 | 0/10、双向 OSPF FULL | 0/10、双向 OSPF FULL |
| `frequency_drop` [3] | n=61：61.9% → **52.46%** | n=200：56% → **49.5%** | n=200：55.5% → **51% / 49%** | n=200：58%/56% → **59.5% / 61%** |
| 串口 relay 链 `delay` [50,0] | — | — | 121 → **120–121 ms** | 120/147/160（Δ98）→ **100/128/156**（Δ92） |

五种全部逐项与 kernel 版一致：2× 单向 delay、RTT 丢包 = 1−(1−L)²、BPF 选择性且控制面不受扰。

### 4.2 消失的八种

`rate`、`reorder`、`gemodel`、`duplicate`、`seed`、`limit`、`quota`、`window_drop`——四场下发全部 409。现行版本下这一整类实验（按帧长限速、乱序、Gilbert-Elliott 突发损失、复制、确定种子、令牌桶配额、时间窗断网）均不可用。

### 4.3 frequency_drop——值得知道的场间差异

drop-every-3rd 的 RTT 丢包理论值 = 55.6%。仅 relay 版实测：

| | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| relay 版 | 52.5% | 49.5% | 49–51% | **59.5% / 61%** |
| kernel 版【转引】 | 61.9% | 56% | 55.5% | 58% / 56% |

Docker/QEMU/IOU 聚在 ~50% 附近，Dynamips 在 ~60%——即**"relay ⇒ ~50%"不是普适签名**，Dynamips 复现的是它自己 kernel 时代的偏移方向。最佳解释【推断】：every-Nth 计数器对链上**全部帧**计数（OSPF hello、以太 keepalive、CDP 混入），ping 视角的丢包率随各平台背景帧组合漂移（"混流相位"）。实操纪律：frequency_drop 精确验证只用静默链（passive-interface + 关 CDP）；任何 filter 判健康都不看单个短样本（n ≥ 200）。

---

## 5. 性能影响（按平台）

### 5.1 总矩阵

| 指标 | Docker | QEMU | IOU | Dynamips |
|---|---|---|---|---|
| E2E RTT，kernel → relay | 0.36 → **1.9–2.2 ms（×5–6）** | 6.63 → **5.5–6.7 ms（持平）**¹ | 1.91 → **2.23 ms（≈，跨会话仅指示性）**¹ | 521 → **454–542 ms（持平）** |
| 直连链 RTT | 0.099 → **0.32–0.54 ms** | — | 单跳 **0.54–0.55 ms** | 每跳 ~30–40 ms（kernel ~45） |
| 单流吞吐 | 2.22 G → **1.28 G（÷1.7）** | 342 M → **139–148 M（÷2.3）** | 126 M → **128–131 M（持平）** | 524K/114K → **629K/104K（1 retr）** |
| 多流 | 16 流 19.4 G → **1.36 G（÷14）**；32 流 ÷17 | 16 流 171 M → **104–124 M** | 8 流 272 M → **181–209 M** | 8 流 → sender 419K–1.47 M / receiver 0 |
| 多流放大形态 | **消失**（单流 ≈ 16 ≈ 32 ≈ 1.2–1.4 G） | 与 kernel 同形（反降）、水位减半 | **保留**（平台 > 单流 ×1.5） | 从未存在（RTO 崩塌） |
| 备注 | 每段 relay 成本 ~0.1–0.2 ms；≥5 ms delay 档与 kernel 收敛（同进 cwnd 受限区） | virtio 复制场：单流 1.73 G → **305–320 M（÷5.4）**、多流塌陷；virtio 杠杆 ×5.1 → ×2.2 | **无可测劣化**——IOL 用户态转发主导；重传反而大降 1541 → ~530 | **无劣化**——MIPS 模拟 + idle-sleep 主导（比 Docker 低 2–3 个数量级） |

¹ 在受控宿主 CPU 负载下测量（见 §6-1）。

### 5.2 矩阵解读

- **Docker 是唯一被 relay 重创的场**。它的 kernel 路径是全家族最快的（单流 2.2 Gbps、×16 流 19.4 Gbps），因此 relay 的 ~1.3 Gbps 单源水位与逐包用户态成本完全暴露。双源并发（2×16 流，1.24 + 1.25 G）证明这是**每源**水位而非单一共享硬瓶颈；1 跳（2 段 relay）3.0 G 说明吞吐随 relay 段数阶梯下降【实测】。
- **QEMU 损失吞吐但不损失延迟**。其瓶颈本就是 VM 穿越（~0.5 ms/VM；relay 化后 +0.52 ms/VM，原 +0.62），故延迟不变；吞吐减半是因为 relay 逐包转发拆散了 virtio 赖以摊薄的 GSO/TSO 超帧【推断】。
- **IOU 与 Dynamips 无感**。IOU 的每跳成本是其用户态 IOL 转发进程；Dynamips 是 MIPS 模拟 + 30 ms 片 idle-sleep。两者都远慢于 relay，去掉 kernel 路径在延迟与吞吐上均不可见——IOU 的 TCP 重传甚至大幅下降（1541 → ~530）【实测】。
- **delay 语义处处成立**：全链锚点复现 kernel 值（QEMU 11×5 ms：108.81 ms/116 M vs kernel 109.47 ms/131 M；Dynamips 11×10 ms：Δavg ≈ +100 ms，确定性部分在 min 上呈现；IOU 单跳 min Δ96 ≈ 2×50）【实测】。

---

## 6. 跨场方法论发现

1. **宿主 CPU 电源状态敏感性（RTT 最大 ~2× 摆幅）**。宿主空闲时转发比有载时更慢，双向可复现。
   - QEMU：全链 RTT **空闲 10.2–11.0 ms ↔ 有载 5.2–6.7 ms**；给空闲宿主加 6 路 burn 后立刻回落到 6.57 ms【实测】。
   - IOU：**空闲 4.8–5.0 ms ↔ 有载 2.2–2.3 ms**，双向可复现；24 核宿主上仅 3 个 busy 核即可压住该效应【实测】。
   - 解释【推断】：空闲深 C-state / 降频使每次转发唤醒多付 ~0.2–0.5 ms。
   - 后果：RTT 类测量必须加受控负载（几个 `yes > /dev/null`）或标注宿主状态；跨会话绝对 RTT 仅指示性。
2. **rp_filter × ECMP 伪影（QEMU 场）**。ping 设备 transit 接口 IP 可显示 100% 丢而网络完全健康：回程应答的 ECMP 哈希选中"错"的平行链，被上游节点 strict `rp_filter=1` 静默丢弃。A/B 定案（rp_filter 0 → 通、1 → 复现）+ `/proc/net/snmp` 计数证实"请求全到、应答全发"【实测】。连通性验证用回环或主机 E2E，勿用 transit 接口 ping。
3. **样本量纪律**。丢包类 filter 需 n ≥ 200：duplicate[20] 100 包测 +62%、200 包测 +45%（理论 +44%）；frequency_drop 另需静默链（见 §4.3）。
4. **现行版本的适配项**。delay 强制 2 参——自动化脚本改 `[x]` → `[x, 0]`。长 ping 仍走本地 console TCP；console 会回放滚动缓冲（取末条 summary）；Dynamips 会话的 console 还需应答 telnet 协商（对 `IAC DO TERMINAL-TYPE` 回 WONT/DONT，否则静默无输出）；Cisco IOS 15.2(4)M11 拒绝 `show ip ospf neighbor brief` 与 `show ip route <ip>/32`（改用 `<ip> <mask>`）。

---

## 7. 节点 stop/start（生命周期）

四场全部通过、链路零重建：Docker FRR-2（3 链）、QEMU FRR-qemu-2（3 链）、IOU R9、Dynamips R9——节点均经持久化配置回归（NVRAM / frr.conf）、OSPF 回 Full（Dynamips 有 ~40 s 收敛窗口、期间瞬态丢包）、主机 E2E 回 0% 丢。2026-09-30 修复的"docker stop/start 废链路 L2"问题未复现（relay 路径无桥端口孤儿化问题）【实测】。

---

## 8. 结论——kernel datapath 的逐平台价值

| 平台 | filter 价值 | 性能价值 | 移除后的实际影响 |
|---|---|---|---|
| Docker | 8 种 kernel-only filter | **高**——全家族唯一快路径平台 | **严重**：RTT ×5–6、吞吐 ÷14–25、多流聚合消失 |
| QEMU | 8 种 kernel-only filter | 中——吞吐减半；virtio 杠杆 ×5.1→×2.2、多流不稳定 | **中等**：延迟无碍，容量与 virtio 故事退化 |
| IOU | 8 种 kernel-only filter（以太链也回落 relay 的 5 种） | 无可测 | **仅 filter 能力** |
| Dynamips | 8 种 kernel-only filter（同上回落） | 无可测 | **仅 filter 能力** |

**总评**。现行版本下全部链路都是用户态 relay：把 5 种 filter 当作支持集；relay 的 ~0.1–0.2 ms/段与 ~1.3 Gbps/源包络只会显现在原生转发快于它的平台上（Docker 明显、QEMU 体现在吞吐）；对瓶颈在仿真器本体的平台（IOU、Dynamips）保持原有期待即可。**kernel datapath 在今日版本下仅剩的独有价值 = 那 8 种高级 filter。**

---

## 9. 复现菜单（四场通用）

```bash
# 平台判定
link_get(<link>)                      # 无 kernel_datapath 键
link_available_filters(<link>)        # 5 种 legacy
link_update(<link>, filters={"rate": ["512kbit"]})   # 409 Unknown filter type（无指引）
link_update(<link>, filters={"delay": [50]})         # 409 expects 2 parameter(s)

# filter（丢包类 n ≥ 200；frequency_drop 用静默链）
{"delay": [50, 0]}  {"packet_loss": [10]}  {"frequency_drop": [3]}
{"corrupt": [30]}   {"bpf": ["icmp[icmptype]==8"]}   filters={}   # 清空 + 基线复核

# 性能：iperf3 单流/多流；RTT 类测量加受控宿主负载；delay 曲线用平行链同档
# 生命周期：node_stop -> node_start 中部节点；验证 NVRAM 自恢复、OSPF Full、E2E 0%
```

---

## 10. 引用（四份分场报告）

| 平台 | 仅 relay 版对照报告 | kernel datapath 基线 |
|---|---|---|
| Docker | `Kernel-DataPath-Docker-FRRDocker-无Kernel-对照实测.md` | `Packet-Filter-Test-方案与实施记录.md` + 项目 README（2026-09-30） |
| QEMU | `Kernel-DataPath-Qemu-FRRqemu-无Kernel-对照实测.md` | `QEMU-Kernel-DataPath-Test-方案与实施记录.md` §10/§11 |
| IOU | `Kernel-DataPath-Iou-CiscoIOU-无Kernel-对照实测.md` | `IOU-Kernel-DataPath-Test-方案与实施记录.md` §5/§6/§10 |
| Dynamips | `Kernel-DataPath-Dynamips-Cisco7200-无Kernel-对照实测.md` | `Dynamips-Kernel-DataPath-Test-方案与实施记录.md` §1–§10 |

*本文全部 relay 侧数字为 2026-10-04/05 经 GNS3 MCP 在 server `3.1.0.dev7+38cc7cc0a` 上的【实测】；kernel 侧为对上述基线记录的【转引】。标【推断】的内容为与实测一致的假说，非独立验证的机制。英文版：`Kernel-DataPath-NoKernel-Comparison-EN.md`。*
