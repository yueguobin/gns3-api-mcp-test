# Kernel-DataPath-Docker-MixedNOS 方案与实施记录

全 docker 混合 NOS 6-hop 线形链实验场：Ubuntu A → 6 台路由器（SRLinux/FRR/XRd 交错）→ Ubuntu B。
- 项目：`Kernel-DataPath-Docker-MixedNOS`（b322be35-a0b0-4d3e-bac2-e0d5c028d9e3）
- 建成：2026-10-04，当日全验证
- 快照：`baseline-mixednos-6hop-clean`（aaecbb1b-dd7f-44ae-b9b6-4bb9f9bef08c）

## 1. 设计规则（用户授权自行决定）

| 决策点 | 选择 | 理由 |
|---|---|---|
| 拓扑 | 纯串行 P2P（不用 switch） | hop 计数干净，与 FRR-Chain/11 节点系列方法论一致 |
| hop 数 | 恰好 6：SRL×2 + FRR×2 + XRd×2 | 满足"≥6 hop 且覆盖三种类型"的最小完备集 |
| 类型排列 | SRL-FRR-XRd-SRL-FRR-XRd 交错 | 三种厂商对（SRL↔FRR / FRR↔XRd / XRd↔SRL）全部相邻过 |
| IGP | OSPFv2 单区 area 0，网络类型全默认 broadcast | 跨 NOS 互操作验证价值 > 静态路由；不调 p2p 避免跨厂商网络类型不一致卡 ExStart |
| 编址 | 10.5.xy.0/24（R_x–R_y 互联，x 取 .x）；主机网 10.5.100.0/24 / 10.5.200.0/24 | 10.5 未被占用；沿用 FRR-Chain 的 100/200 主机网段惯例 |

## 2. 拓扑与编址

```
Ubuntu-A ── SRL-1 ── FRR-1 ── XRd-1 ── SRL-2 ── FRR-2 ── XRd-2 ── Ubuntu-B
10.5.100.2  R1      R2      R3      R4      R5      R6    10.5.200.2
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

Router-ID：10.5.0.1 ~ 10.5.0.6。

## 3. 配置通道（每 NOS 一条）

| NOS | console | 配置方法 | 持久化 |
|---|---|---|---|
| SRLinux | docker_exec(sr_cli) | ws console 逐行 0.15s 推 sr_cli 块配置 | `commit save` → /etc/opt/srlinux/config.json |
| FRR | telnet(vtysh) | device_config_send（tag `device_type:cisco_ios_telnet`） | `write memory` → /etc/frr/frr.conf |
| XRd | docker_exec(xr_cli) | device_config_send（模板自带 netmiko cisco_xr_telnet + admin/cisco） | `commit` → /xr-storage |
| Ubuntu | telnet(bash) | ws console bash `ip addr/route` | ⚠️ 运行时，重启需重配 |

配置要点：
- FRR：`router ospf`（10.x 无 instance 模式）+ `network 10.5.0.0/16 area 0`
- SRL：接口 admin-state enable ×3 层 + NI 绑定 + ospf instance admin-state enable + `advertise-subnet true`
- XRd：接口 ipv4 address + no shutdown；`router ospf 1` → `area 0` → `interface` 挂接口；结尾 `commit`+`end`

## 4. 验证结果（全部实测，2026-10-04）

| 项目 | 结果 |
|---|---|
| 链路 kernel_datapath | **7/7 true**（SRL↔FRR、FRR↔XRd、XRd↔SRL 混合对全部 kernel 链——混合 NOS docker 对不影响判定） |
| OSPF 邻居 | **10/10 Full**（FRR-1 2 + FRR-2 2 + XRd-1 2 + XRd-2 1 + SRL-1 1 + SRL-2 2；XRd-2 对 B 侧无 OSPF 属预期） |
| E2E ping A→B | 10/10 收包 0% loss，**回包 ttl=58**（64−6，精确 6 hop 证据） |
| RTT | avg 3.13ms（min 1.99 / max 5.22 / mdev 0.89） |
| iperf3 单流 | **65.8 Mbits/s**（371 重传/5s） |
| iperf3 4 流聚合 | **66.0 Mbits/s**（多流不涨 = 路径固定瓶颈形态） |
| stop/start 全链 | OSPF 自动回满、E2E 复验 5/5 0% loss（三 NOS 配置持久化均存活） |

吞吐归因（**推断未实测**）：纯 FRR docker 链 11 跳 2.2Gbps，本链 66Mbps 差两个数量级，嫌疑最大是 XRd control-plane 镜像用户态慢速转发 ×2 跳内联。逐段归因待做（实验菜单 §7.2）。

## 5. 踩坑与要点

- **SRL↔FRR/XRd OSPF 邻接零调通**：曾担心 SRL 默认 jumbo MTU 导致 DBD MTU 不匹配卡 ExStart，实测未发生，三种 NOS broadcast 默认值直接互通。
- DR 选举正常：FRR 视角 XRd 常当选 DR（router-id 大）。
- Ubuntu（gns3/ubuntu:noble）自带 iperf3，无需安装。
- XRd 停机 40s（GNS3_STOP_TIMEOUT=40），stop_all → snapshot 要留时间。
- 主机运行时配置：恢复快照/重启后仅需 4 条命令重建（README §6）。

## 6. 与既有系列的关系

| 系列 | 载体 | 单流吞吐 | RTT/跳 |
|---|---|---|---|
| FRR-Chain 11 节点 | 全 FRRDocker | 2.2 Gbps | ~0.016ms/跳 |
| 本项目 6 节点 | SRL/FRR/XRd 混合 | 65.8 Mbps | ~0.52ms/跳 |
| QEMU 11 节点（e1000） | FRR-qemu | 342 Mbps | 0.60ms/跳（VM 穿越） |
| Dynamips 11 节点 | c7200 | 524 Kbps | ~45ms/跳 |

## 7. 实验菜单

1. 链路 filter：7 条 kernel 链应支持 13 种 filter（对照 Mixed-Kernel-DataPath 修正版语义）
2. 逐段吞吐归因：FRR-1/FRR-2 装 iperf3，切分 XRd 段与非 XRd 段
3. 断链演练：suspend 任一段，OSPF 收敛计时
4. 网络类型实验：SRL 改 point-to-point vs 邻居 broadcast 的 ExStart 行为
