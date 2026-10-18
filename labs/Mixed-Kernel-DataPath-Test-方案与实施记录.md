# Mixed-Kernel-DataPath-Test 方案与实施记录

> 2026-10-04 建成并全量验证。项目 `Mixed-Kernel-DataPath-Test`（ID `bc54cfdf-cbbf-4363-97a2-e63f8b80c9d5`）。
> 目的：在**一个项目内混合 7 种节点类型 + 1 台 Ethernet switch**（dynamips / FRRDocker / IOU / IOL-XE docker / SR Linux / XRd docker / Ubuntu docker），测试**当前版本** kernel datapath 的真实效果。
> 本文所有结论除明确标注【转述】/【推断】外，均为本次实测（证据：MCP link API 原始返回、设备 console 输出）。
> **同日更新（2026-10-04 稍晚）**：§5 记录的 filter 静默失效缺陷已由 gns3server 团队修复（kernel datapath mixin 单点 ownership 门控：对端不再以空 filter 对共享锚点做破坏性 reconcile）并重启服务。**§5.4 为修复后的全量复验记录**（§5.1–5.3 保留修复前现场原文）。

## 1. 背景与问题

服务端从 `3.1.0.dev7+c9692ff9a`（四版单类型实验场所用版本）更新到 **`3.1.0.dev7+842f1eecb`** 后，此前记录的若干"已知限制"需要复核：

1. Ethernet switch 相关链路：旧记录"switch↔switch 回落 relay（仅 5 种 filter）、单侧挂 switch 的上联链 kernel"是否仍然成立？
2. IOL-XE docker（unix-socket NIO）链路：旧记录"恒 relay"是否仍然成立？
3. 混合拓扑下 8 条上行链路（含交换机端口）的 kernel 判定与 filter 能力清单。
4. **filter 数据面是否真的生效**——API 说 kernel、说开放 13 种，不等于数据面真的执行。

## 2. 平台

- GNS3 server **3.1.0.dev7+842f1eecb**（单 compute `local`）
- 节点模板：Ethernet switch（内置）、Cisco 7200（dynamips，`c7200-adventerprisek9-mz.152-4.M11`）、FRRDocker（`gns3/frr:latest`，FRR 10.x）、Cisco IOU L3（`x86_64_crb_linux-adventerprisek9-ms.iol`）、Cisco IOL-XE docker（`iol-xe/iol-xe:17-18-02`）、SRLinux（`ghcr.io/nokia/srlinux`，v26.x）、XRd Control Plane（`ios-xr/xrd-control-plane:24.4.1`）、Ubuntu Docker Guest（`gns3/ubuntu:noble`）×2
- device_type tag：R1/FRRDocker-1/IOU-R-1/CiscoIOL-XE-1 = `cisco_ios_telnet`（device 工具直通，实测 IOL-XE docker 的 netmiko 直通可用）；XRdControlPlane-1 = `cisco_xr_telnet`；SRLinux-1 与两台 Ubuntu 走 ws console

## 3. 拓扑与编址

```
        R1(dynamips)   FRRDocker-1   IOU-R-1   CiscoIOL-XE-1
             │              │            │            │
        e0   │         e1   │       e2   │       e3   │
             └──────────────┴── Switch1 ─┴────────────┘
        e4   │         e5   │       e6   │       e7   │
             │              │            │            │
        SRLinux-1    XRdControlPlane-1  U1         U2
             (U1=UbuntuDockerGuest-1，U2=UbuntuDockerGuest-2)

 对照链（不经交换机）：U1 eth1 ──────────── U2 eth1
```

- 交换机段 `10.77.0.0/24`（全部同网段，纯 L2，无路由协议）：
  R1 `.11`、FRRDocker-1 `.12`、IOU-R-1 `.13`、CiscoIOL-XE-1 `.14`、SRLinux-1 `.15`、XRdControlPlane-1 `.16`、U1 `.100`、U2 `.101`
- 直连对照段 `10.78.0.0/24`：U1 `.1`、U2 `.2`
- 静默措施：IOS 系 `no cdp run`（R1 另 `no keepalive`）、XRd `no cdp`、SRLinux `system lldp admin-state disable`；无路由协议
- 持久化：R1/IOU-R-1/CiscoIOL-XE-1 `write memory`；FRRDocker-1 `wr`（/etc/frr/frr.conf）；SRLinux-1 `commit save`；XRd `commit`（/xr-storage）；U1/U2 `/etc/network/interfaces`（eth0+eth1，分列语法）
- 快照：`baseline-mixed-kernel-datapath-clean`（`500704a7-a430-4f1e-8ccd-bc86d22a46a9`）

### node_id / link_id 清单

| 节点 | 类型 | node_id | console |
|---|---|---|---|
| Switch1 | ethernet_switch | `c639ffc6-020a-4664-8528-2de0eda5aef1` | — |
| R1 | dynamips | `c6350d43-a236-4e92-9af8-0e9291e8a97c` | 5049 |
| FRRDocker-1 | docker | `5e9dbb33-e23f-4b53-8621-78755e757384` | 5050 |
| IOU-R-1 | iou | `ae4aee07-6806-41d6-a72e-125bedf8783c` | 5051 |
| CiscoIOL-XE-1 | docker | `6b0b4b79-8cc0-4234-b3a3-34a3fd5fe23b` | 5052 |
| SRLinux-1 | docker | `ccf469c0-9971-46f2-b385-765f3c652536` | 5053 |
| XRdControlPlane-1 | docker | `8fd7f5cf-14c0-478c-9640-7d0b04d76dc0` | 5054 |
| UbuntuDockerGuest-1 | docker | `4d64b422-8204-4d6b-9672-ddaf17615933` | 5055 |
| UbuntuDockerGuest-2 | docker | `7c1c7746-099f-4e28-b29e-f0fafbd28e18` | 5056 |

| 链路 | link_id | kernel |
|---|---|---|
| Switch1 e0 ↔ R1 f0/0 | `83040534-7659-4c16-a33a-729815142faa` | true |
| Switch1 e1 ↔ FRRDocker-1 eth0 | `9e1bfca8-7f70-40d1-b0ef-2c50624d3239` | true |
| Switch1 e2 ↔ IOU-R-1 e0/0 | `36d4d747-4f09-4ceb-a77d-de25d5d89adf`（2026-10-04 复验时删建、顺序不变；原 `e1883d9d-…`） | true |
| Switch1 e3 ↔ CiscoIOL-XE-1 e0/0 | `07df6fb3-ba3e-4e15-980c-ff02909c51c8` | true |
| Switch1 e4 ↔ SRLinux-1 e1-1 | `d9c8625d-d363-46da-a087-b315c9f86131` | true |
| Switch1 e5 ↔ XRdControlPlane-1 Gi0/0/0/0 | `4838e02e-009a-49fd-9152-5311d8c034a6` | true |
| Switch1 e6 ↔ UbuntuDockerGuest-1 eth0 | `6c457788-c5a4-4f73-8102-ddb5e11f6763` | true |
| Switch1 e7 ↔ UbuntuDockerGuest-2 eth0 | `4689590e-4312-49bd-95f3-5a6152d8f4ed` | true |
| U1 eth1 ↔ U2 eth1（直连对照） | `cd918e9e-03f9-469b-9a3b-0d58ab7ea81e` | true |

## 4. kernel datapath 判定与 filter 能力普查（问题 1/2/3）

- **8 条交换机上行链全部 `kernel_datapath: true`**，且 `link_available_filters` **8/8 返回全部 13 种 filter**（frequency_drop / packet_loss / delay / corrupt / bpf / rate / reorder / gemodel / duplicate / seed / limit / quota / window_drop），含全部 kernel-only 类型
- 直连对照链同样 `kernel_datapath: true`、13 种全开放
- **旧记录作废（同版本服务器复核）**：
  - 在现存的 Comprehensive Test 项目里现场复核：**Switch1↔Switch2（e20↔e20）`kernel_datapath: true` 且开放 13 种**。旧记录"switch↔switch 回落 relay（仅 5 种 filter）"是服务器更新前的状态，**在 842f1eecb 上已不成立**
  - **IOL-XE docker 链路 `kernel_datapath: true` 且开放 13 种**。旧记录"IOL-XE unix-socket NIO → 链路恒 relay"同样已被服务器更新推翻
- 结论【实测】：**当前版本对"以太链路"的 kernel 化已全覆盖**——所有节点类型（dynamips/docker/IOU，含 IOL-XE 与交换机端口）的以太链都走 kernel datapath，API 层面不再有 relay 差异（串口链不在此列，见四版单类型实验场记录）

## 5. 核心发现：交换机终结链路的 filter **静默失效**（数据面）

API 全绿 ≠ 数据面生效。本次在**同一项目、同一服务器**上做了严格的 A/B 对照：

### 5.1 A 组：经交换机（Switch1 e0–e7）——全部无效

| # | 链路 | filter 设置 | 方式 | 实测 | 预期（若生效） |
|---|---|---|---|---|---|
| 1 | 6 条上行链同时 | delay [50] ×6 | 并行下发 | ping 全目标 RTT 与基线一致（R1 14ms / FRR 0.07 / IOU 0.69 / IOL-XE 0.53 / SRL 1.7 / XRd 1.3 / U2 0.05） | 各 +100ms |
| 2 | Switch1 e0 ↔ R1 | bpf ["icmp"] | 并行 2 条 | ping R1 **0% 丢包**（5.6/25.9/8.3ms）正常通 | 100% 丢包 |
| 3 | Switch1 e1 ↔ FRR | frequency_drop [-1]（**全丢**） | **单条下发** | ping FRR **0% 丢包**（0.05ms）正常通 | 100% 丢包 |
| 4 | Switch1 e0 ↔ R1 | bpf ["icmp"] + `link_reset` | 重置链路 | 重置后仍 **0% 丢包** | 100% 丢包 |

API 侧全程确认：`kernel_datapath: true`、`filters` 字段回显设置值、`link_available_filters` 13 种全开放。**数据面零效果**——包括"全丢"级别的 frequency_drop -1，链路仍 100% 转发。

### 5.2 B 组：不经交换机（U1 eth1 ↔ U2 eth1 直连）——全部精确生效

| # | filter | 设置 | 实测 | 理论/判定 |
|---|---|---|---|---|
| 1 | delay | [50] | RTT 100.129ms（基线 0.083ms） | +100ms = 2×50 **精确** ✓ |
| 2 | bpf | ["icmp"] | 100% 丢包 | 选择性丢 ICMP ✓ |
| 3 | rate | ["10mbit"] | iperf3 **9.25 Mbps**（基线 12.8 Gbps） | 10mbit 塑形 + TCP 开销 ✓ |
| 4 | packet_loss | [20] | **36.67%** 丢（300 包） | 1−(0.8)² = 36% 双向规律 **精确** ✓ |
| 5 | frequency_drop | [3] | **55.33%** 丢（300 包） | 1−(2/3)² = 55.56% eBPF 精确计数 ✓ |
| 6 | corrupt | [50] | **70%** 丢（100 包） | 收包率 0.5² = 25% → 丢 75%（1.2σ 内）✓ |

### 5.3 判定与根因

- **结论【实测】**：同一服务器、同一项目内，**交换机终结链路的 filter 在 API 上"接受并回显"，但数据面完全不执行**（delay / bpf / frequency_drop-1 三种语义迥异的 filter 均零效果；`link_reset` 无效）。直连链同 filter 精确生效，排除"filter 引擎整体故障"。
- 影响面【实测+推断】：本项目 8 条上行链（Switch1 的每一个端口）全部受影响；Comprehensive Test 的 switch 相关链路（含 switch↔switch）同样按此机制运行（其 API 返回与本文一致，未做数据面重复验证【推断】）。即：**凡链路一端是 ethernet_switch 节点，filter 静默失效**。这是本版服务器在 kernel 化 switch 链路时留下的实现缺口。
- 实际使用建议：要跑"链路损伤"类实验（delay/loss/rate…），**用节点直连链**，不要用 ethernet switch 中转链；交换机链路只能用于纯转发拓扑。（**2026-10-04 已修复，见 §5.4；该建议作废**——交换机链路现已可做损伤实验，注意其单侧单向语义）

### 5.4 修复后复验（2026-10-04，服务端修复并重启后）

修复方式【转述团队】：现场复现 → 排除"旧字节码"假说 → compute 层分离实验锁定"对端 tc reset 抹除"根因 → 在 kernel datapath mixin 单点加 **ownership 门控**（对端不再对共享锚点做破坏性 reconcile）→ 2 条单测 + e2e switch-first 段先红后绿（2110 单测、378s 全量 e2e 通过）。以下复验全部为本次实测（MCP + 设备 console）：

| # | 场景 | 操作 | 复验结果 | 修复前（§5.1） |
|---|---|---|---|---|
| 1 | Switch1 e1↔FRR（switch 为 node 0，**原故障顺序**） | 遗留 delay[50]，节点启动后被动生效 | RTT **50.2ms**（首包 101ms＝ARP+单向时延） | 0.05–0.1ms 无效 |
| 2 | 同上 | 清空 filters | 0.064ms 回基线（**清除机制可用**） | 曾"清了也不生效" |
| 3 | 同上 | 显式重设 delay[50] | **50.1ms 稳定**（min/avg/max=50.08/50.11/50.18，mdev 0.034） | 无效 |
| 4 | 同上 | bpf ["icmp"] | **100% 丢包**（5/5） | 无效 |
| 5 | 同上 | frequency_drop [3]（30 包 ×2 样本） | **40% / 30%**（合计 21/60 ≈ **1/3**） | 无效 |
| 6 | Switch1 e0↔R1（dynamips 对端） | delay[50] | 基线 23.8ms → **70.5ms**（+50，本体噪声内） | 无效 |
| 7 | Switch1 e2↔IOU（iou 对端） | delay[50] | 基线 0.84ms → **50.77ms**（mdev 0.032） | 无效 |
| 8 | **端点顺序反转**（删建为 IOU 在前的新链） | delay[50] | **50.78ms**（与顺序无关） | （该序旧代码本可用） |
| 9 | stop/start 持久化（FRR 重启，filter 保持下发状态） | node stop→start | 重启后 **50.1ms 依旧生效** | 旧复现步骤当时"仍旧无效" |
| 10 | 直连链回归（U1↔U2 eth1） | delay[50] | **100.27ms**（2×，mdev 0.057，无回归） | 本就正常 |

**复验结论（实测）**：
- 交换机终结链路的 filter 数据面**已完全生效**：delay / bpf / frequency_drop 三族精确起效；清空、stop/start 持久化、删建重建均正常；节点直连链无回归。
- **有效语义（与直连链的差异，实测）**：交换机链路的 filter 装在单侧锚点（交换机侧）上，只作用于**一个方向**——`delay [50]` → RTT **+50ms**（直连链因两端各装一次为 +100ms=2×）；`frequency_drop [3]` 有效丢包 ≈ **1/3**（直连链为 1−(2/3)²=55.6%）。丢包节奏在两个样本间有确定性相位漂移，【推断】为网段偶发广播包（IPv6 RS/MLD 等）掺入 eBPF 计数器所致（未深究，不影响"生效"结论）。
- **端点顺序无关（实测）**：switch 在 node 0（原故障顺序）与 node 1 均正常——与 ownership 门控的修复方式自洽。
- 收尾：9/9 链路 filters 全部清空回 `{}`、kernel_datapath 均 true；FRR 0.085ms / R1 20.1ms / 直连 0.057ms 回基线。

> 附修正：Switch1 实为 **8 口**（e0–e7，复验时 `node_get` 确认），此前"21 口"的说法有误。

## 6. 性能与基线数据

- 交换机段 RTT 基线（U1 出发，清理后复验）：R1 **24.7ms**（dynamips 本体慢，与四版记录一致）、FRR **0.08ms**、IOU **0.46ms**、IOL-XE **0.68ms**、SRL **1.83ms**、XRd **0.87ms**、U2（过交换机）**0.87ms**
- 直连链（docker↔docker，kernel）基线 RTT **0.067ms**，iperf3 单流 **12.8 Gbps**（7.44 GB/5s，36 retrans）
- 交换机 L2 转发本身无性能问题（docker↔docker 过交换机 0.05–0.9ms），**失效的只是 filter（伤损/限速）功能**

## 7. stop/start 持久化复验

`node_stop_all` → 快照 `baseline-mixed-kernel-datapath-clean` → `node_start_all`，等待全量启动后：

- **8/8 路径全通 0% 丢包**：R1 **31.5ms**（NVRAM）、FRR-1 **0.10ms**（/etc/frr/frr.conf）、IOU-R-1 **0.80ms**（NVRAM）、CiscoIOL-XE-1 **0.97ms**（write memory）、SRLinux-1 **2.8ms**（config.json）、XRdControlPlane-1 **3.9ms**（/xr-storage）、U2 过交换机 **0.14ms**、U1↔U2 直连 **0.11ms**（/etc/network/interfaces 双接口）
- 重启后重挂 `delay [50]` 到 Switch1 e0↔R1 链：ping R1 **26.5/31.5/36.6ms ≈ 基线**（无 +100ms）——**交换机链路 filter 静默失效可复现**（§5 结论在 stop/start 后依然成立）
- 复验后 filter 已清空，项目处于干净基线

## 8. 坑清单（本轮新增）

1. **Ubuntu docker console 禁止发 `\x03`**：以此开头会让 ws 会话立刻关闭、后续命令全部丢弃（与 FRR/vtysh 会话"开头必发 \x03 兜底"的习惯**相反**）。docker console 会话偶尔也会"连上但无输出"，重试一次即可
2. **ws console token 单次有效**：同一 token 第二次连接会被静默拒绝（无任何报错输出），必须每次 `node_console` 重新取
3. **热插拔链路后容器内接口不会自动配**：U1/U2 的 eth1 直连链建立后需手动 `ip link set eth1 up` + 配地址；并行给两端配置时注意先后（U1 首测 100% 丢包即对端尚未就绪所致）
4. **SRLinux 子接口必须显式绑定 network-instance**：`set / network-instance default interface ethernet-1/1.0`，漏掉则地址配了也 ping 不通（老坑再次复现）
5. **IOL-XE docker 的 device 工具直通可用**：`device_type:cisco_ios_telnet` tag + device_config_send 对 IOL-XE/IOL 的 netmiko 直通实测正常（含 `write memory`）
6. FRRDocker 用 `device_type:cisco_ios_telnet` tag 走 device 工具正常（vtysh 兼容 IOS 语法，`wr` 输出 `Integrated configuration saved to /etc/frr/frr.conf [OK]`）

---

*Built & verified 2026-10-04 via GNS3 MCP（链路/节点/设备操作全程走 MCP：device_config_send / node_console+websocat / link_update / link_available_filters / snapshot_create）。数据面结论均为本次实测。*
