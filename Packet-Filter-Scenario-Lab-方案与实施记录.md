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

## 6. 后续实验菜单

| # | filter | 实验 | 状态 |
|---|---|---|---|
| E3 | packet_loss correl | 突发 vs 独立丢包（同均值） | 待做 |
| E4/E5 | delay / rate+delay | RTT 缩放（已随 E2 完成）/ BDP 墙 | 半成 |
| E6 | limit | bufferbloat vs 小队列（delay-only 207M 天花板已到手） | 待做 |
| E7/E8 | reorder / seed | 乱序伪重传 / 逐次复现 | 待做 |
| E9 | frequency_drop | 确定性 vs 随机（0.66× 初值已到手，待大窗口复验） | 半成 |
| E10 | duplicate+corrupt | 等效丢包 | 待做 |
| E11 | window_drop 四参 | 周期断网自愈 | 待做 |
| E12 | bpf proto 89 | 只杀 OSPF→亚秒切备路 | 待做 |
| E13 | bpf icmp | ping 不通业务通 | 待做 |
| E14 | gemodel vs packet_loss | 同均值邻居容错 | 待做 |
| E15 | window_drop 长窗口 | 路由翻动 | 待做 |
