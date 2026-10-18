# Kernel-DataPath-Docker-MixedNOS 方案与实施记录

全 docker 混合 NOS 6-hop 线形链实验场：Ubuntu A → 6 台路由器（SRLinux/FRR/XRd 交错）→ Ubuntu B。
- 项目：`Kernel-DataPath-Docker-MixedNOS`（b322be35-a0b0-4d3e-bac2-e0d5c028d9e3）
- 建成：2026-10-04，当日全验证 + 吞吐归因定案
- 快照：`baseline-mixednos-6hop-clean`（aaecbb1b，纯链 8 节点）/ `baseline-mixednos-6hop-with-probes`（ad69c9b6，含 6 probe 主机，现行基线）

## 1. 设计规则（用户授权自行决定）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 拓扑 | 纯串行 P2P（不用 switch） | hop 计数干净，与 FRR-Chain/11 节点系列方法论一致 |
| hop 数 | 恰好 6：SRL×2 + FRR×2 + XRd×2 | 满足"≥6 hop 且覆盖三种类型"的最小完备集 |
| 类型排列 | SRL-FRR-XRd-SRL-FRR-XRd 交错 | 三种厂商对（SRL↔FRR / FRR↔XRd / XRd↔SRL）全部相邻过 |
| IGP | OSPFv2 单区 area 0，网络类型全默认 broadcast | 跨 NOS 互操作验证价值 > 静态路由；不调 p2p 避免跨厂商网络类型不一致卡 ExStart |
| 编址 | 10.5.xy.0/24（R_x–R_y 互联，x 取 .x）；主机网 10.5.100/200 | 10.5 未被占用；沿用 FRR-Chain 的 100/200 主机网段惯例 |
| probe 主机 | 每路由器空闲口挂 1 台 Ubuntu（10.5.10N.0/24，N=路由器号） | 吞吐归因用（§5），SRL e1-3 / FRR eth2 / XRd Gi0/0/0/2 |

## 2. 拓扑与编址

```
Ubuntu-R1    Ubuntu-R2    Ubuntu-R3    Ubuntu-R4    Ubuntu-R5    Ubuntu-R6
10.5.101.2   10.5.102.2   10.5.103.2   10.5.104.2   10.5.105.2   10.5.106.2
     |            |            |            |            |            |
Ubuntu-A ── SRL-1 ── FRR-1 ── XRd-1 ── SRL-2 ── FRR-2 ── XRd-2 ── Ubuntu-B
10.5.100.2   R1       R2       R3       R4       R5       R6     10.5.200.2
```

| 链路 | 网段 | 地址分配 |
|---|---|---|
| Ubuntu-A ↔ SRL-1 e1-1 | 10.5.100.0/24 | A=.2 / SRL-1=.1 |
| SRL-1 e1-2 ↔ FRR-1 eth0 | 10.5.12.0/24 | SRL-1=.1 / FRR-1=.2 |
| FRR-1 eth1 ↔ XRd-1 Gi0/0/0/0 | 10.5.23.0/24 | FRR-1=.2 / XRd-1=.3 |
| XRd-1 Gi0/0/0/1 ↔ SRL-2 e1-1 | 10.5.34.0/24 | XRd-1=.3 / SRL-2=.4 |
| SRL-2 e1-2 ↔ FRR-2 eth0 | 10.5.45.0/24 | SRL-2=.4 / FRR-2=.5 |
| FRR-2 eth1 ↔ XRd-2 Gi0/0/0/0 | 10.5.56.0/24 | FRR-2=.5 / XRd-2=.6 |
| XRd-2 Gi0/0/0/1 ↔ Ubuntu-B | 10.5.200.0/24 | XRd-2=.1 / B=.2 |
| probe 链 ×6 | 10.5.101~106.0/24 | U-RN=.2 / RN=.1 |

Router-ID：10.5.0.1 ~ 10.5.0.6。probe 网段全部进 OSPF area 0。

## 3. 配置通道（每 NOS 一条）

| NOS | console | 配置方法 | 持久化 |
|---|---|---|---|
| SRLinux | docker_exec(sr_cli) | ws console 逐行 0.15s 推 sr_cli 块配置 | `commit save` → /etc/opt/srlinux/config.json |
| FRR | telnet(vtysh) | device_config_send（tag `device_type:cisco_ios_telnet`） | `write memory` → /etc/frr/frr.conf |
| XRd | docker_exec(xr_cli) | device_config_send（模板自带 netmiko cisco_xr_telnet，admin/cisco） | `commit` → /xr-storage |
| Ubuntu ×8 | telnet(bash) | ws console bash `ip addr/route` | ⚠️ 运行时，重启需重配（见 §7） |

配置要点：
- FRR：`router ospf`（10.x 无 instance 模式）+ `network 10.5.0.0/16 area 0`（probe 口自动覆盖）
- SRL：接口 admin-state enable ×3 层 + NI 绑定 + ospf instance admin-state enable + `advertise-subnet true`
- XRd：接口 ipv4 address + no shutdown；`router ospf 1` → `area 0` → `interface` 挂接口；结尾 `commit`+`end`

## 4. 验证结果（全部实测，2026-10-04）

| 项目 | 结果 |
|---|---|
| 链路 kernel_datapath | **13/13 true**（7 原链 + 6 probe 链；含 SRL↔FRR、FRR↔XRd、XRd↔SRL 混合对） |
| OSPF 邻居 | **10/10 Full**（5 路由器间链 ×2；probe 主机不跑 OSPF 属预期） |
| E2E ping A→B | 10/10 收包 0% loss，**回包 ttl=58**（64−6，精确 6 hop 证据） |
| RTT | avg 3.13ms（min 1.99 / max 5.22 / mdev 0.89） |
| iperf3 单流/4 流 | 65.8 / 66.0 Mbits/s（归因见 §5：瓶颈 SRL） |
| stop/start 全链 | OSPF 自动回满、E2E 复验通（三 NOS 配置持久化均存活） |

## 5. 吞吐归因（实测定案，probe 阶梯法）

用"每路由器挂 probe Ubuntu + 临时直连链"做的归因阶梯，全部串行实测：

| 测量 | 路径 | 吞吐 | RTT |
|---|---|---|---|
| L0 直连基线 | A(eth1) ↔ U-R1(eth1)，零路由器 | **12.7 Gbps** | 0.099ms |
| L1 纯 XRd | B — XRd-2 — U-R6 | **740 Mbps** | 0.84ms |
| L2 纯 SRL | A — SRL-1 — U-R1 | **62 Mbps** | ~0.4ms |
| 深度阶梯 M1~M6 | A→U-R1…A→U-R6（1~6 hop） | 61~81 Mbps 全平坦 | — |
| 全链 | A — S-F-X-S-F-X — B | 66 Mbps | 3.1ms |

**结论：瓶颈是 SRLinux 容器数据面**。一次 SRL 穿越 12.7G→62M（200 倍降幅）；全链 66M ≈ SRL 单跳 62M（min 模型，两个 SRL 卡同一水位）；XRd 740M / FRR（历史 2.2G）均不添堵。M1~M6 平坦是"SRL 一直在路径上"的必然。

机理（**解释非实测**）：SRL 容器版数据面不是 Linux 内核转发，是 `sr_linux` 主进程内用户态虚拟转发，62M@1500B ≈ 5.2kpps 每包处理极限。注意 SRL **延迟**反而不差（单穿 ~0.15ms < XRd ~0.37ms），塌的只是吞吐。

方法论教训（坑）：
- **ping 路由器接口地址测的是设备本地 ICMP 响应，不是转发路径**——首次阶梯尝试数值非单调（SRL-1 直连接口 1.8ms vs 过 SRL 到 FRR-1 0.4ms），不可用于归因；probe 主机过路流量才是纯转发测量。
- 归因阶梯各测量**必须串行**（共享路径设备，并行互相污染）。
- 多流不涨（66M）+ 平坦阶梯 = 固定每包瓶颈形态，与拥塞/窗口限制（多流会涨）区分。

## 6. 与既有系列的关系

| 系列 | 载体 | 单流吞吐 | RTT/跳 |
|---|---|---|---|
| FRR-Chain 11 节点 | 全 FRRDocker | 2.2 Gbps | ~0.016ms/跳 |
| 本项目（纯 XRd 段） | XRd control-plane | 740 Mbps | ~0.37ms/单穿 |
| 本项目（纯 SRL 段） | SRLinux 容器 | 62 Mbps | ~0.15ms/单穿 |
| 本项目 6 hop 全链 | 混合（SRL 瓶颈） | 66 Mbps | ~0.52ms/跳 |
| QEMU 11 节点（e1000→virtio） | FRR-qemu | 342M → 1.73G | 0.60ms/跳（VM 穿越） |
| Dynamips 11 节点 | c7200 | 524 Kbps | ~45ms/跳 |

## 7. 快照恢复后的最小重建步骤

路由器三 NOS 配置均持久化，恢复后只需重配 8 台主机（IP+gw+iperf server）：

```bash
# Ubuntu-A: ip addr add 10.5.100.2/24 dev eth0; ip route add default via 10.5.100.1
# Ubuntu-B: ip addr add 10.5.200.2/24 dev eth0; ip route add default via 10.5.200.1
# Ubuntu-RN (N=1..6): ip addr add 10.5.10N.2/24 dev eth0; ip route add default via 10.5.10N.1
# 各主机 iperf3 server: iperf3 -s -D
```

## 8. 实验菜单

1. 链路 filter：13 条 kernel 链应支持 13 种 filter（对照 Mixed-Kernel-DataPath 修正版语义）
2. SRL 吞吐调优：SRL 流量处理参数（如 vhost/多核）能否突破 62M
3. 断链演练：suspend 任一段，OSPF 收敛计时
4. 网络类型实验：SRL 改 point-to-point vs 邻居 broadcast 的 ExStart 行为
5. probe 主机反向矩阵：U-RN 互测全排列（当前只测了 A 起深阶梯 + B 起单段）
