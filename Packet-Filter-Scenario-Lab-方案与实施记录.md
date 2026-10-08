# Packet-Filter-Scenario-Lab 方案与实施记录

> 项目：`Packet-Filter-Scenario-Lab`（project_id `27b64527-a53a-4847-ba9c-4baaf0269e4f`）
> 定位：用典型实验场景衬托 kernel-datapath 链路 packet filter（13 种损伤原语）的价值——filter 是"环境变量"，不动拓扑、不插中间节点，改参数即换网络环境。
> 证据标注：本文区分【实测】【理论】【推断】；未标注即【实测】。

## 1. 设计（2026-10-07 与用户确认）

### 1.1 场景选题

- **场景 1：TCP × 损伤矩阵**——丢包/时延/限速/队列等损伤下测 TCP 吞吐，与理论公式对照
- **场景 2：控制面 × 数据面分离**——bpf 选择性杀协议、gemodel 突发丢包、window_drop 定时故障
- BGP（bpf 杀 tcp/179、hold timer）留二期

### 1.2 拓扑（6 节点菱形，全 docker）

```
host1 ────── R1 ══(cost 10)══ R2 ══(cost 10)══ R4 ────── host2
 10.10.0/24   ║                                 10.10.1/24
              ╚═══(cost 50)═══ R3 ══(cost 50)═══╝
```

- 节点：R1–R4 = FRRDocker（带 `device_type:cisco_ios_telnet` tag），host1/host2 = Ubuntu Docker Guest
- 主路 R1→R2→R4（cost 20），备路 R1→R3→R4（cost 100）；**损伤只打主路链 R1—R2**
- 路径策略默认主备（单流确定性），按实验可改 ECMP；OSPF hello/dead 默认 10/40s

### 1.3 编址

| 节点 | 接口 | 地址 |
|---|---|---|
| host1 | eth0 | 10.10.0.100/24，gw 10.10.0.1 |
| host2 | eth0 | 10.10.1.100/24，gw 10.10.1.1 |
| R1 | lo / eth0(host1) / eth1(R2) / eth2(R3) | 1.1.1.1/32 / 10.10.0.1 / 10.0.12.1 / 10.0.13.1 |
| R2 | lo / eth1(R1) / eth2(R4) | 2.2.2.2/32 / 10.0.12.2 / 10.0.24.1 |
| R3 | lo / eth1(R1) / eth2(R4) | 3.3.3.3/32 / 10.0.13.2 / 10.0.34.1 |
| R4 | lo / eth0(host2) / eth1(R2) / eth2(R3) | 4.4.4.4/32 / 10.10.1.1 / 10.0.24.2 / 10.0.34.2 |

OSPF 单区 0：WAN 口 `ip ospf network point-to-point` + 显式 cost，接入口 passive。

## 2. 建设与验收（2026-10-07）

| 验收项 | 结果 |
|---|---|
| kernel_datapath | 6/6 链 true（13 种 filter 前提） |
| OSPF | 4/4 Full 一次成；traceroute 确认走主路 R1→R2→R4 |
| E2E | host1↔host2 0% loss，RTT 0.22ms，ttl=61 |
| iperf3 基线 | 单流 6.23 Gbit/s、0 重传 |
| 快照 | `baseline-filter-scenario-clean`（fff2dc6f） |
| 重启复验 | OSPF/host 配置全持久化；唯一运维点=host2 重启后重拉 iperf3 server |

画布带两块文字板（编址总览 + 实验步骤），格式为单 `<text>` + 字面换行符（一个 drawing = 一个 svg + 一个图形元素）。

## 3. E2 实验：丢包-吞吐曲线（2026-10-08 执行）

**背景**：服务器重启后执行（重启清空运行态 filter，正好从零基线开始；OSPF/主机配置自动恢复，iperf3 server 手动重拉）。

**方法**：损伤打 R1—R2 主路链；每档 `ping -c 5` 测 RTT + `iperf3 -t 10` 单流（host1→host2）。发送端拥塞控制 CUBIC（实测 sysctl），MSS 1448。先用 时延 delay 25ms 把 RTT 从 0.1ms 抬到 50ms——【推断→已验证】原生 RTT 下 Mathis 预测远超平台 6.2G 天花板，曲线拉不开。

**数据**（吞吐为 iperf3 sender/receiver）：

| 档位 | RTT avg | 吞吐 sender | 吞吐 receiver | Retr | ping 丢包 | Reno 理论【理论】 |
|---|---|---|---|---|---|---|
| R0 基线（无损伤） | 0.107ms | 6.26G | 6.26G | 514 | 0% | — |
| R1 delay 25 | 50.336ms | 207M | 204M | 1979 | 0% | — |
| R2 delay25+丢包1% | 50.415ms | 5.03M | 4.07M | 25 | 0% | 2.81M |
| R3 delay25+丢包2% | 50.424ms | 1.78M | 1.67M | 34 | 0% | 1.99M |
| R4 delay25+丢包5% | 50.427ms | 1.05M | 1.04M | 41 | 0% | 1.26M |
| R5 delay25+丢包10% | 50.329ms | 629K | 522K | 49 | **20%** | 0.89M |
| R6 delay100+丢包1% | 200.315ms | 1.15M | 822K | 10 | 0% | 0.71M |
| R7 delay25+freq_drop N=100 | 50.402ms | 3.35M | 2.92M | 25 | 0% | （确定性模型另议） |
| R8 清空恢复 | 0.133ms | 6.21G | 6.21G | 64 | 0% | — |

Reno 理论线：T = 1.22·MSS·8/(RTT·√p)，MSS=1448，RTT 取各档实测值。

## 4. 发现与结论

1. **时延精确性**：delay 25 → RTT 50.336ms、delay 100 → RTT 200.315ms，直连 docker 链 2× 语义分毫不差（与 09-30 filter 专项一致）。
2. **T∝1/RTT 得证**：同为 1% 丢包，RTT 50→200ms 吞吐 5.03M→1.15M，比值 4.37× ≈ 理想 4×（精确 RTT 比 3.97）。
3. **CUBIC 相对 Reno 线的位置随丢包率反转**：1% 时在线上 1.80×，2%/5%/10% 落到线下 0.90/0.84/0.71×。【推断】高丢包+10 秒短流下 RTO 停摆主导（R5 尾部出现整秒 0 吞吐），Mathis 的稳态假设失效；200ms 档（R6）1.63× 又回到线上方。
4. **衰减斜率比理论陡**：sender 侧 1%→2%→5%→10% 逐级比值 2.82/1.70/1.67×，均陡于 Reno 的 √ 档（1.41/1.58/1.41×）。【推断】同上，RTO 机制在低吞吐区形成地板效应。
5. **双向丢包公式再验证**：10% 档 ping 路径丢包实测 20% vs 理论 1−(0.9)²=19%（5 样本）。
6. **delay-only 天花板**：仅 delay 25 时吞吐 207M（Retr 1979）——netem 损伤队列默认 1000 包，BDP 超限即溢出丢包。这是 E6（limit/bufferbloat）实验的直接素材。
7. **丢包参数只收整数（重要）**：`packet_loss` Chance 为 int（0–100）；传 0.1 会被服务端**静默丢弃**（filter 不生效、无报错）。亚 1% 随机丢包不可直接表达；确定性亚 1% 可用 frequency_drop（每 N 包丢 1）。
8. **确定性 vs 随机丢包（E9 预演）**：同为均值 1%，frequency_drop N=100（确定性）吞吐 3.35M < packet_loss 1%（随机）5.03M，比值 0.66×。【推断】理想化"确定性远优于随机"结论要求 cwnd≫N，本场景平均 cwnd ≈15 包 ≪100，不在该区间；理想结论待大窗口/长流实验再验。
9. **控制面韧性**：全部损伤档位期间（含 10% 丢包）OSPF 邻居持续 Full（Up Time 贯穿 12 分钟实验窗口）——hello 10s/dead 40s 对 10% 独立丢包不敏感。
10. **服务器重启行为**：filter 是运行态、重启即清空（回到无损伤基线）；FRR（frr.conf）/主机（/etc/network/interfaces）配置持久。

## 5. 运维要点

- 节点/服务器重启后 host2 重拉 iperf3 server：`nohup iperf3 -s >/dev/null 2>&1 &`
- host 持久化走 /etc/network/interfaces（busybox ifup，address/netmask 分列，改文件用 base64 经 ws console）
- 服务器重启后 MCP 需 /mcp 重连；ws URL 以 node_console 返回值为准（重启后地址可能变）
- Ubuntu docker console 禁发 \x03、禁 exit；websocat timeout 贴输入时长；token 单次有效
- 画布文字板：一个 drawing = 一个 svg + 一个图形元素，多行 = text 内字面换行符

## 6. 第二批实验：E5/E6/E7/E8/E10/E11（2026-10-08 续跑）

### 6.1 E5/E6：限速 rate × 队列 limit × 时延 delay（bufferbloat 三元组）

负载下 RTT 由后台 ping（`ping -c 30 -i 0.3` 与 iperf3 并行）测得：

| 组合 | 吞吐(sender) | 负载 RTT avg/max | ping 丢包 | Retr |
|---|---|---|---|---|
| rate 100M（队列默认 1000 包） | 98.2M | 89.9 / 120.7ms | 0% | 55 |
| rate 100M + delay 25（深队列） | 95.9M | 115.4 / 145.8ms | 0% | 68 |
| rate 100M + delay 25 + limit 50（浅队列） | 10.6M | 50.2 / 50.7ms | 6.7% | 139 |
| delay 25 only（对照，无 rate） | 197M | 50.4 / 52.8ms | 0% | 1995 |
| delay 25 + limit 100（无 rate） | 21.0M | 50.4ms | 0% | 249 |
| delay 25 + limit 10（无 rate） | 2.10M | 50.4ms | 33.3% | 49 |

结论：
- **bufferbloat 完整形态**：同样限速 100M，深队列=满吞吐但 RTT 膨胀 2.3×（空载 0.12ms→满载 115ms）；浅队列=RTT 贴住 50ms 底但吞吐塌到 10.6M——50 包（75KB）队列装不下 100M×50ms=625KB 的 BDP，loss-based 拥塞控制填不满管道。教科书级权衡曲线。
- **netem 的 delay 是"每包定时器"不是串行化瓶颈**：仅 delay 无 rate 时队列再深也不叠 RTT（50.4ms 平），吞吐天花板 ~200M 来自 TCP 突发撞 limit 溢出（Retr ~2000 而 ping 0% 丢）。**要有 RTT 膨胀必须配 rate**。

### 6.2 E7：乱序 reorder（配 delay 25）

| 档 | 吞吐(sender) | Retr |
|---|---|---|
| reorder 1% | 14.7M | 314 |
| reorder 5% | 46.2M | 4007 |

- 1% 乱序即把吞吐打到 delay-only 的 7%；Retr（314）远超同档真丢包（25）——伪快速重传。
- 5% 反而比 1% 高（46M vs 14.7M）。【推断】持续高乱序促使内核快速抬升 dupthresh 容忍度，伪重传被 DSACK 撤销砍窗；4007 次重传约 8% 带宽开销。

### 6.3 E8：seed 复现（delay25+loss1%+seed 12345，换值再换回重武装）

| 轮 | 逐秒序列(Mbit/s) | 总吞吐 | Retr |
|---|---|---|---|
| A | 12.6/2.1/2.1/4.2/4.2/2.1/2.1/2.1/2.1/3.1 | 3.67M | 25 |
| B | 14.7/2.1/3.2/5.2/2.1/0.0/3.2/2.1/3.2/5.2 | 4.09M | 27 |

**两轮不一致——seed 对自由运行的 TCP 不构成复现**。【推断】seed 固定的是 PRNG 序列（按包序消费），TCP 每轮发包节奏漂移导致丢包落点漂移；可复现性只对固定节奏的探测流成立。修正"seed=实验可复现"的朴素预期。

### 6.4 E10：重复 duplicate / 损坏 corrupt（配 delay 25）

| 档 | 吞吐(sender) | Retr | 对照 |
|---|---|---|---|
| duplicate 1% | 190M | 1888 | ≈delay-only 207M，可忽略 |
| corrupt 1% | 4.61M | 28 | ≈packet_loss 1% 的 5.03M/25 |

- **corrupt=等效丢包**：校验和坏包被 TCP 按丢包重传，吞吐/Retr 与同档 packet_loss 几乎重合。
- duplicate 1% 在 G 速率下被队列噪声掩盖，影响可忽略。

### 6.5 E11：周期断网 window_drop（delay25 + [start 3s, outage 2s, chance 100, period 10s]）

30 秒长 ping：60 发 48 收，**丢包 20.0% = 占空比 2s/10s 精确命中**；窗口外 RTT 稳定 50.4ms——周期黑洞+自愈形态成立（双向同时断，等效链路闪断）。

## 7. 更正与确认（操作侧）

1. **link_update 的 kwargs 必须用 `{"filters": {...}}` 包裹**：裸 filter 字典在部分场景静默失败（整包忽略或部分应用，无任何报错）。本批曾据此误判"rate 与 limit 互斥""seed 不可下达"，经正确格式复验**全部作废**——三 filter 共存（delay+rate+limit）与 seed 下达均正常。教训已记 memory。
2. **correl bug 确认保留**（与格式无关）：packet_loss 带 correl 参数时（如 [1,25]）配置被接受、echo 正确，但数据面不丢包（200 包 ping 0 丢失，该事件概率≈1.8%），吞吐回到无丢包天花板。**E3（突发 vs 独立丢包）被此 bug 挡住，待服务端修复后补测**。
3. packet_loss chance 只收整数（0.1 静默丢弃）——E2 已记录，维持。
4. OSPF 邻接在本批全部损伤（含 33% 队列丢包、5% 乱序、20% 周期断网）下持续 Full 累计 1h01m 未断。

## 8. 实验菜单状态

| # | filter | 实验 | 状态 |
|---|---|---|---|
| E1/E2 | 基线/丢包曲线 | §3 | ✅ |
| E3 | packet_loss correl | 突发 vs 独立 | ⛔ 服务端 bug（§7.2） |
| E4/E5 | delay/rate+delay | RTT 缩放/BDP 墙 | ✅（§3/§6.1） |
| E6 | limit | bufferbloat vs 小队列 | ✅（§6.1） |
| E7 | reorder | 乱序伪重传 | ✅（§6.2） |
| E8 | seed | 复现性边界 | ✅（§6.3，结论=对自由 TCP 不可复现） |
| E9 | frequency_drop | 确定性 vs 随机 | 半成（§3 R7：0.66×，待大窗口复验） |
| E10 | duplicate/corrupt | 等效丢包 | ✅（§6.4） |
| E11 | window_drop 四参 | 周期断网 | ✅（§6.5） |
| E12 | bpf proto 89 | 只杀 OSPF→切备路 | 待做（场景 2） |
| E13 | bpf icmp | ping 假象 | 待做（场景 2） |
| E14 | gemodel vs packet_loss | 同均值邻居容错 | 待做（场景 2） |
| E15 | window_drop 长窗口 | 路由翻动 | 待做（场景 2） |
