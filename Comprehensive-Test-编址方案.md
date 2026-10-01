# Comprehensive Test 编址方案（2026-08-27）

项目：Comprehensive Test（6a21a432-e9cb-436a-9ea7-d5797eda1bb7），43 节点 / 82 链路。
十组业务组 + 双 route-server 骨干。本文档为唯一编址依据，配置推送以此为准。

## 全局规则

| 项 | 规则 | 示例 |
|---|---|---|
| 组网段 | 组G = 10.G.0.0/16（BGP 聚合整段） | G7 → 10.7.0.0/16 |
| 组 v6 | 2026:G::/32（/32，非 /48） | 2026:7::/32 |
| 节点间链路 | 10.G.**AB**.0/24，主机位=本机编号；v6 2026:G:AB::/64，主机 ::本机编号 | R5–R6：R5=10.2.56.5、R6=10.2.56.6 |
| Loopback0 | 10.G.N.N/32 + 2026:G:N::N/128（兼 router-id） | XRd-3 = 10.7.3.3 + 2026:7:3::3 |
| 骨干 | 10.99.99.0/24 + 2026:99:99::/64 | 见下表 |

映射关系沿用 mark-test 约定：10.X.Y.Z → 2026:X:Y::Z。

## 骨干 10.99.99.0/24（Sw1↔Sw2 e20 互连，单一 L2）

地址规律：**.1G = 组G 接 Sw1 侧边界，.2G = 接 Sw2 侧**（首位=交换机、末位=组号，助记用；
物理上同一网段）。v6 同号 ::1G/::2G。RS 双网卡各有独立地址，BGP 会话不依赖 e20 桥。

| 节点/口 | 挂哪 | v4 | v6 |
|---|---|---|---|
| G1 R3 f0/0 | Sw1-e0 | .11 | ::11 |
| G1 R4 f0/0 | Sw2-e1 | .21 | ::21 |
| G2 R7 f0/0 | Sw1-e2 | .12 | ::12 |
| G2 R8 f0/0 | Sw2-e2 | .22 | ::22 |
| G3 R-3 e1/3 | Sw1-e4 | .13 | ::13 |
| G3 R-4 e1/0 | Sw2-e3 | .23 | ::23 |
| G4 R-7 e0/0 | Sw1-e1 | .14 | ::14 |
| G4 R-8 e0/0 | Sw2-e4 | .24 | ::24 |
| G5 IOSv-3 Gi0/0 | Sw1-e3 | .15 | ::15 |
| G5 IOSv-4 Gi0/0 | Sw2-e5 | .25 | ::25 |
| G6 FRR-1 eth7 | Sw1-e5 | .16 | ::16 |
| G6 FRR-2 eth7 | Sw2-e6 | .26 | ::26 |
| G7 XRd-1 Gi0/0/0/22 | Sw1-e6 | .17 | ::17 |
| G7 XRd-2 Gi0/0/0/22 | Sw2-e7 | .27 | ::27 |
| G8 SRL-1 e1-34 | Sw1-e8 | .18 | ::18 |
| G8 SRL-2 e1-34 | Sw2-e8 | .28 | ::28 |
| G9 FRR-5 eth7 / eth6 | Sw1-e7 / Sw2-e0 | .19 / .29 | ::19 / ::29 |
| G10 IOL-XE-3 Eth0/3 | Sw1-e10 | .110 | ::110 |
| G10 IOL-XE-4 Eth0/3 | Sw2-e11 | .210 | ::210 |
| BGP-RS-1 eth0 / eth2 | Sw1-e19 / Sw2-e9 | .101 / .103 | ::101 / ::103 |
| BGP-RS-2 eth0 / eth2 | Sw1-e9 / Sw2-e10 | .102 / .104 | ::102 / ::104 |
| RS-1↔RS-2 eth1 直连 | — | 10.99.0.0/30（.1/.2） | 2026:99::/64（::1/::2） |
| RS Lo0 | — | .201 / .202 | ::201 / ::202 |

**BGP 对接规则**（路由阶段用）：Sw1 侧边界（.1G）→ 邻居 .101/.102；Sw2 侧（.2G）→ 邻居 .103/.104。
G9 FRR-5 主用 .19，.29 可加第二组会话。RS 间 eth1 段预留。

## 各组明细（均为 6 条 full-mesh + 上联）

### G1 R1–R4｜dynamips 7200（slot2=PA-8E，**以太 mesh**）｜AS64501
链路 12/13/14/23/24/34 → 10.1.AB.0/24。Lo0：10.1.1.1 … 10.1.4.4。
- R1: e2/0→R2, e2/1→R4, e2/2→R3
- R2: e2/0→R1, e2/1→R3, e2/2→R4
- R3: e2/1→R2, e2/2→R1, e2/3→R4, **f0/0→Sw1(.11)**
- R4: e2/1→R1, e2/2→R2, e2/3→R4, **f0/0→Sw2(.21)**

### G2 R5–R8｜dynamips 7200（slot2=PA-8T，**串口 mesh**）｜AS64502
链路 56/57/58/67/68/78 → 10.2.AB.0/24。Lo0：10.2.5.5 … 10.2.8.8。连线与 G1 同构：
- R5: s2/0→R6, s2/1→R7, s2/2→R8
- R6: s2/0→R5, s2/1→R8, s2/2→R7
- R7: s2/1→R5, s2/2→R6, s2/3→R8, **f0/0→Sw1(.12)**
- R8: s2/1→R6, s2/2→R5, s2/3→R7, **f0/0→Sw2(.22)**

### G3 R-1–R-4｜IOU 以太｜AS64503
链路 12/13/14/23/24/34 → 10.3.AB.0/24。Lo0：10.3.1.1 … 10.3.4.4。
- R-1: e0/0→R-2, e0/1→R-3, e0/2→R-4
- R-2: e0/0→R-1, e0/1→R-4, e0/2→R-3
- R-3: e0/1→R-1, e0/2→R-2, e0/3→R-4, **e1/3→Sw1(.13)**
- R-4: e0/1→R-2, e0/2→R-1, e0/3→R-3, **e1/0→Sw2(.23)**

### G4 R-5–R-8｜IOU 串口｜AS64504
链路 56/57/58/67/68/78 → 10.4.AB.0/24。Lo0：10.4.5.5 … 4.8.8。
- R-5: s2/0→R-6, s2/1→R-7, s2/2→R-8
- R-6: s2/0→R-5, s2/1→R-8, s2/2→R-7
- R-7: s2/1→R-5, s2/2→R-6, s2/3→R-8, **e0/0→Sw1(.14)**
- R-8: s2/1→R-6, s2/2→R-5, s2/3→R-7, **e0/0→Sw2(.24)**

### G5 CiscoIOSv-1–4｜qemu IOSv｜AS64505
链路 12/13/14/23/24/34 → 10.5.AB.0/24。Lo0：10.5.1.1 … 10.5.4.4。
- v1: Gi0/0→v2, Gi0/1→v3, Gi0/2→v4
- v2: Gi0/0→v1, Gi0/1→v4, Gi0/2→v3
- v3: Gi0/0→**Sw1(.15)**, Gi0/1→v1, Gi0/2→v2, Gi0/3→v4
- v4: Gi0/0→**Sw2(.25)**, Gi0/1→v2, Gi0/2→v1, Gi0/3→v3

### G6 FRRDocker-1–4｜FRR｜AS64506
链路 12/13/14/23/24/34 → 10.6.AB.0/24。Lo0：10.6.1.1 … 10.6.4.4。
- F1: eth0→F2, eth1→F3, eth2→F4, **eth7→Sw1(.16)**
- F2: eth0→F1, eth1→F4, eth2→F3, **eth7→Sw2(.26)**
- F3: eth0→F4, eth1→F1, eth2→F2
- F4: eth0→F3, eth1→F2, eth2→F1

### G7 XRdControlPlane-1–4｜XRd｜AS64507
链路 12/13/14/23/24/34 → 10.7.AB.0/24。Lo0：10.7.1.1 … 10.7.4.4。
- X1: /0→X2, /1→X3, /2→X4, **Gi0/0/0/22→Sw1(.17)**
- X2: /0→X1, /1→X4, /2→X3, **Gi0/0/0/22→Sw2(.27)**
- X3: /0→X4, /1→X1, /2→X2
- X4: /0→X3, /1→X2, /2→X1

### G8 SRLinux-1–4｜SRL v26｜AS64508
链路 12/13/14/23/24/34 → 10.8.AB.0/24。Lo0：10.8.1.1 … 10.8.4.4。
- S1: e1-1→S2, e1-2→S3, e1-3→S4, **e1-34→Sw1(.18)**
- S2: e1-1→S1, e1-2→S4, e1-3→S3, **e1-34→Sw2(.28)**
- S3: e1-1→S4, e1-2→S1, e1-3→S2
- S4: e1-1→S3, e1-2→S1, e1-3→S2

### G9 FRRDocker-5 + Ubuntu×2｜AS64509（按规律推定）
- FRR-5: eth0=10.9.11.1/24 + 2026:9:11::1/64（→Ubu-1），eth1=10.9.12.1/24 + 2026:9:12::1/64（→Ubu-2），Lo0=10.9.5.5 + 2026:9:5::5，eth7=10.99.99.19、eth6=10.99.99.29
- Ubu-1: eth0=10.9.11.2/24 + 2026:9:11::2，gw 10.9.11.1 / 2026:9:11::1
- Ubu-2: eth0=10.9.12.2/24 + 2026:9:12::2，gw 10.9.12.1 / 2026:9:12::1

### G10 CiscoIOL-XE-1–4｜IOL-XE docker（IOS-XE 17.18.2）｜**AS6510（用户指定，脱离 6450G 系列）**
链路 12/13/14/23/24/34 → 10.10.AB.0/24。Lo0：10.10.1.1 … 10.10.4.4。接口名 IOL 风格 `Ethernet0/x`（非 Gi）。
- XE-1: Eth0/0→XE-2, Eth0/1→XE-3, Eth0/2→XE-4
- XE-2: Eth0/0→XE-1, Eth0/1→XE-3, Eth0/2→XE-4
- XE-3: Eth0/0→XE-1, Eth0/1→XE-2, Eth0/2→XE-4, **Eth0/3→Sw1(.110)**
- XE-4: Eth0/0→XE-1, Eth0/1→XE-2, Eth0/2→XE-3, **Eth0/3→Sw2(.210)**
- OSPF：`router ospf 1`（v2 network 语句）+ `router ospfv3 1` AF ipv6 + 接口级 `ospfv3 1 ipv6 area 0`（同 G4 IOU17 语法）；iBGP v4 走骨干直连 .110↔.210、v6 走 lo0 + `update-source Loopback0`

## 路由实施记录（2026-08-28 完成并全通）

- 每组 OSPFv2+v3 area 0（IOS 传统 v6 / IOU17 ospfv3 AF / XRd router ospf(fv3) / FRR ospf+ospf6 / SRL 双 instance），边界三件套：Null0(blackhole) 锚定 + BGP network 汇总 + default-information originate always（SRL 内部用静态 ECMP 默认）
- 双 RS 64599：36 邻居/台全 Established；Sw1 侧边界 → .101/.102，Sw2 侧 → .103/.104
- **特例 1**：RS 对 FRR 系（F1/F2/F5 的 ::16/::26/::19/::29）在 v6 AF 下 `no route-server-client`——FRR 拒绝非对等体 link-local NH（RFC2545），普通 eBGP（NH=RS、AS 含 64599、流量经 RS 折返）才能通；v4 仍纯 route-server
- **特例 2**：FRR 环回是 `lo` 不是 `lo0`（lo0 为死配置不进内核，曾致 lo 地址/IGP 前缀全丢）；F1↔F2 v6 iBGP 需 `update-source lo`
- **特例 3**：FRR-5 双卡同网段——BGP `update-source` 钉会话源 + `ip route 10.99.99.10x/32 ethN` 钉转发接口，否则重启后内核选路次序随机、入向被 rp_filter 掐
- **运维注意**：Ubuntu 持久化走默认机制（镜像启动命令会执行 ifup）——`/etc/network/interfaces` 必须 **busybox 兼容格式**：`address`+`netmask` 分开写（不能写 CIDR，否则 busybox ifup 静默失败），v6 不用 inet6 stanza 而用 `up ip -6 addr add …` / `up ip -6 route add default …` 钩子；已验证 stop/start 全自动恢复 v4+v6。曾短暂用过 start_command hack，已弃用（清除时 node_update 传 null 无效、传空串 `""` 才清得掉）；IOS 家族改完配置必须当场 `do write memory`（曾因先存后配，重启丢整段路由）
- 验证：跨组 ping 矩阵 v4+v6 全通（内部节点经默认路由出组，覆盖全部 9 组×6 平台）；SRL 内部 ECMP 有 duplicate 回包属正常

## 复检与修复记录（2026-08-29）

- **边界对 v6 iBGP 缺 update-source（全 IOS 家族通病）**：G1–G5 五组边界对（R3/R4、R7/R8、R-3/R-4、R-7/R-8、IOSv-3/4）v6 iBGP 邻居建在对方 lo0 上但无 `update-source lo0`，从未 Established（Idle/never；v4 iBGP 因邻居恰配在直连段地址而幸免）；G7 XRd X1/X2 同病（卡 Active，需 `update-source Loopback0` + commit）。已全部修复 + `do write memory`/`commit`，修复后 Est/9pfx，且跨后续服务器重启持久化验证通过。G6（FRR update-source lo）、G8（SRL 6/6 UP）本就正常。
- 教训：RS 视角"36 会话全 Est"覆盖不到组内边界对 iBGP，巡检须从边界设备侧逐组看 summary。
- 同日 gns3server 3.1.0a5 更新：ws console token 改为短串 `gns3t_*` 且**单次有效**（一连接一取），websocat 输出不可接管道（会吞输出）；服务器重启后项目可能停 closed 需先 project_open。

## G10 扩展记录（2026-10-02，一次建成全通）

- 4×CiscoIOL-XE（docker 模板 6492832f，`iol-xe/iol-xe:17-18-02`，画布右上 (1095~1320, -555/-330)）+8 链路；模板自带 `netmiko_device_type: cisco_ios_telnet`，device 工具零配置直通，开机自带 hostname/`no ip domain lookup` 基础配置
- **IOL-XE 链路全部 kernel_datapath=false**（unix-socket NIO 非 TAP，含挂交换机的上联链），filter 仅 5 种 relay 基础款——全项目 kernel 链变为 61/82
- 坑 1：**FRR 侧新增 v6 邻居必须在 `address-family ipv6 unicast` 下显式 `activate`**——只配 remote-as+route-server-client 时会话不建立（XE 侧 Idle/never，RS v6 summary 里根本不出现），补 activate 后即起
- 坑 2：BGP-RS-1/2 节点原本无 device_type tag（模板 65e41e50 不带 netmiko 字段），已补 `device_type:cisco_ios_telnet` tag
- 路由：OSPFv2/v3 4×3 FULL；边界三件套 + iBGP（v4 直连/v6 lo0+update-source）+ eBGP 双 RS（XE-3→.101/.102、XE-4→.103/.104，`no bgp enforce-first-as`）；双 RS 各 40 邻居（v4+v6 各 20）全 Est，G10 四会话 PfxRcd=10（1 自有+9 转售，与老组指纹一致）
- 验证：XE-1→10.3.1.1 / 2026:8:1::1 / 10.99.99.19 全 5/5；反向 IOSv-1→10.10.1.1+2026:10:1::1、R-1→10.10.2.2+2026:10:4::4 全 5/5；全部 `do write memory`/`write memory` 持久化
