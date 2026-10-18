# Jumbo-Frame-Qemu-FRR-Test 方案与实施记录

- 日期:2026-10-10(单日建成 + 全实验矩阵闭环)
- 项目:`Qemu-FRR-JumboFrame`(id `8f80b06b-bd89-4941-ae52-216dac4db789`)
- 服务器:`3.1.0.dev7+23f117de5`
- 快照:`baseline-jumbo-9000`(a28e190b,全链 MTU 9000 持久化、OSPF Full、停机态)
- 使命:QEMU FRR 链路巨型帧端到端行为——MTU 阶梯通过性、PMTUD、OSPF×MTU、分片重组、吞吐收益

## 1. 拓扑与编址

```
H1(UDG) ──10.9.1.0/24── R1(FRR-qemu/virtio) ──10.9.12.0/31── R2(FRR-qemu/virtio) ──10.9.2.0/24── H2(UDG)
   └──────────────────────── 10.9.99.0/31 直连对照链(排除 FRR 转发因素) ────────────────────────┘
```

| 节点 | 模板 | node_id | 角色 |
|---|---|---|---|
| FRR-qemu-1(R1) | FRR-qemu(frr-8.2.2.qcow2)eth0/eth1 改 **virtio-net-pci** | 87f910bc | 路由器,OSPF area 0,router-id 1.1.1.1 |
| FRR-qemu-2(R2) | 同上 | 8f4eabfe | 路由器,router-id 2.2.2.2 |
| UbuntuDockerGuest-1(H1) | gns3/ubuntu:noble | 993e659a | 流量端,10.9.1.1 / 10.9.99.0 |
| UbuntuDockerGuest-2(H2) | 同上 | 5d722a0f | 流量端,10.9.2.1 / 10.9.99.1,iperf3 server 自启 |

- H1/H2 默认路由指向各自网关;R1/R2 OSPF 单区宣告三个网段
- **4/4 链全部 kernel_datapath=true**,含 UDG↔qemu 混合链(veth↔tap,首次验证)与 UDG↔UDG 直连
- virtio 化方式:节点级 `node_update custom_adapters`(顶层 adapter_type 节点 update 不接受);e1000 模板未动

## 2. MTU 上限的分层实证(核心结论)

| 层 | max MTU | 来源 |
|---|---|---|
| guest virtio_net 驱动(FRR-qemu 内核) | **65535**(`ip -d link` maxmtu 实测) | 不是瓶颈 |
| UDG veth | 65535 | 不是瓶颈 |
| **宿主机 tap(gq\*)** | **65521(标称,`ip a` 可见,全部 16 个 tap 一致)** | **链路 MTU 名义顶** |
| 实际数据面 | **≥65522 通过**(桥转发是 L2 行为,不按 MTU 拦帧) | 65522 字节 IP 包 DF ping 实测通过 |
| 发送缓冲 | 65535 撞 `sendmsg: No buffer space available`(ENOBUFF) | 65507 payload 实测 |

**结论:用户口径"link 最大 MTU 65521"= 宿主 tap 标称值;但桥/tap 转发不按 MTU 丢帧,实测 65522 仍通,65535 被 socket 缓冲挡住。名义顶 65521,可用顶介于 65522~65535(发送端缓冲限制)。**

## 3. E1:MTU 阶梯(全路径一致,DF 边界=MTU−28 全部精确)

| MTU 档 | DF ping 边界 | iperf3 直连 | iperf3 经 2×FRR-qemu | OSPF |
|---|---|---|---|---|
| 1500(基线) | 1472 ✓ / 1473 本地拒 | 14.5 Gb/s | 4.17 Gb/s | Full |
| 9000 | 8972 ✓ / 8973 本地拒 | **40.7 Gb/s**(×2.8) | **18.3 Gb/s**(×4.4) | Full(不打断) |
| 16110(e1000 世界参照) | 16082 ✓ | 40.6 Gb/s | **18.7 Gb/s(峰值)** | Full |
| 65521 | 65493 ✓ / 65494 本地拒 | **62.4 Gb/s** | 16.1 Gb/s(回落) | Full |

- 巨型帧对 qemu 转发路径收益巨大(每包穿越成本被大包摊薄);但经 qemu 路径在 ~16K 达峰,64K 包回落(virtio 大包拷贝开销上升);直连(veth GSO)单调上升到 62.4G
- 零重传贯穿所有档位

## 4. E2:PMTUD / 出口收窄(R1 eth1=1500,其余 9000)

| 测项 | 结果 |
|---|---|
| DF 8972 经路由 | **`From 10.9.1.2: Frag needed and DF set (mtu = 1500)`**(ICMP type3/code4 回发送端) |
| 无 DF 8972 经路由 | 通,R1 出口分片转发、H2 重组回包(ttl=62) |
| `ip route get` | **`mtu 1500` 锁定**(PMTU cache,~600s 过期) |
| iperf3 | 4.26 Gb/s(从 18.3G 跌回 1500 档),Retr 99=初期撞墙,TCP PMTUD 完整收敛 MSS 8960→1460 |
| R1 snmp | FragOKs=3、**FragFails=1(精确对应 1 个 DF 大包)**、FragCreates=21 |

**PMTU 锁粘性(彩蛋):物理路径恢复 9000 后,route cache 的 mtu 1500 锁不过期 → iperf3 仍 4.13G;`ip route flush cache` 后立即回 18.8G。修好路径吞吐不自动恢复。**

**方向性实证(方法论级):MTU 属性不分方向,内核检查只在发送路径。收窄设在转发入口(R1 eth0)→ 9000 DF 包照常通过 18G(入向不查);设在转发出口(R1 eth1)→ frag needed。硬件 Catalyst 会在入向丢 giants,Linux 没有——仿真与真机行为差异。**

## 5. E3:OSPF × MTU 失配(R1 eth1=1500 / R2 eth0=9000)

完整五段轨迹:

1. **失配 → 永卡 ExStart/DR**(hello 正常、DD 交换被拒;`MTU mismatch detection: enabled` 为 FRR 8.2 默认)
2. 此时数据面前兆:H1 ping H2 得 **`Destination Net Unreachable`**(R1 无路由,code 6;不是 frag needed——包没走到出口检查)
3. **小端(R1)`ip ospf mtu-ignore` → ~10s 内 Full**(无需清邻居,DD 重传自然完成)
4. **去 mtu-ignore → 已建立的 Full 不打断**(检查只在建邻阶段,Full 不复查)
5. `clear ip ospf process` 强制重建 → 复现卡死;**MTU 对齐(eth1 回 9000)→ Full 恢复**(重启后 14.8s 亦 Full)

坑:`clear ip ospf process` 是 exec 命令,device 工具自动落 config 模式,需先 `end`。

## 6. E4:分片/重组

- 无 DF 8972 跨出口 1500:R1 分片(FragCreates 累计)、H2 重组成功回 8980 字节(行为级证明)
- H2 snmp 的 Reasm 字段与分片数不严格对应(内核字段语义/版本差异),以 ping/iperf3 行为为主证据,R1 的 Frag 三元组干净自洽
- 65521 档全程单帧直通无分片

## 7. E5:链路机制对照 + 三平台快测(当日补测)

### E5a:relay×jumbo —— 无载体,不可测(环境已演进)

本项目 4 链全 kernel_datapath。原计划借 IOL-XE 的 relay 链补测,但实测 `iol-docker-test` 场:12 条 IOL(IOL-XE/IOL-L2 docker)链**全部 kernel_datapath=true**——当前服务器(23f117de5)上 IOL 的 unix-socket NIO 链已全部 kernel 化,10-01"恒 relay"旧结论作废。relay 链仅存 VPCS↔docker 两条,VPCS 为 1500 固定 MTU 轻量栈、无大包能力 ⇒ **relay×jumbo 在当前环境无高 MTU 载体,不可构造**。uBridge UDP 载荷 65507 对 9000 帧理论上无碍(推断,未实测)。

### E5b:IOU / IOL-XE / Dynamips 三平台 jumbo 支持快测(全实测)

| 平台 | 操作 | 结果 |
|---|---|---|
| IOL-XE 17-18-02(iol-docker-test R1/R2,e0/0 直连) | `interface e0/0` + `mtu 9000` | **`% Interface Ethernet0/0 does not support user settable mtu.`** |
| IOU L3 adventerprisek9(IOU 场 IOU-R-1/2,e0/0 直连) | 同上 | **一字不差同样拒绝**(IOL 家族同根驱动) |
| Dynamips c7200 15.2(7200 场 R1/R2,f1/0=PA-FE-TX 直连) | `interface fa1/0` + `mtu 9000` | **语法层 `Invalid input`**(真机语义:FE 卡无 jumbo;要测须换 PA-GE,9216 上限) |

**结论:Cisco 仿真三平台(IOU/IOL-XE/c7200-FE)全部不支持巨型帧——jumbo 实验的载体只有 Linux 系(qemu/docker/veth/tap)。** 跨平台链路层(宿主 tap/桥)结论与节点类型无关,已由本场闭环,无需重测。

快测成本:IOL-XE/IOU 各 ~2 分钟(docker/IOU 启动快+配置即拒),Dynamips ~4 分钟(boot 慢);三场用后即停、已 close 还原。

## 8. 持久化方案(已验证重启生效)

| 节点 | 机制 | 内容 |
|---|---|---|
| H1/H2(UDG) | host 侧 `node_file_write` → `etc/network/interfaces` | address/netmask/gateway + `mtu 9000` + `up iperf3 -s -D` |
| R1/R2(FRR-qemu) | guest 内 console base64 直写 `/etc/network/interfaces`(Alpine ifupdown-ng,networking 服务在跑) | `iface ethX inet manual` + `up ip link set dev ethX mtu 9000` + up;IP 仍由 frr.conf(zebra)驱动 |

重启后验证:H1/R1 接口 mtu 9000 自动生效、OSPF Full 14.8s、DF 8972 通、iperf3 18.4 Gb/s。

## 9. 坑清单

1. **MTU 变更必须全部就位再验证**:并行改 4 节点时 ping 撞上未就绪端 → 假性 100% 丢包(@16110 首测踩中,复测通过)
2. 收窄点选在 OSPF 互联链路 → 先炸 OSPF(code 6)而非 PMTUD(code 4);收窄要选纯数据出口
3. FRR-qemu console 落 vtysh,vtysh 无 mtu 命令 → exit 到 bash `ip link set`,**完事必须发 vtysh 送回**(device 工具还依赖它)
4. device 工具自动进 config 模式:exec 命令(clear)前先 `end`;首条 `configure terminal` 报 Unknown command 无害
5. `ip -br link` 不显示 MTU 列;`ip -d link` 的 maxmtu 在第 2 行(sed 1p 会截掉)
6. qemu 节点顶层 adapter_type 拒改,须 `custom_adapters` 逐口
7. FRR-qemu guest = Alpine + BusyBox 1.35(ps 无 -p、base64/awk 可用),frr-8.2.2

## 10. 复现菜单(快照回滚后)

```bash
# 0) restore 快照 baseline-jumbo-9000 → start all → 45s
# 1) E1 阶梯:4 节点 ip link set dev eth0/eth1 mtu <档>;H1: ping -M do -s <档-28> 10.9.2.1;iperf3 -c 10.9.2.1 / 10.9.99.1
# 2) E2:R1 eth1 mtu 1500(注意 E3 连锁)→ H1 观察 frag needed / route 锁 / iperf3 降速;修完 ip route flush cache
# 3) E3:R1/R2 互联段失配 → show ip ospf neighbor 卡 ExStart;interface eth1 + ip ospf mtu-ignore → Full
# 4) 顶探:H1/R 全 65535 → ping -M do -s 65494(65522)实测过、65507 撞 ENOBUFF
```

## 11. 结论一句话

巨型帧在 GNS3 qemu(kernel-datapath virtio 链)上全档位端到端可用:9000 档对 qemu 转发吞吐 ×4.4(4.2→18.3G);链路 MTU 名义顶=宿主 tap 65521,实测 65522 仍通(桥不按 MTU 拦帧);Linux 转发只查出口 MTU,入口收窄无感;OSPF MTU 失配卡 ExStart 的小端 mtu-ignore 秒修;PMTU 锁有 600s 粘性,修路径后需 flush cache;**IOU/IOL-XE/c7200-FE 三平台全部不支持 jumbo(mtu 命令直接拒绝),巨型帧实验载体只有 Linux 系节点**。
