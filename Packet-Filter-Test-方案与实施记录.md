# Packet Filter Test — 方案与实施记录（2026-09-30）

在 11 节点 FRR 链上对 GNS3 link packet filter 全部 **13 种类型**做逐个数据面实测：为后续"多跳延迟"实验标定 filter 行为与换算关系；并在当晚服务端修复后复验 window_drop / gemodel / kernel_datapath 三处。

- GNS3 项目：`Docker-Kernel-DataPath-test-FRRDocker`（project_id `d1ab2349-2e53-4e41-a9ae-b5ffcd912408`；09-30 由 `docker-dataplane-test` 改名）
- 平台/版本：11× FRRDocker（`gns3/frr:latest` 镜像，`show version` = **FRR 10.3**，console 主进程 = vtysh）；GNS3 server `3.1.0.dev7+2445e2e5e`
- 测试链路：**FRRDocker-1 eth5 ↔ FRRDocker-2 eth5**（`10.1.1.0/30`，link_id `ba72b22e-cf2c-46de-a292-3c15d2551036`，`kernel_datapath: true`）——10 条链路中择一（平行双链路之一），干扰面最小
- 结论一句话：**13 种 filter 全部可用、数据面行为与文档一致**（换算公式见 §4）；三处服务端修复均经实测复验生效（§5）。

## 1. 环境与方法

### 1.1 拓扑与被测链路

```
FRRDocker-1 ══eth5══ FRRDocker-2 ── FRRDocker-3 ── ... ── FRRDocker-11     (11 节点线形链)
             ══eth6══
             （eth5/eth6 平行双链路；本次只扰 eth5，eth6 全程无影响）
```

- 链上运行 OSPF 单区（`network 10.1.0.0/16 area 0`）；被测链路同时在跑 OSPF hello —— 对本测试有两个影响：推进 frequency_drop 的每-N 计数器（相位漂移）、高丢包时可能打断邻接（自愈，见 §6）
- ping 目标取**对端接口地址 `10.1.1.2`**（与源同 /30）：路径必然走被测链路，100% 锁定，不经过其它节点

### 1.2 流量采样方法

- 采样工具：本地 console TCP 直连（`127.0.0.1:5000` 进 node1 vtysh）+ 采样脚本（附录 A）；脚本按**到达顺序**逐行打印每包（乱序、DUP! 可直接判读），结束发 `\x03` 终止 ping
- 不用 MCP device 工具做流量采样的原因：vtysh `ping` 不会自动停止（挂死工具会话），且**不支持 `-c/-i` 参数**（实测 `% Unknown command`）—— 只能 1 pps 长采样
- 判读：丢包 = 未出现的 icmp_seq；DUP! 单列；RTT 直读

### 1.3 基线（无 filter）

```
8 packets transmitted, 8 received, 0% packet loss
rtt min/avg/max/mdev = 0.074/0.099/0.119/0.017 ms
```

测试全程多次复测基线均为 0% 丢、avg 0.07–0.10 ms。

## 2. 逐个 filter 实测结果（13 种，全部【实测】）

| # | 类型 | 参数 | 预期（按下方换算模型） | 实测 | 判定 |
|---|---|---|---|---|---|
| 1 | packet_loss | `[30]` | 双向 1−0.7²≈51% | **56%±7%**（n=50 合并） | ✅ |
| 2 | frequency_drop | `[3]` | 1−(2/3)²≈56% | **61.9%**（n=21，成段丢） | ✅ |
| 3 | gemodel | `[100,10,10]` | 单向 9.09% → 往返 17.4%（新语义） | 23.8%（n=21） | ✅ 噪声内 |
| 4 | corrupt | `[30]` | ≈51%（坏包被校验和丢） | **53.3%**（n=15） | ✅ |
| 5 | delay | `[50]` | RTT=100.0 | **100.18**（mdev 0.095） | ✅ |
| 6 | delay+jitter | `[50,20,"normal"]` | mdev≈√2×20=28.3 | **27.2** | ✅ |
| 7 | reorder | `[50,25,5]`+delay | 单腿重排 ≈19% | **18.75%**，RTT 双峰 50/100 ms | ✅ |
| 8 | rate | `["64kbit"]` | 2×98B×8/64k≈24.7 ms | **24.68** | ✅ |
| 9 | rate | `["256kbit"]` | ≈6.2 ms | **6.24** | ✅ |
| 10 | bpf | `icmp[icmptype]==8` | echo request 100% 丢 | **100% 丢，OSPF 邻接不动** | ✅ 选择性 |
| 11 | quota | `[2000,100]` | 断崖 | **前 15 通 → 全丢** | ✅ |
| 12 | window_drop | `[5000,3000,100,10000]` | 每周期断 3s | **丢 6-8 / 15-17 / 25-27** | ✅ |
| 13 | duplicate | `[50]` | DUP! | **15 收 +11 DUP**（最多 3 份） | ✅ |
| — | seed / limit | `[12345]` / `[1000]` | — | 组合态接受且不干扰（delay+loss 同链同时生效） | ✅ |

关键原始输出摘录：

```
# 5. delay 50ms —— 教科书 RTT
9 packets transmitted, 9 received, 0% packet loss
rtt min/avg/max/mdev = 100.100/100.179/100.393/0.095 ms

# 6. delay 50 + jitter 20 normal —— 抖动 ±√2×20
rtt min/avg/max/mdev = 38.705/95.282/132.296/27.167 ms

# 7. reorder [50,25,5] —— 零 seq 倒置但 RTT 双峰（被选包跳过延迟队列）
seq=1 100ms seq=2 100ms ... seq=8 50.1ms ... seq=10 50.2ms ... seq=13 50.1ms ...
rtt min/avg/max/mdev = 50.082/90.849/100.370/19.556 ms   (3/16 落在 50ms 档)

# 8. rate 64kbit —— 按二层帧长逐包序列化（84B IP + 14B Eth = 98B）
11 packets transmitted, 11 received, 0% packet loss
rtt min/avg/max/mdev = 24.576/24.678/24.886/0.112 ms    (98×8/64000×2 ≈ 24.5ms)

# 12. window_drop 周期形态 —— 每周期 3s = 3 个包，分毫不差
收到 seq: 1-5, 9-14, 18-24, 28-32    （空洞 6-8 / 15-17 / 25-27，周期 10s）

# 13. duplicate 50% —— 收 + DUP!
15 packets transmitted, 15 received, +11 duplicates, 0% packet loss
（icmp_seq=12 收到 3 份）
```

## 3. 丢包类的一条总规律

**filter 在链路双向各生效一次**（两个方向独立裁决）。所以用 ping（往返）测丢包时：

```
RTT 有效丢包 = 1 − (1 − p)²
```

验证：packet_loss 30% → 实测 56%（单向模型仅 30%，4σ 排除）；corrupt 30% → 53%。设置参数时按此倒推单向值。

## 4. 换算公式小结（后续实验直接用）

| 类别 | 公式 | 备注 |
|---|---|---|
| 丢包类（loss/corrupt/frequency/gemodel/quota/window/bpf） | RTT 丢包 = 1−(1−L)² | L = 单向失效率 |
| delay | RTT = 2×delay | 实测精确到 0.1ms |
| delay+jitter | mdev ≈ √2 × jitter | 双向各摊一次抖动 |
| rate | RTT ≈ 2×(帧字节数×8 / rate) | 帧 = IP 包长 + 14B 以太头（84B ping → 98B） |
| gemodel | 单向 L = p/(p+r)×(1−h) | 新语义：p=good→bad、r=bad→good、1−h=bad 态丢包率 |
| frequency_drop | 单向 L ≈ 1/N（近似） | 链路上其它流量（如 OSPF hello）推进计数器、相位漂移，非死板 mod-N |

## 5. 服务端修复复核（09-30 晚）

> 本节严格区分证据来源：【实测】= 本次在活实例上直接取得原始输出；【转述】= 开发侧提供的证据；【推断】= 我的推测。

1. **kernel_datapath 字段**【实测】：此前 `schemas/controller/links.py` 的 LinkBase 漏字段、response_model 静默剥掉 asdict 值；本次 `link_get` 已返回 `kernel_datapath: true`。
2. **gemodel 文档与参数名**【实测】：`link_available_filters` 的 gemodel 描述已更新为新语义（"p=good→bad、r=bad→good、1−h=bad 态丢包（good 态不丢），稳态均值 p/(p+r)×(1−h)"），参数名同步为 `p (good-to-bad)` / `r (bad-to-good)` / `1-h (bad-state loss)`。旧措辞（p=bad 态丢包、r=good 态丢包、1−h=good→bad）四处全反。
3. **gemodel 往返口径复核**【实测】：新语义下两点采样 —— `[100,10,10]` 预测往返 17.4%、实测 23.8%（n=21）；`[10,30,100]` 预测 43.75%、实测 51.6%（n=64）。均略高于预测 1–2σ，判定为突发态小样本方差**【推断】**（坏态以包为单位住留，样本效率低；建议精确校准用"逐向 offered = sent + dropped"计数而非往返 ping）。
4. **window_drop 三参"单次中断"形态**【实测】：此前本项两次"无效果"疑似服务端问题，本次以新值 `[8000,6000,100]` 复测正常 —— 6000ms 窗口 = **精确 6 连丢**（seq 4-9），窗口前后流量正常；该形态**工作正常**。早期两次失败的成因判定为**观测时序错过**【推断】：window start 从 filter 生效时刻起算，而 MCP 调用延迟（反推可达 ~5s）使 ping 起跑晚于窗口 —— 单次窗口"过时不候"。
5. **同值重设短路**【转述 · 开发侧】：controller 层同值 filters PUT 被 `new_filters != self.filters`（link.py:341）短路吞掉 —— 单次窗口的"重设即重来"失效；修复加 `or "window_drop" in new_filters` 强制 reconcile。该机制由开发侧代码路径 + 隔离实例日志（t4 重设后 ubridge 零命令）确认；**我无法在已修复实例上重放"未修"行为**【说明】。
6. **同值重设修复效果**【实测】：修复后在我的实例上同值 PUT 再次武装成功 —— 第二个窗口精确出现（seq 5-10，同样 6 连丢）；若短路仍在，该 PUT 会被静默吞掉、应表现为 0 丢包。

## 6. 坑与注意事项（方法学）

1. **高丢包下的 ARP 黑障**：重丢使邻居条目过期，而 ARP 请求自身也挨同一个 filter 的刀 → ping 报 `Destination Host Unreachable`（**本机 10.1.1.1 生成，非传输丢包**）。做丢包率统计时这类 error 要剔除，否则虚高（本次 n=64 的样本被污染 6 个包）。
2. **高丢包会打断被测链路的 OSPF 邻接**（4 连丢 hello 触发 dead timer，~40s 自愈）。平行双链路拓扑下不影响转发，但邻接 Up Time 会重置，判读"邻接异常"时先查测试历史。
3. **window_drop 是"过时不候"的一次性事件**：start 从 filter 生效时刻起算；如观测方（MCP 调用链）延迟大，窗口会被整段错过 —— 测试设计留余量（start ≥5–8s、对观测延迟做容差），或改用四参周期形态。同值重设现已可直接"重来"（§5.6 修复后）。
4. **vtysh ping 限制**：无 `-c/-i` 参数、不自动停止、ws 断开后容器侧仍在跑（须 `\x03`）；长采样走本地 console TCP（§1.2）。
5. **rate 的反推要用二层帧长**：netem 按出队帧（含 14B 以太头）序列化，用 IP 长度算会系统性偏低约 14%。
6. **gemodel 突发态样本效率低**：小样本 ping 测率的置信区间很宽，精确标定用逐向计数（见 §5.3）。
7. **多 filter 可叠加**：`delay + packet_loss + seed + limit` 同链同时生效互不干扰；`seed` 使 loss/duplicate/jitter 的随机抽样可复现，做对照实验建议固定 seed。
8. **平台姿势**：docker 节点需 `device_type:cisco_ios_telnet` tag 才能走 MCP device 工具（镜像 console 主进程是 vtysh，提示符兼容 cisco_ios_netmiko）；`link_available_filters` 是某个 filter 在**当前链路**上是否可用的权威答案（kernel 类型仅出现在 kernel-datapath 链路）。

## 7. 实验菜单（重放步骤）

前置：项目 `Docker-Kernel-DataPath-test-FRRDocker` 打开、`node_start_all`、等 ~30s OSPF 收敛（22/22 Full）。

```
# 0) 确认链路与基线
link_get(ba72b22e-...)                    # kernel_datapath: true, filters: {}
console(node1): ping 10.1.1.2             # 0% 丢，~0.1ms

# 1) 任选一 filter 下发（改 filters 字典 = 整组替换）
link_update(ba72b22e-..., filters={"delay": [50]})           # 或 packet_loss/corrupt/... 见 §2 表
console(node1): ping 10.1.1.2   （采样 ≥20s，Ctrl+C 收尾）

# 2) 叠加/改参数（同一次 link_update 全量传 filters 字典）
link_update(..., filters={"delay": [50], "packet_loss": [30], "seed": [12345]})

# 3) window_drop 单次窗口（注意观测余量）与周期形态
link_update(..., filters={"window_drop": [8000, 6000, 100]})      # 单次：8s 后断 6s
link_update(..., filters={"window_drop": [5000, 3000, 100, 10000]})  # 周期：每 10s 断 3s

# 4) 收尾
link_update(..., filters={})              # 清空
console(node1): ping 10.1.1.2             # 复核基线
```

## 8. 重建 checklist

1. 前置：`Docker-Kernel-DataPath-test-FRRDocker` 的 11 节点链就绪、OSPF 单区收敛（22/22 Full，编址见该链的搭建记录）——本测试**不新建任何节点/链路**；
2. 节点打 `device_type:cisco_ios_telnet` tag（device 工具可用）；
3. `link_available_filters(ba72b22e-...)` 确认 13 种齐全（缺 kernel 类型 = 该链路非 kernel-datapath，结论会不同）；
4. 按 §7 菜单逐项；`filters={}` 收尾后复测基线。

## 附录 A：采样脚本（pingtest.py）

```python
#!/usr/bin/env python3
"""Ping sampler via GNS3 docker console (raw TCP).
Usage: pingtest.py <console_port> <target> [duration_s]"""
import socket, sys, time, re

port = int(sys.argv[1]); target = sys.argv[2]
duration = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
s = socket.create_connection(('127.0.0.1', port), timeout=5)
s.settimeout(0.5); buf = b''

def drain(t):
    global buf
    end = time.time() + t
    while time.time() < end:
        try:
            d = s.recv(4096)
            if not d: break
            buf += d
        except socket.timeout: continue

time.sleep(1); drain(1)                      # settle
s.sendall(f'ping {target}\r\n'.encode()); t0 = time.time()
while time.time() - t0 < duration: drain(0.5)
s.sendall(b'\x03')                           # stop ping
time.sleep(1.5); drain(1.5); s.close()

clean = re.sub(r'\xff[\xfb\xfd\xfe].?', '', buf.decode('utf-8', 'replace'))
clean = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z=]', '', clean)
for line in clean.splitlines():
    l = line.strip()
    if l and ('bytes from' in l or 'icmp_seq' in l or 'DUP' in l
              or 'transmitted' in l or 'rtt' in l or 'packet loss' in l):
        print(l)
```

---
*Built & verified 2026-09-30 via GNS3 MCP（filter 控制与设备操作全程走 MCP；流量采样经本地 console TCP，见 §1.2）。*
