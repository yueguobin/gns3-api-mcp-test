# SRL-SpineLeaf-Test 方案与实施记录

> 日期：2026-09-13 ｜ 项目：`SRL-SpineLeaf-Test`（57839794-a868-437b-bfa7-71dae108f441）
> 模板：SRLinux（ghcr.io/nokia/srlinux:latest，v26.7.1，console=docker_exec 直达 sr_cli）+ Ubuntu Docker Guest
> 结论：**2S+4L eBGP Clos + 原生 EVPN/VXLAN（VNI 100）建成，8/8 会话 Est、leaf 双 ECMP、type-2/3 全网状、主机跨 Leaf E2E 0% 丢包**——与 DC-Test（XRd 无 NVE）、FRR-SpineLeaf（内核 VXLAN 模拟）不同，这是首次用"真 NOS 原生 EVPN"跑通的 Clos

## 1. 目标

用 SR Linux docker 复刻 Spine-Leaf fabric，验证 v26 平台的 eBGP underlay + 原生 EVPN-VXLAN overlay（mac-vrf、头端复制、eBGP RR）。

## 2. 拓扑

```
   S1 (AS65000)                    S2 (AS65000)
   system 10.0.0.1/32              system 10.0.0.2/32
   e1-1..e1-4 → L1..L4             e1-1..e1-4 → L1..L4
        10.1.L.0/31                     10.2.L.0/31
        (Spine .0/Leaf .1)              (Spine .0/Leaf .1)
     │            │            │            │
     L1           L2           L3           L4
  AS 65001     AS 65002      AS 65003     AS 65004
  system 10.0.0.11/32  ……  system 10.0.0.14/32（VTEP 源）
  e1-1↔S1  e1-2↔S2  e1-3→host（bridged，挂 mac-vrf）
     │            │            │            │
     H1           H2           H3           H4
  10.100.100.11/24 ………………………… 10.100.100.14/24（同网段跨 Leaf L2）
```

- 10 节点（6×SRLinux + 4×Ubuntu）、12 链路（8 fabric + 4 host）
- **单 eBGP 会话双 AF**：ipv4-unicast（underlay）+ evpn（overlay）同会话承载
- Spine 作 **eBGP EVPN RR**（`route-reflector client true`）；实测 **v26 eBGP RR 转售 EVPN 默认不改 NH**（与 FRR 行为一致，无需 next-hop-unchanged）
- VNI 100 / evi 100，mac-vrf，头端复制（type-3 自动），纯 L2

## 3. 编址与 AS 规划

| 项 | 规则 | 例子 |
|---|---|---|
| Spine AS | 两台同 AS 65000 | — |
| Leaf AS | 每台独立 6500N | L1=65001 … L4=65004 |
| fabric 链路 | 10.S.L.0/31（Spine .0 / Leaf .1） | S1↔L1 = 10.1.1.0/31 |
| system 地址 | system0.0 = 10.0.0.X/32（S=1,2；L=11-14）= VTEP 源 | L2 = 10.0.0.12/32 |
| EVPN RD | N:100（每 leaf 唯一） | L3 = 3:100 |
| EVPN RT | 统一 target:65000:100 | — |
| 租户 | 10.100.100.0/24，H_N=.1N | H3 = 10.100.100.13/24 |

## 4. 配置模板（v26 实测语法，与旧版差异极大）

### 4.1 Spine（S1 例，S2 把 10.1→10.2、system 换 10.0.0.2）

```text
/interface ethernet-1/K { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.K.0/31 } } }        # K=1..4 对 L_K
/interface system0 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.0.0.1/32 } } }
/network-instance default {
    interface ethernet-1/1.0 { } …… interface ethernet-1/4.0 { }
    interface system0.0 { } }
/routing-policy { …… prefix-set LO-ONLY + policy BGP-EXPORT(statement10 prefix 匹配
    + statement20 protocol bgp) + BGP-IMPORT-ALL，同 FRR 版思路 }
/network-instance default protocols bgp {
    admin-state enable
    autonomous-system 65000
    router-id 10.0.0.1
    afi-safi ipv4-unicast { admin-state enable
        import-policy [ BGP-IMPORT-ALL ]
        export-policy [ BGP-EXPORT ] }
    afi-safi evpn { admin-state enable }
    ebgp-default-policy { import-reject-all false      # ← v26 默认 true，必须关！
        export-reject-all false }
    route-reflector { client true }                     # 全局 RR 开关
    group leafN { peer-as 6500N                          # 4 个 group（peer-AS 不同）
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } } }
```

### 4.2 Leaf（L_N 例）

```text
/interface ethernet-1/1 { …… address 10.1.N.1/31 }      # e1-2 → 10.2.N.1
/interface ethernet-1/3 { admin-state enable             # host 口：bridged
    subinterface 0 { admin-state enable
        type bridged } }
/interface system0 { …… address 10.0.0.{10+N}/32 }       # VTEP 源；lo0 平移而来
/tunnel-interface vxlan0 {
    vxlan-interface 100 {
        type bridged                                     # ← v26 用 bridged（旧版 mac-vrf）
        ingress { vni 100 }                              # ← v26 结构化（旧版 ingress-vni）
        egress { source-ip use-system-ipv4-address } } }  # ← 只能枚举值=system 地址
/network-instance VNI-100 {
    type mac-vrf
    admin-state enable
    interface ethernet-1/3.0 { }
    vxlan-interface vxlan0.100 { }
    protocols {
        bgp-evpn { bgp-instance 1 {
            admin-state enable
            vxlan-interface vxlan0.100
            evi 100
            ecmp 2 } }
        bgp-vpn { bgp-instance 1 {                        # ← 不配 RD/RT 则零路由生成！
            route-distinguisher { rd N:100 }
            route-target { export-rt target:65000:100
                import-rt target:65000:100 } } } } }
/network-instance default protocols bgp {
    admin-state enable
    autonomous-system 6500N
    router-id 10.0.0.{10+N}
    afi-safi ipv4-unicast { admin-state enable
        import-policy [ BGP-IMPORT-ALL ]
        export-policy [ BGP-EXPORT ]
        multipath { ebgp { maximum-paths 4 } } }          # ← v26 默认单路径，ECMP 要显式
    afi-safi evpn { admin-state enable }
    ebgp-default-policy { import-reject-all false
        export-reject-all false }
    group ebgp-spines { peer-as 65000
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    neighbor 10.1.N.0 { peer-group ebgp-spines }
    neighbor 10.2.N.0 { peer-group ebgp-spines } }
commit save
```

### 4.3 Ubuntu 主机（H_N，console=telnet，live-only 不持久化）

```bash
ip link set eth0 up                 # 不 up 则 leaf 侧 e1-3 无载波 → EVPN 全挂（见坑1）
ip addr add 10.100.100.1N/24 dev eth0
```

## 5. 实施步骤（全 MCP + ws console）

1. `project_create` → 批量建 10 节点（S1/S2/L1-L4/H1-H4）→ 批量建 12 链路 → `node_start_all`
2. ws console（token 单次有效）分块推送 underlay：0.15-0.3s/line、`enter candidate private` → `commit save`
3. 修复 BGP-EXPORT（statement10 去 protocol static 改纯 prefix 匹配，见坑 4）
4. 推 overlay：host 口 bridged、system0 平移、tunnel-interface、mac-vrf（含 bgp-vpn RD/RT）、evpn AF、spine RR、multipath、ebgp-default-policy
5. 主机配 IP（载波拉起后 type-3 立即生成）
6. 验证（下节），期间日志排障用 `node_file_get` 直读 GNS3 volume 暴露的 `/var/log/srlinux/file/messages`

## 6. 验证结果（2026-09-13，全过）

| 检查项 | 结果 |
|---|---|
| eBGP 会话 | S1/S2 各 4/4 Est、L1-L4 各 2/2 Est（8/8） |
| underlay 路由 | leaf 收 5 条远端 system /32；`active-routes-with-ecmp 3`（multipath 4 生效） |
| lo/system ping | L1→10.0.0.13（跨脊）0% 丢包，ttl=63 |
| EVPN type-3 | leaf 收 3 条远端 IMET（各双路径经 S1/S2，Best 走 S1，tie-break peer-router-id） |
| EVPN type-2 | ping 触发后 6 条 MAC-IP（3 远端 MAC × 双路径），3 used |
| RR 转售 | spine 对 client 转售且 **NH 保持 10.0.0.1X 不改写**、AS 追加 65000、Cluster-List 空 |
| MAC 表 | 本地 1 learnt（ethernet-1/3.0）+ 远端 3 evpn（`vtep:10.0.0.12/13/14 vni:100`） |
| 主机 E2E | H1→H2/H3/H4 与 H2→H4 均 3/3、0% 丢包（rtt ≈1-3ms） |
| 持久化 | 6 台路由器全部 `commit save`（含排障期间的修复项） |

## 7. 坑与经验（按踩中顺序）

1. **host 载波决定 EVPN 生死（最大坑，排查 1 小时）**：type-3 生成要求 mac-vrf 内接口 oper-up；Ubuntu docker 的 eth0 不 `ip link set up` 则 leaf e1-3 无载波、子接口 down、bgp-instance oper up 但**零路由生成**、evpn [0/0/0]。日志线索：`networkInstanceInterfaceDown ... ethernet-1/3.0 in VNI-100`（messages 经 GNS3 extra_volumes 可直读，`node_file_list/get` 即可，无需进容器）。**先配主机再查 EVPN**。
2. **v26 ebgp-default-policy 默认 import/export-reject-all=true**：eBGP 无 policy 的 AF 一律拒收拒发（学了 FRR ebgp-requires-policy 的思路）。ipv4 我们有显式 policy 没踩到，evpn AF 全 0 就是它。fabric 全局关掉最省事。
3. **v26 EVPN 服务路由必须显式 RD/RT**：`/network-instance <mac-vrf> protocols bgp-vpn bgp-instance 1` 下配 rd + export-rt/import-rt；官方 lab（srl-labs/nokia-evpn-lab）标配，旧版"evi 自动推导"不再成立。不配则 bgp-evpn 零输出。
4. **BGP 只导出 active 路由**：lo 的 static blackhole anchor 被同前缀 host 路由压制（active false）→ `match protocol static` 匹配不到 → Tx=0。修法：statement 只 match prefix-set（host 路由也匹配）。组⑨ border 的 aggregate 无同前缀 host 所以当年没暴露。
5. **v26 语法变化**（vs 旧文档/skill）：`vxlan-interface` 下 `type bridged/routed`（非 mac-vrf/ip-vrf）、`ingress { vni }`（非 ingress-vni）、`egress source-ip` 只接受 `use-system-ipv4-address` 枚举 → **VTEP 源必须是 system0 地址**（lo0 平移过去；同 candidate 内 delete+add 避免重叠检查报错）；`system0` 是合法接口名。
6. **v26 BGP ECMP 默认关**：`afi-safi ipv4-unicast multipath { ebgp { maximum-paths N } }` 显式开启。
7. show 命令：`show /network-instance X tunnel-table`（tunnel**s**-table 不存在）；EVPN 路由 `show .../bgp routes evpn route-type {2|3|summary|detail}`；`ping network-instance VNI-100` 对 mac-vrf 报 "Must be an existing network namespace"（L2 NI 不能 ping，用主机侧验证）；`info from state` 查 list 必须带 key 或查父级。
8. tree 探测：路径不能带 list key（`tree /network-instance protocols bgp multipath` ✓，`tree /network-instance default ...` ✗）。
9. mac-vrf 的头端复制隧道不出现在 tunnel-table（那是 ip-vrf 的 routed VNI 概念），看 `bridge-table mac-table`（vtep: 字段）与 multicast-destinations。

## 8. 与 DC-Test（XRd）/ FRR-SpineLeaf-Test 对照

| 维度 | XRd（DC-Test） | FRR（FRR-SpineLeaf） | **SR Linux v26（本项目）** |
|---|---|---|---|
| EVPN | ✗（control-plane 版无 NVE，降级 routed tenant） | 内核 VXLAN 手搓 VTEP | **原生 mac-vrf/bgp-evpn** |
| VTEP 源 | — | lo0 任意 | **必须 system0 地址** |
| overlay 会话 | — | eBGP 双 AF | eBGP 双 AF（同会话 ipv4+evpn） |
| RR | — | spine 转售 | spine `route-reflector client true`，NH 不改 ✓ |
| 默认策略 | — | 需 ebgp-requires-policy 关闭 | **ebgp-default-policy 双开关默认 true** |
| 载波依赖 | 无此问题（routed 口） | 无（vrf vni 不看 host 载波?） | **mac-vrf 接口 down 则零 EVPN 路由** |
| 主机 E2E | routed 互 ping | L2 over VXLAN ✓ | L2 over VXLAN ✓（0% 丢包） |
