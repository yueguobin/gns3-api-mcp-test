# Dynamips-Kernel-DataPath-Test 方案与实施记录

> 2026-10-01 建成并全量验证。项目 `Dynamips-Kernel-DataPath-test-Cisco7200`（ID `796d08d4-7560-41f5-bd9b-2330e48f639e`）。
> 目的：验证 GNS3 3.1 dev 的 kernel-datapath 链路在 **Dynamips 节点（Cisco 7200 / c7200）** 上的实现与效果，与《Docker-Kernel-DataPath-test-FRRDocker》《Qemu-Kernel-DataPath-test-FRRqemu》《Iou-Kernel-DataPath-test-CiscoIOU》互为对照。
> 本文所有数据面结论除明确标注【转述】/【推断】外，均为本次实测（证据：各步 console/link API 原始输出、抓包、只读内核对象观察）。

## 1. 背景与问题

服务端本轮新增 Dynamips 的 kernel datapath（`feat(controller): offer Dynamips the kernel datapath` / `feat(dynamips): anchor every Ethernet port on a persistent TAP`）【转述·源码 commit 标题】。Docker/QEMU/IOU 三版实验场已分别验证，Dynamips 版悬而未决的问题：

1. dynamips↔dynamips 以太链路是否走内核数据面？dynamips↔docker 混合链路呢？
2. dynamips **串口**链路（非以太端口）是否按设计留在 relay？
3. kernel 链上 13 种 filter 是否全开放且数据面精确？relay 链开放哪几种、kernel-only 是否被拒？
4. suspend/resume 在 dynamips kernel 链上是否原生生效？
5. seed 可复现性在 dynamips 平台是否成立（IOU 版有 CDP 干扰坑）？
6. dynamips 的延迟/吞吐量级与 docker/qemu/iou 差多少？
7. 节点 stop/start 后锚点生命周期是否自愈（Dynamips 的 "stop is not close" 语义）？

## 2. 平台

- GNS3 server **3.1.0.dev7+c9692ff9a**（单 compute `local`，`enable_kernel_datapath` 开启）
- compute capabilities：`ubridge_tap: true`、`ubridge_tc`（netem: delay/jitter/loss/dup/corrupt/rate/reorder/gemodel/dist/seed/limit；ebpf: nth/quota/window/flow）
- **Cisco 7200 模板**（`2dd24853-f656-43cf-89ac-a6b83482b708`）：镜像 `c7200-adventerprisek9-mz.152-4.M11.image`（IOS 15.2(4)M11），npe-400，RAM 512MB，console=telnet，tag `device_type:cisco_ios_telnet`
  - 适配器：slot0=`C7200-IO-FE`（FastEthernet0/0）+ slot1=`PA-2FE-TX`（FastEthernet1/0、1/1）= 3×FE；R2/R3 另加 slot2=`PA-4T+`（Serial2/0-3）
- 主机：Ubuntu Docker Guest ×2（`gns3/ubuntu:noble`，iperf3/ping/tshark 侧脚本齐全）

## 3. 拓扑与编址

```
 host1 ── R1 ══╪══ R2 ── R3 ── R4 ── R5 ── R6 ── host2
(10.4.100.1) f0/0  f1/0+f1/1  f0/0                          f1/1  (10.4.200.1)
                    └─ R2 Serial2/0 ── R3 Serial2/0（relay 对照，不进 OSPF）
```

- Loopback `10.4.0.N/32`；链段 `10.4.{1..6}.0/30`（小号 .1；seg1/seg6 为 R1↔R2 双平行链）；串口 `10.4.7.0/30`；主机网 10.4.100/200.0/24（网关 .254）
- OSPFv2 单区域：每台 `router ospf 1` + `router-id 10.4.0.N`，接口级 `ip ospf 1 area 0`，transit 接口 `ip ospf network point-to-point`
- 串口：hdlc，R2 侧 `clock rate 2000000`（被镜像取整为 2016000，正常）
- 持久化：6 台 `write memory`（NVRAM）；主机 `/etc/network/interfaces`（busybox 分列语法，node stop/start 自动应用）；R1 全局 `no cdp run`
- 快照：`baseline-dynamips-kernel-datapath-clean`（`32acdeb0-7e1f-446a-9cd4-0559ce5a3515`）

### node_id / link_id 清单

| 节点 | node_id | console |
|---|---|---|
| R1–R6 | `6957bc25…` / `10303b82…` / `28a68656…` / `f62841f1…` / `aaa2bc8c…` / `93e9dfc7…` | 5000-5005 |
| host1/host2 | `dc4b2597…` / `0f27eb3e…` | 5006/5007 |

| 链路 | link_id | kernel |
|---|---|---|
| seg1 R1 f1/0 ↔ R2 f1/0 | `150b7833-52f2-4f0e-9e13-dd9458123fd8` | true |
| seg6 R1 f1/1 ↔ R2 f1/1（平行） | `9fcf1712-8402-413c-b33d-8ba587d0dcd6` | true |
| seg2 R2 f0/0 ↔ R3 f0/0（filter 主测链） | `593e7f67-1be8-48cb-a94e-100448e21293` | true |
| seg3 R3 f1/0 ↔ R4 f1/0 | `bf236a39-5384-4014-a12f-1c48e72aabcc` | true |
| seg4 R4 f1/1 ↔ R5 f1/0 | `8467d18d-068a-4426-a027-45be6d97a211` | true |
| seg5 R5 f1/1 ↔ R6 f1/0 | `058048f3-d27e-4c2d-81b5-6f04c1898ce9` | true |
| host1 R1 f0/0 ↔ host1（混合链） | `57f10402-8e44-47d8-9f3e-ca6e66e7fb35` | true |
| host2 R6 f1/1 ↔ host2（混合链） | `5e20a252-40b9-445f-a7bd-0bffa8eddc2c` | true |
| 串口 R2 s2/0 ↔ R3 s2/0 | `2e73b4c7-5c41-43a5-a30f-2983be2e00c6` | **false** |

## 4. kernel datapath 判定（问题 1/2）

- **8 条以太链全部 `kernel_datapath: true`**，含 **dynamips↔dynamips**（6 段）与 **dynamips↔docker 混合**（2 条主机链）
- **串口链 `kernel_datapath: false`**（relay）——按"非以太端口逐端口排除"，同节点其它以太端口不受影响（R2 同节点 3 条以太链仍 true）
- 内核对象实测（只读 `ip link` 观察）：
  - 锚点 TAP 命名 `gd{node_id[:8]}e{slot}p{port}`，如 R2 的 `gd10303b82e0p0/e1p0/e1p1`
  - 每条 kernel 链一个内核桥 `gns3{link_id}`；seg2 桥 `gns3593e7f671be` 成员**恰好**两个锚点（R2+R3）
  - 混合链桥 `gns357f104028e4` = R1 锚点 + docker veth（`gvdc4b2597e0p0`）
- `link_available_filters`：kernel 链 **13 种全开放**；relay 串口链仅 5 种旧版（frequency_drop / packet_loss / delay / corrupt / bpf）
- 对 relay 串口链下发 kernel-only filter（gemodel）→ **错误带指引**："Packet filter(s) gemodel only run on a kernel-datapath link (tc netem on the veth host end); this link is wired on the uBridge relay — delete and recreate the link to switch it to the kernel datapath (Original 409 Error)"
- 连接建立于双端 stopped 状态（deferred wiring 路径），节点 start 后自动挂线

## 5. 路由与端到端验证

- OSPF 邻接 12/12 全 FULL（R1=2、R2=3、R3=2、R4=2、R5=2、R6=1；串口不入 OSPF）
- R1 路由表：所有远端前缀双下一跳 `via 10.4.6.2 (f1/1)` + `via 10.4.1.2 (f1/0)`——双平行链 ECMP 成立
- host1→host2：30/30 收，0% 丢，**ttl=58**（6 台路由器各减 1），RTT avg ~234ms

## 6. Filter 实测（问题 3/4/5，全部【实测】）

换算规律与其它三版一致：**filter 双向各生效一次**（RTT 丢包 = 1−(1−L)²，RTT delay = 2×单向）。
主探针：R2 IOS ping → 10.4.2.2（`ping 10.4.2.2 repeat N timeout 1`，单跳穿 seg2），单跳基线 **min/avg/max = 4/37/72 ms，100/100**。

| # | filter（seg2 除注明） | 配置 | 实测 | 理论/判定 |
|---|---|---|---|---|
| 1 | delay | [50] | min/avg 100/140ms | 4/37 + 2×50 ✓ |
| 2 | delay+jitter+dist | [10,3,normal] | 20/59/96ms | +2×10 底 + 抖动 ✓ |
| 3 | packet_loss | [10] | 79%（159/200） | 81%（1σ 内）✓ |
| 4 | corrupt | [50] | 33%（20/60） | 25%（1.5σ 内）✓；旁证 OSPF hello Bad Checksum、邻接震荡 |
| 5 | frequency_drop | [3] | **44%（44/100）** | 44.44%，eBPF 精确 ✓（丢包图案呈周期） |
| 6 | bpf | [icmp[icmptype]==8] | 0%（0/10） | 选择性丢 echo request ✓ |
| 7 | gemodel | [10,10,50] | 66% / 64%（两轮，100 包） | 单向 p/(p+r)(1−h)=25% → 56.25%；实测丢 ~35%，突发型方差大于二项分布，如实记录 |
| 8 | rate | [512kbit] | 1400B：60/77/92ms | 基线 + 2×(1442×8/512k)=45ms ✓ |
| 9 | reorder | [50,0,10]+delay[20] | 100/100 收齐，**8 处倒置**（基线 0 处） | 到达序 3→1、8→7、38→36、58→53… ✓ |
| 10 | duplicate | [20] | **+47 DUP/100 包** | 双向各 20%≈40 ✓ |
| 11 | quota | [20000,100]（1400B） | 前 **14 帧**通 → 断崖全丢 | 20000÷1442≈13.9 帧 ✓ |
| 12 | window_drop 三参 | [15000,3000,100] | seq 98→129 单一黑洞 **3.145s**，窗外 0 丢 | outage 3000ms 精确 ✓ |
| 13 | window_drop 四参 | [15000,3000,100,8000] | 4 个窗，窗长 3.23-3.37s，周期 **8.17/7.90/8.02s**，窗外零丢 | 周期 8.0s 精确 ✓ |
| 14 | limit（delay[500] 对照） | limit=[10] vs [1000] | 2 路并发（各 100 包@10ms）：**limit10 丢 74-77%**；**limit1000 丢 0%** | 队列深度尾丢语义 ✓ |
| 15 | seed（host1↔R1 静默链） | packet_loss=[20]+seed | §6.2 | 逐位可复现 ✓ |
| 16 | suspend（kernel 原生） | true/false | 挂起 0/5；恢复 5/5；邻接保持 FULL | anchor admin-down ✓ |
| 17 | relay 串口 delay（对照） | [50] | RTT 120/147/160ms（基线 4/49/64） | Δ≈100ms=2×50 ✓ |
| 18 | 全链 delay ×5 段（E2E） | [5]×6 链 | Δavg≈43ms（同时段 A/B） | 2×5段×5=50ms（多跳噪声 ±30ms）✓ |

### 6.1 seed 可复现性（问题 5，IOU 版 CDP 坑未复现）

host1↔R1 静默链（R1 `passive-interface FastEthernet0/0` 临时设置，测完还原；R1 全局 `no cdp run` 已持久化），packet_loss[20]+seed，`ping -c 100 -i 0.01`：

| 轮次 | 操作 | 结果 |
|---|---|---|
| A | seed=12345 | 46/100 收，md5 `7c2ec9af…` |
| B | seed=77777 | 64/100 收，md5 `f6e66392…`（与 A 差 46 行） |
| C | 换回 12345 | 46/100 收，md5 与 A 一致、**diff=0 逐位相同** ✓ |

- **seed 包级复现成立**（A/C 零差异），IOU 版需 `no cdp run` 的前置在本场同样具备（R1 已持久化关闭 CDP）
- 短窗采样偏差记录：seed=12345 的**前 100 包**丢包 54%（理论 36%），同 seed 300 包收敛到 39%；无 seed 三轮 137/149/163 包分别 27.0%/33.6%/36.8%。seed 决定的是确定性图案，短窗内密度可偏离期望值，长窗回归——**复现实验用 100 包对比时勿以丢包率判断成败，看图案 md5**

### 6.2 编排与测量坑（本轮新增）

1. **console 回放污染**：本地 telnet console 每次连接会回放滚动缓冲，自动解析时必须取**最后一条** summary 行（曾把历史输出误读为"5% 丢包"，实为上一轮的旧 summary）
2. **长 ping 超 device 工具超时**：高丢包下 `repeat 100+ timeout 1` 每丢包等 1s，netmiko 子任务超时并以 `status:"failed"` 返回（按错误契约上报，符合预期）；改用**本地 console TCP 直连**（`127.0.0.1:500x`）自计时脚本
3. **corrupt 50% 会打乱 OSPF**：hello 校验和失败 → 邻接 LOADING→FULL 震荡 ~10s；震荡期间 E2E 出现 R1 "Destination Host Unreachable"（路由暂时丢失）。**大毁伤 filter 测试后要等路由收敛再测下一项**，否则测到的不是 filter 行为
4. window_drop 短窗 vs MCP 编排延迟（同 Docker/QEMU/IOU 版）：start 需留 ≥15s 余量

### 6.3 链路抓包（kernel 链 capture）

`link_capture_start` → ping → `link_capture_stop` → `link_capture_download`（curl 带 ticket 下载）正常。pcap 26 帧：ICMP 16、OSPF 6、**IOS Ethernet keepalive（loop, 0x9000）3、CDP 1**——后两者即 netem RNG 的潜在噪声源（§6.1 静默链方法论的同源物）。

### 6.4 suspend/resume

挂起 seg2 → R2 ping R3 **0/5**；恢复 → **5/5**（RTT 正常）；挂起 ~20s 内 R2 的 OSPF 邻接保持 FULL（dead timer 40s 未到）。

## 7. 性能基线（问题 6，对照前三版）

| 指标 | Dynamips 6 跳（本项目） | IOU 6 跳 | QEMU 6 跳 | Docker 11 跳 |
|---|---|---|---|---|
| host↔host RTT | **203-270 ms**（ttl=58） | 3.71 ms | 4.58 ms | 0.36 ms |
| 每跳 | **~35-40 ms** | ~0.62 ms | ~0.7 ms | <0.1 ms |
| iperf3 单流 | **524 Kbps**（收 259 Kbps，重传 106） | 247 Mbps | 609 Mbps | 2.22 Gbps |
| iperf3 8/16 流 | **559 Kbps**（收 167 Kbps） | 209 Mbps | 440 Mbps | 19.4 Gbps |

结论：

- dynamips 的延迟/吞吐比其它三类节点低 **2-3 个数量级**，瓶颈在 **dynamips 的 MIPS 模拟 + idle-sleep**：每跳 ~35-40ms 与模板 `idlemax 500 / idlesleep 30`（空闲睡眠 30ms 片）量级一致；**relay 串口链每跳 ~49ms（对照实测），与 kernel 链同量级 → 慢在 dynamips 本体，不在 kernel datapath**
- dynamips 进程 CPU 仅 ~4.7%（idlepc 生效、机器 24 核负载 2.1），排除宿主机资源竞争
- filter 精度不受低吞吐影响（44.44%、13.9 帧、3.0s 窗等均分毫不差）

## 8. 坑清单（Dynamips 特有）

1. **console 回放**（§6.2-1）：自动化解析取最后一条 summary
2. c7200 串口需 DCE 端 `clock rate`（R2 侧），配置被取整（2000000→2016000）属正常
3. `device_config_send` 把命令包在 `configure terminal` 中，`write memory` 必须先发 `end`（登出配置模式）
4. 引导时间：6 台 c7200 冷启动 ~2-3 分钟（比 IOU 慢、比 QEMU 一次到位）；重启后 console 需等 IOS ready 再推送
5. 端口适配器（slot1=PA-2FE-TX 等）必须在节点 stopped 时改，`node_update` 属性合并语义正常
6. CDP/keepalive 帧常驻链路（pcap 可见），seed 复现实验建议静默链 + R1 关 CDP（本场已持久化）
7. `link_list` 的 fields 白名单**已包含** `kernel_datapath`（IOU 版记录的缺口在 c9692ff9a 后已修）

## 9. 复验、快照与 stop/start 专项（问题 7）

- 全部 filter 清除后基线复验：E2E 20/20 0% 丢、OSPF 12/12
- **R2 stop/start 专项（通过）**：R2 带 3 条 kernel 链（seg1/seg6/seg2）+ 1 条 relay 串口
  - **stop 后**：3 个锚点 TAP 全部存活、三条链的桥成员原样保留——**"stop is not close" 实测成立**（hypervisor 存活持有 TAP fd）
  - **start 后**：NVRAM 配置自恢复，R2 自身 3×FULL、R1 见双平行 2×FULL、R3 见 R2 FULL；E2E 0% 丢（RTT 204/257/334ms）
- 快照 `baseline-dynamips-kernel-datapath-clean` 于全停后创建，随后 `node_start_all` 恢复：全网 OSPF 回基线（R1 2×FULL）、E2E 20/20 0% 丢

---

*Built & verified 2026-10-01 via GNS3 MCP（链路/节点/设备操作全程走 MCP：device_config_send / device_show_run / link_update / link_capture_*；设备命令经本地 console TCP 直连采集，内核对象为只读观察）。数据面结论均为实测；服务端实现细节标注【转述】。*
