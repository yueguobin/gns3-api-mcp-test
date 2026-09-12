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

## 8. 与 DC-Test（XRd）对照

| 项 | DC-Test (XRd) | 本项目 (FRR) |
|---|---|---|
| 拓扑/AS/编址 | 2S+4L 同款设计 | 完全复用 |
| EVPN/VXLAN | 不可行（XRd 无 NVE），routed tenant | 同为 routed（FRR docker 可玩 VXLAN，留作后续） |
| 会话建立 | 手动 commit、分页坑多 | 一次推完、即时生效 |
| 断网收敛 | hold-timer ≈168s（eBGP 默认 180s） | 未演练（后续可 suspend S1 测） |
