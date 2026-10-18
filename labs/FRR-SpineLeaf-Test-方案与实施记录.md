# FRR-SpineLeaf-Test 方案与实施记录

> 日期：2026-09-12 ｜ 项目：`FRR-SpineLeaf-Test`（cae66bff-51fb-4ac4-bff5-281430a19698）
> 模板：FRRDocker（gns3/frr:latest，FRR 10.x，**bgpd 可用**）+ Ubuntu Docker Guest
> 结论：**2S+4L eBGP Clos 一次建成，8/8 会话 Est，ECMP 双路径，主机跨 Leaf E2E 0% 丢包**

## 1. 目标

用 FRR docker 复刻 DC-Test（XRd 版）的 Spine-Leaf eBGP Clos 设计，验证 FRR 平台的 fabric 搭建与数据面连通。

## 2. 拓扑

```
        S1 (AS 65000)                     S2 (AS 65000)
        lo: 10.0.0.1/32                   lo: 10.0.0.2/32
        eth0..eth3 ──┐                 ┌── eth0..eth3
                     │   10.1.L.0/31   │   10.2.L.0/31
                     │   (S1 侧 .0)    │   (S2 侧 .0)
     ┌──────────────┼─────────────────┼──────────────┐
     L1             L2                L3             L4
  AS 65001       AS 65002          AS 65003       AS 65004
  lo 10.0.0.11   lo 10.0.0.12      lo 10.0.0.13   lo 10.0.0.14
  eth0↔S1 .1     eth0↔S1 .1        eth0↔S1 .1     eth0↔S1 .1
  eth1↔S2 .1     eth1↔S2 .1        eth1↔S2 .1     eth1↔S2 .1
  eth2: 192.168.1.1/24  ...         eth2: 192.168.3.1/24
     │                │                │                │
     U1               U2               U3               U4
  192.168.1.11/24  192.168.2.11/24  192.168.3.11/24  192.168.4.11/24
```

- 10 节点：6×FRRDocker（重命名 S1/S2/L1-L4）+ 4×Ubuntu（U1-U4，默认名后改名）
- 12 链路：8 fabric（S-L，/31）+ 4 host（L eth2 ↔ U eth0）
- 无 IGP：纯 eBGP，Leaf 通告 lo /32 + 租户 /24，Spine 纯转售

## 3. 编址与 AS 规划

| 项 | 规则 | 例子 |
|---|---|---|
| Spine AS | 两台同 AS 65000 | — |
| Leaf AS | 每台独立 6500N | L1=65001 … L4=65004 |
| fabric 链路 | 10.S.L.0/31（Spine .0 / Leaf .1） | S1↔L1 = 10.1.1.0/31，S2↔L3 = 10.2.3.0/31 |
| 路由器 lo | 10.0.0.X/32（S1/S2=1,2；L1-L4=11-14） | L2 lo = 10.0.0.12/32 |
| 租户网段 | 192.168.N.0/24，Leaf eth2 .1，主机 .11 | U3 = 192.168.3.11/24 gw 192.168.3.1 |

## 4. 配置模板

### Spine（S1 示例，S2 把 10.1→10.2、lo 换 10.0.0.2）

```text
conf t
int lo
 ip address 10.0.0.1/32
int eth0
 ip address 10.1.1.0/31
int eth1
 ip address 10.1.2.0/31
int eth2
 ip address 10.1.3.0/31
int eth3
 ip address 10.1.4.0/31
exit
router bgp 65000
 no bgp ebgp-requires-policy
 neighbor 10.1.1.1 remote-as 65001
 neighbor 10.1.2.1 remote-as 65002
 neighbor 10.1.3.1 remote-as 65003
 neighbor 10.1.4.1 remote-as 65004
 address-family ipv4 unicast
  neighbor 10.1.1.1 activate
  neighbor 10.1.2.1 activate
  neighbor 10.1.3.1 activate
  neighbor 10.1.4.1 activate
  network 10.0.0.1/32
 exit-address-family
end
wr
```

### Leaf（L1 示例，其余换 N）

```text
conf t
int lo
 ip address 10.0.0.11/32
int eth0
 ip address 10.1.1.1/31
int eth1
 ip address 10.2.1.1/31
int eth2
 ip address 192.168.1.1/24
exit
router bgp 65001
 no bgp ebgp-requires-policy
 neighbor 10.1.1.0 remote-as 65000
 neighbor 10.2.1.0 remote-as 65000
 address-family ipv4 unicast
  neighbor 10.1.1.0 activate
  neighbor 10.2.1.0 activate
  network 10.0.0.11/32
  network 192.168.1.0/24
 exit-address-family
end
wr
```

FRR 要点：`no bgp ebgp-requires-policy`（否则 eBGP 不发包）、邻居必须在 address-family 下显式 `activate`（FRR 默认不自动激活）。

### Ubuntu 主机（U_N，console=bash）

```bash
ip link set eth0 up
ip addr add 192.168.N.11/24 dev eth0
ip route add default via 192.168.N.1
```

注意：live 配置无持久化（镜像无 ifup/systemd），节点重启需重推。

## 5. 实施步骤（全 MCP/ws console）

1. `project_create` FRR-SpineLeaf-Test
2. 批量 `node_create` 6×FRRDocker + 4×Ubuntu Docker Guest（默认名，后 `node_update` 改名 S1/S2/L1-L4/U1-U4）
3. 批量 `link_create`×12（compact 格式 [id, adapter, port, ...]，8 fabric + 4 host）
4. `node_start`（显式列 10 台 id，绕开僵尸节点 Lite-5 用 start_all）
5. ws console 推 6 台 FRR 配置（vtysh），`wr` 落盘 frr.conf
6. ws console 推 4 台 Ubuntu ip 命令
7. 验证（下节）

## 6. 验证结果（2026-09-12，全过）

**BGP 会话（show bgp ipv4 unicast summary）**

| 节点 | 邻居 | 状态 |
|---|---|---|
| S1 | 10.1.1.1 / 10.1.2.1 / 10.1.3.1 / 10.1.4.1 | 4/4 Est（PfxRcd=2，PfxSnt=9） |
| S2 | 10.2.1.1 / 10.2.2.1 / 10.2.3.1 / 10.2.4.1 | 4/4 Est |
| L1 | 10.1.1.0 / 10.2.1.0 | 2/2 Est（PfxRcd=7） |

**路由（L1 `show ip route bgp`）**：全部远端 lo /32 + 租户 /24 均在 RIB，**非直连前缀全部 ECMP 双路径**（via 10.1.1.0 eth0 与 10.2.1.0 eth1），例：

```text
B>* 192.168.4.0/24 [20/0] via 10.1.1.0, eth0, weight 1
  *                        via 10.2.1.0, eth1, weight 1
```

**ping 矩阵**

| 源 → 目的 | 结果 |
|---|---|
| L1 → 10.0.0.2（S2 lo，跨 fabric） | 7/7，0% loss |
| U1 → U2 / U3 / U4（跨 Leaf 主机） | 全部 3/3，0% loss（ttl=61，经 Spine 转发） |
| U1 → 10.0.0.14（远端 Leaf lo） | 3/3，0% loss |

## 7. 坑与经验

1. **FRRDockerLite ≠ FRRDocker**：两者 template 数据完全一致（同 image tag、同参数，created_at 不同），差异在镜像内容/daemon 集——Lite 的 daemon 集没有 bgpd（技能记录：mgmtd/zebra/ospfd/ospf6d），**跑 BGP 必须用 FRRDocker**（实测 daemon：`mgmtd zebra ospfd ospf6d bgpd watchfrr staticd`）。模板数据看不出，只能 show daemons 或翻旧项目。
2. **vtysh 的 `wr` 必须在 enable 模式**：config 模式下报 Unknown command。配置块结尾用 `end`（而非逐级 exit）再 `wr`。
3. **ws console `\x03` 后第一条命令可能被吞开头字符**（"ping"→"ing"）：`\x03` 后补一个空 `\r\n` 刷新提示符再发实命令。FRR vtysh 主进程节点无此现象（vtysh 无 bracketed-paste）。
4. **批量 node_delete 报 404 ≠ 删干净**：FRRDockerLite-5 删除报 404，但 node_list 仍可见（僵尸条目），node_get 也 404。需重启 GNS3 服务自愈；期间 start_all 会把它拉起，改用显式 id 列表启动。
5. console 主进程即 vtysh（FRR 镜像），bootstrap 里的 `vtysh` 命令报 Unknown command 属预期无害。
6. Ubuntu Docker Guest 配置是 live-only，重启即丢（无 ifup）；如需持久化可写 /etc/rc.local 或 rc-local 兜底（未实施）。

## 8. EVPN/VXLAN 叠加层（09-13 建成，全验证通过）

在 routed underlay 之上叠加 BGP EVPN + VXLAN（RFC 8365 单会话双 AF：现有 eBGP 会话同时承载 ipv4 unicast + l2vpn evpn）。

### 8.1 设计

- **VNI 100**（L2 拉伸，172.20.100.0/24）覆盖 4 台 Leaf；每 Leaf：`br100`（vlan_filtering 1）桥接 `eth3`（主机腿）+ `vxlan100`（固定 id 100，local-tunnelip= 本机 lo，dstport 4789，nolearning）
- BUM 走 EVPN type-3 头端复制；MAC 走 type-2 BGP 通告（无 flooding 学习）
- U1-U4 用空闲 eth1 接入：172.20.100.11-14/24
- 新增 4 链路：L_N eth3 ↔ U_N eth1

### 8.2 Leaf 配方（内核 + vtysh，L_N 例）

```bash
# 内核对象（console 先 exit 掉 vtysh 进 bash；live-only，重启需重推）
ip link add br100 type bridge vlan_filtering 1
ip link add vxlan100 type vxlan id 100 local 10.0.0.1N dstport 4789 nolearning
ip link set vxlan100 master br100
ip link set eth3 master br100
bridge vlan add dev vxlan100 vid 100
bridge vlan add dev eth3 vid 100 pvid untagged
bridge vlan del dev eth3 vid 1
ip link set br100 up && ip link set vxlan100 up && ip link set eth3 up
```

```text
conf t
router bgp 6500N
 address-family l2vpn evpn
  neighbor 10.1.N.0 activate
  neighbor 10.2.N.0 activate
  advertise-all-vni          ← 关键！见 8.4
 exit-address-family
end
wr
```

Spine 只需 af l2vpn evpn 下逐邻居 `activate`（无需任何 next-hop 配置，见 8.4 第 2 条）。

### 8.3 验证结果（全过）

| 检查项 | 结果 |
|---|---|
| show evpn vni（4 台 Leaf） | VNI 100 L2，Remote VTEPs 阶梯递增 1/2/3（type-3 互播成功） |
| U1→U2/U3/U4（172.20.100.x） | 全部 3/3、0% loss（ttl=64，L2 over VXLAN） |
| show bgp l2vpn evpn（L1） | 每 VTEP 独立 RD（10.0.0.11-14:2）；type-2/3 齐全；**type-2 next-hop= 源 VTEP lo**，AS path `65000 65002`（经 Spine 转售），RT 6500N:100 |
| show evpn mac vni 100（L1） | 本地 MAC（eth3）+ 3 条远端 MAC → VTEP 10.0.0.12/13/14（BGP 学习） |

### 8.4 排障实录（半天踩坑，按时间线）

1. **`show evpn vni` 空表（最大坑，消耗最久）**：zebra 完全认识 vxlan 接口（`show interface vxlan100` 显示 VxLAN Id/VTEP IP/Master 全对），但 VNI 表恒空。逐层排查：vlan-unaware→vlan-aware、`tunnel_info`、SVI 子接口、重建 vxlan 触发重评估、`debug zebra vxlan`（零输出）——全部无效。最终读 FRR 源码定位：`zevpn_build_hash_table()` 开头 `zvrf = zebra_vrf_get_evpn(); if (zvrf == NULL) return;`，而 bgpd 侧 `bgp_zebra.c`：`if (bgp->advertise_all_vni) bgp_zebra_advertise_all_vni(bgp, 1);`——**FRR 10.3 的 `advertise-all-vni` 不是默认开**，不配它 bgpd 永不向 zebra 注册 EVPN，VNI 表永远空。一条命令解决。
2. **eBGP EVPN 的 next-hop**：10.3 里 `neighbor X next-hop-unchanged`/`nexthop-unchanged`/`bgp evpn next-hop-unchanged` 全部 Unknown command——因为 **EVPN AF 发 eBGP 邻居默认就不改 next-hop**（RFC 8365 语义，无开关）。实测 type-2 跨两级 eBGP 后 next-hop 仍是源 VTEP lo。别去配不存在的命令。
3. **`tunnel_info` 只属于 external 模式**：`bridge vlan add dev vxlanX vid V tunnel_info id VNI` 对固定 id 的 vxlan 报 `RTNETLINK Invalid argument`（新 iproute2；旧版静默接受但无意义）。固定 id + 普通 `vid` 成员即可。
4. **官方镜像 quay.io/frrouting/frr 在 GNS3 里不好使**（A/B 测试用）：console 接 PID 1 = watchfrr，**`\x03` 会直接杀掉整个 FRR 栈**；须 template `start_command=/bin/bash` + `sed bgpd=yes /etc/frr/daemons` + `frrinit.sh start` 手工拉起；vtysh 每条命令都刷 `frr.conf processing failure: 11` 噪音。**结论：FRR on GNS3 用 gns3/frr（FRRDocker 模板）即可**，EVPN 能力齐全。测试模板 FRR-Official-10.7 已保留（T1 节点已删）。
5. FRR doc 的 SVI（vlan 子接口）只有 IRB/ARP 抑制才需要，纯 L2 VNI 不用（实测 sv100 删不删无影响）。

## 9. 与 DC-Test（XRd）对照

| 项 | DC-Test (XRd) | 本项目 (FRR) |
|---|---|---|
| 拓扑/AS/编址 | 2S+4L 同款设计 | 完全复用 |
| EVPN/VXLAN | 不可行（XRd 无 NVE），routed tenant | **已建成全验证**（L2VNI 拉伸，type-2/3 + 头端复制） |
| 会话建立 | 手动 commit、分页坑多 | 一次推完、即时生效 |
| 断网收敛 | hold-timer ≈168s（eBGP 默认 180s） | 未演练（后续可 suspend S1 测） |
