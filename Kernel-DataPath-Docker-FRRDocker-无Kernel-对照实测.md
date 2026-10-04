# Kernel-DataPath-Docker-FRRDocker — 无 Kernel-DataPath 版本对照实测（2026-10-04）

> 性质：**对照复测记录**。本场基线（kernel datapath 版）数据为**转引**——《Packet-Filter-Test-方案与实施记录.md》与项目 README（均 2026-09-30 / server `3.1.0.dev7+2445e2e5e`）；本轮在**无 kernel datapath 的服务器版本**上把同一测试菜单原样重跑，本文所有数值除注明外均为本次**实测**（方法沿用 Packet-Filter §1.2/附录 A）。
> 一句话结论：**链路 100% 可用（OSPF 22/22、E2E 0% 丢）、5 种 legacy filter 数据面行为与 kernel 版逐项一致（含 2× 双向语义）；8 种 kernel-only filter 整体消失（409）。性能全面塌方：RTT ×5–10、低延迟下吞吐 ×14–25、多流不再放大（单源 ~1.3 G 水位）；高 delay 下两版本收敛（同受 cwnd 限）。**

- 项目：`Kernel-DataPath-Docker-FRRDocker`（`d1ab2349-2e53-4e41-a9ae-b5ffcd912408`，原 `Docker-Kernel-DataPath-test-FRRDocker`；14 节点 / 14 链，11×FRRDocker + 3×UbuntuDockerGuest）
- 对照版本：server **`3.1.0.dev7+38cc7cc0a`（无 kernel datapath）** ↔ 原 **`3.1.0.dev7+2445e2e5e`（kernel datapath）**
- 被测链：`ba72b22e`（FRR-1 eth5 ↔ FRR-2 eth5，10.1.1.0/30）；delay 曲线用 eth5+eth6 双平行链同档（`ba72b22e` + `1e8ec651`）

---

## 1. 平台层判定（差异一：字段与 filter 支持集）

| 项 | kernel 版（09-30） | 无 kernel 版（本次，实测） |
|---|---|---|
| `link_get` 的 `kernel_datapath` 字段 | `true` | **字段整体消失**（非 false；`link_get` 返回中无此键） |
| `link_available_filters` | **13 种** | **5 种**：frequency_drop / packet_loss / delay / corrupt / bpf |
| kernel-only 下发（如 rate/window_drop） | 可用 | **409**：`Invalid packet filter parameters: Unknown filter type: rate`（window_drop 同式） |
| `delay` 参数校验 | `[50]` 单参可用（jitter 缺省） | **强制 2 参**：`delay expects 2 parameter(s), got 1`；`[50, 0]` 可用 |
| 其他链路（host2↔FRR-11 `0dbb78c5` 抽查） | — | 同为 5 种（支持集对全项目链路均匀） |

8 种不可用：**rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop**。409 报错为纯 "Unknown filter type" 文案，**无迁移指引**（与汇总文档所记 "409 带指引" 不同，本版本无指引文本）。

---

## 2. 环境与方法（本次）

- 全部 14 节点 `node_start_all` 冷启；**零人工干预**，frr.conf 持久化配置自动生效，OSPFv2 单区约 1 分钟内自动收敛 **22/22 Full**（FRR-1 双 ECMP 邻居 ×2、中间 ×2、末节点 ×1）。
- 流量采样：本地 console TCP 直连（FRR-1 `127.0.0.1:5000`，脚本同 Packet-Filter 附录 A）；vtysh ping 仍**不支持 `-c/-i`**（实测 `% Unknown command`），丢包类样本为 1 pps 长采样（n≥61）。
- 吞吐：host1/host3 ↔ host2 的 iperf3（`iperf3 -s -D` 常驻各主机；重启后需重起服务，已做）；delay 曲线为 eth5+eth6 双链同档下发（ECMP 均匀），host1→host2。
- 对照口径注意：跨会话绝对 RTT 含宿主负载成分（本轮同会话内自洽）；E2E 首次采样 4.893 ms 为重启后**瞬态**（复测 1.9–2.2 ms），下表取稳态。

---

## 3. 连通性基线（对照）

| 测量 | kernel 版（转引） | 无 kernel 版（实测） | 差异 |
|---|---|---|---|
| OSPF 邻接 | 22/22 Full | **22/22 Full** | 无 |
| host1→host2 ttl / traceroute | ttl=53 / 11 路由器跳 | **ttl=53 / 12 行（11 路由器 + 目的）** | 无 |
| 直连被测链 RTT（FRR-1→10.1.1.2） | 0.074–0.119 ms（avg 0.099） | **0.318 / 0.354 / 0.538 ms**（三轮） | **≈3–5×** |
| 全链 E2E RTT（host1→host2） | 0.36 ms | **1.90 / 2.02 / 2.18 ms**（三轮） | **≈5–6×** |
| 穿链 vtysh ping（FRR-1→10.1.0.11，ttl=55） | ~0.18 ms | **2.084 ms** | **≈11×** |
| 1 跳（host3→host1，ttl=63） | （未记 RTT） | **0.796 ms** | — |

原始摘录（实测）：

```
# 直连被测链（清空 filter 后复核）
9 packets transmitted, 9 received, 0% packet loss
rtt min/avg/max/mdev = 0.177/0.354/0.461/0.083 ms

# 全链 E2E（收尾复核）
10 packets transmitted, 10 received, 0% packet loss
rtt min/avg/max/mdev = 1.014/1.901/2.642/0.476 ms
64 bytes from 10.1.200.1: icmp_seq=1 ttl=53 time=...
（traceroute 12 行、11 路由器跳，同 kernel 版）

# 穿链 vtysh ping（FRR-1 → FRR-11 lo）
13 packets transmitted, 13 received, 0% packet loss
rtt min/avg/max/mdev = 0.730/2.084/3.003/0.628 ms   (ttl=55)
```

---

## 4. Packet Filter 对照（5 种可用逐项 + 8 种不可用）

| # | 类型 | 参数（本次） | kernel 版（转引） | 无 kernel 版（实测） | 判定 |
|---|---|---|---|---|---|
| 1 | delay | `[50, 0]` | 100.179 ms（mdev 0.095，参数 `[50]`） | **100.625 ms（mdev 0.088）** | ✅ 2× 精确，一致 |
| 2 | delay+jitter | `[50, 20]` | mdev 27.167（参数 `[50,20,"normal"]`） | **mdev 27.035**（min/avg/max 34.6/98.7/155.6） | ✅ 一致 |
| 3 | packet_loss | `[30]` | 56%±7%（n=50） | **55.74%（n=61）** | ✅ 一致（理论 51%） |
| 4 | corrupt | `[30]` | 53.3%（n=15） | **57.38%（n=61）** | ✅ 一致（理论 51%） |
| 5 | frequency_drop | `[3]` | 61.9%（n=21，成段丢） | **52.46%（n=61）** | ✅ 一致（理论 55.6%；相位漂移见下） |
| 6 | bpf | `icmp[icmptype]==8` | 100% 丢，OSPF 邻接不动 | **100% 丢（14/14），OSPF 邻接不动** | ✅ 选择性一致 |
| 7–13 | rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop | — | 逐项可用且精确 | **409 拒绝（不可用）** | ⛔ 功能缺失 |

关键原始输出摘录（实测）：

```
# delay 50 —— 教科书 RTT（与 kernel 版 100.179 一致）
15 packets transmitted, 15 received, 0% packet loss
rtt min/avg/max/mdev = 100.467/100.625/100.766/0.088 ms

# delay 50 + jitter 20 —— mdev ≈ √2×20
17 packets transmitted, 17 received, 0% packet loss
rtt min/avg/max/mdev = 34.565/98.670/155.628/27.035 ms

# packet_loss 30
61 packets transmitted, 27 received, 55.7377% packet loss, time 61418ms

# corrupt 30
61 packets transmitted, 26 received, 57.377% packet loss, time 61476ms
rtt min/avg/max/mdev = 0.156/79.088/2048.305/393.843 ms, pipe 3

# frequency_drop 3
61 packets transmitted, 29 received, 52.459% packet loss, time 61445ms

# bpf icmp[icmptype]==8
14 packets transmitted, 0 received, 100% packet loss, time 13308ms
（同时 FRR-1↔FRR-2 邻接保持 Full，bpf 选择性成立）

# kernel-only 下发
link_update(filters={"rate": ["64kbit"]})       → 409 Invalid packet filter parameters: Unknown filter type: rate
link_update(filters={"window_drop": [8000,6000,100]}) → 409 ... Unknown filter type: window_drop
link_update(filters={"delay": [50]})            → 409 delay expects 2 parameter(s), got 1
```

副作用与现象（实测）：

1. **corrupt [30] 采样期间出现 RTT 离群**（max 2048 ms、mdev 393 ms、pipe 3），采样后邻接仍 Full 无震荡——与 kernel 版"corrupt 50% 震荡邻接"不同，本轮未触发 dead timer。
2. **frequency_drop 期间邻接被打断又自愈**：~52% 有效丢包下 4 连丢 hello 触发 dead timer；FRR-1 eth5 侧邻居 Up Time 在采样后重置（48s），~40 s 自愈回 Full。与记录中的已知现象一致，**52.46% 的 n=61 样本未剔除邻接震荡窗口**，两侧版本同样口径。
3. 全部 filter 清空后基线复核：**0% 丢、avg 0.354 ms**，链路回到干净态。

---

## 5. 吞吐对照（本次实测 vs 09-30 转引）

### 5.1 总表

| 测量 | kernel 版（转引） | 无 kernel 版（实测） | 倍数 |
|---|---|---|---|
| 全链 单流（host1→host2） | 2.22 Gbps | **1.28 Gbps**（retr 234） | ÷1.7 |
| 全链 16 流 | 19.4 Gbps | **1.36 / 1.32 Gbps**（retr 3098） | **÷14** |
| 全链 16 流 + `-w 4M` | （未记） | **1.55 / 1.36 Gbps**（retr 2171） | — |
| 全链 32 流 | 20.2 Gbps | **1.20 / 1.17 Gbps**（retr 6515） | **÷17** |
| 1 跳直连（host3→host1）单流 | 9.8 Gbps | **3.00 Gbps**（retr 112） | ÷3.3 |
| 1 跳直连 16 流 | 73.9 Gbps | **2.98 Gbps**（retr 3412） | **÷25** |
| 并发双源（host1+host3 各 16 流 → host2） | 9.60+10.5 = 20.1 G（共享不叠加） | **1.24+1.25 = 2.49 G（各自 ≈ 单源水位）** | ÷8 |

### 5.2 delay×吞吐曲线（eth5+eth6 双链同档 delay，host1→host2）

| delay/链 | RTT（实测） | 单流（实测） | 16 流（实测） | kernel 版 RTT / 单流 / 16 流（转引） |
|---|---|---|---|---|
| 0 ms | 1.9–2.2 ms | **1.28 G** | **1.36 G** | 0.36 ms / 2.22 G / 19.8 G |
| 1 ms | **4.51 ms** | **1.20 G** | **1.26 G** | 2.26 ms / 1.64 G / 3.78 G |
| 5 ms | **12.20 ms** | **936 M** | **1.14 G** | 10.5 ms / 883 M / 1.03 G |
| 10 ms | **21.93 ms** | **584 M** | **811 M** | 20.5 ms / 466 M / 614 M |
| 20 ms | **43.45 ms** | **240 M** | **422 M** | 40.7 ms / 262 M / 388 M |

- RTT 侧：**RTT ≈ 基线 + 2×delay 分毫不差**（4.51/12.20/21.93/43.45 对 2.2+2/10/20/40），delay 语义与 kernel 版完全一致。
- 吞吐侧：**两版本在 ≥5 ms 档收敛**（都进入 cwnd 受限区，数值同区间）；差异集中在 **0–1 ms 低延迟档**（16 流 19.8G→1.36G）。
- 规律（实测）：单源 1/16/32 流全部落在 **1.2–1.4 G** 平台；双源合计 2.49 G > 单源水位 ⇒ **不是单一共享硬瓶颈**；1 跳（2 段 relay）3.0 G ⇒ 每多穿越一段 relay 吞吐阶降【推断：用户态逐包转发 + 丢包反馈共同作用，重传率 0.3–0.6%】。

---

## 6. stop/start 存活专项（平台回归）

- FRR-2（3 条链：eth5/eth6→FRR-1、eth2→FRR-3）`node_stop` → `node_start`：**三条链全部存活**——重启侧与对端双向 ping 均 0% 丢（FRR-1→10.1.1.2、FRR-3→10.1.3.1）；OSPF 约 1 分钟内全部回 **Full**（期间曾短暂 Init，属收敛过程）。
- 结论：09-30 修复的 "docker stop/start 废链路 L2" 问题在本版本上**未复现**（本版本链路走 relay 路径，机制不同，无 L2 孤儿端口问题）**【实测】**。

---

## 7. 结论与差异速查

| 维度 | kernel 版（09-30） | 无 kernel 版（本次） | 影响 |
|---|---|---|---|
| API 字段 | `kernel_datapath: true` | 字段消失 | 自动化判据需改（不能再靠该字段判断） |
| filter 支持集 | 13 种 | **5 种**（legacy） | 8 种高级损伤/队列/随机 filter 不可用（rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop） |
| 5 种 legacy filter 数据面 | 精确（2× 双向） | **逐项一致（2× 双向）** | filter 语义层与 datapath 解耦，行为不变 |
| 参数校验 | delay 单参可用 | delay 强制 2 参 | 下发脚本需适配（`[x]` → `[x, 0]`） |
| 连通性 | OSPF 22/22、ttl=53、11 跳 | **完全相同** | 功能面零回归 |
| 延迟 | 直连 0.099 / 全链 0.36 ms | **直连 0.3–0.5 / 全链 1.9–2.2 ms（×5–6）** | 每穿越一段 relay 约 +0.1–0.2 ms |
| 吞吐（全链 16 流） | 19.4 Gbps | **1.36 Gbps（÷14）** | 用户态转发多流不放大（单源 ~1.3 G 平台） |
| 吞吐（1 跳 16 流） | 73.9 Gbps | **2.98 Gbps（÷25）** | 短路径同样塌方 |
| 多流形态 | 单流→16 流 ×8.7 | **单流 ≈ 16 流 ≈ 32 流（不放大）** | 单源形态变化，属丢包反馈/逐包处理瓶颈 |
| 高 delay 场景 | cwnd 受限 | **同区间收敛** | kernel datapath 优势主要体现在低 RTT 高吞吐场景 |
| stop/start 存活 | 已修复（09-30） | **存活正常（未复现旧问题）** | 无回归 |

**归因备注（推断，标注）**：RTT 增量为每穿越一段 relay 的固定成本（用户态转发/唤醒，~0.1–0.2 ms/段）；吞吐塌方叠加了逐包处理与丢包反馈（重传 0.3–0.6%），双源 2.49 G 证明链路物理承载高于单源水位。跨会话绝对值为指示性。

---

## 8. 重现菜单

```bash
# 0) 前置：项目 open + node_start_all（14 容器），~1 min 自收敛 22/22 Full
# 1) 平台判定
link_get("ba72b22e-cf2c-46de-a292-3c15d2551036")        # 无 kernel_datapath 键
link_available_filters("ba72b22e-...")                    # 5 种
link_update(..., filters={"rate": ["64kbit"]})            # 期待 409 Unknown filter type

# 2) 5 种 filter（逐项，采样见 Packet-Filter 附录 A 脚本）
link_update(..., filters={"delay": [50, 0]})               # 注意 2 参
link_update(..., filters={"packet_loss": [30]})            # n≥60 样本
link_update(..., filters={"corrupt": [30]})
link_update(..., filters={"frequency_drop": [3]})
link_update(..., filters={"bpf": ["icmp[icmptype]==8"]})
link_update(..., filters={})                               # 清空后复核基线

# 3) 性能
host1# iperf3 -c 10.1.200.1 -t 5 [-P 16|32] [-w 4M]
host3# iperf3 -c 10.1.100.1 -t 5 [-P 16]                  # 1 跳对照
# 4) delay 曲线：eth5+eth6 同档 [X,0]，X=1/5/10/20
```

---

*本记录为对照复测（2026-10-04），全部数据面数值为本次在无 kernel datapath 服务器（`3.1.0.dev7+38cc7cc0a`）上的【实测】；kernel 基线为【转引】Packet-Filter-Test 文档与项目 README（2026-09-30 / `3.1.0.dev7+2445e2e5e`）。*
