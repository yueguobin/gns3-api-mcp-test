# SRL-SpineLeaf-Test 方案与实施记录

> 日期：2026-09-13 ｜ 项目：`SRL-SpineLeaf-Test`（57839794-a868-437b-bfa7-71dae108f441）
> 模板：SRLinux（ghcr.io/nokia/srlinux:latest，v26.7.1-554，console=docker_exec 直达 sr_cli）+ Ubuntu Docker Guest（telnet）
> 结论：**2S+4L eBGP Clos + 原生 EVPN/VXLAN（VNI 100）建成，8/8 会话 Est、leaf 双 ECMP、type-2/3 全网状、主机跨 Leaf E2E 0% 丢包**——与 DC-Test（XRd 无 NVE）、FRR-SpineLeaf（内核 VXLAN 模拟）不同，这是首次用"真 NOS 原生 EVPN"跑通的 Clos。排障 3 关（host 载波 / ebgp-default-policy / 显式 RD-RT），实录见 §7。

## 1. 目标

用 SR Linux docker 复刻 Spine-Leaf fabric，验证 v26 平台的 eBGP underlay + 原生 EVPN-VXLAN overlay（mac-vrf、头端复制、eBGP RR）。

## 2. 拓扑与接口映射

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
  e1-1↔S1  e1-2↔S2  e1-3→host（bridged，挂各自 mac-vrf）
     │            │            │            │
     H1           H2           H3           H4
  └─租户A VNI100─┘        租户B VNI200   租户C VNI300
  10.100.100.0/24          10.100.200.0/24 10.100.3.0/24
  （H1 .11 ↔ H2 .12 跨 Leaf L2 互通；B/C 单叶隔离）
```

- 10 节点（6×SRLinux + 4×Ubuntu）、12 链路（8 fabric + 4 host）
- **三租户**（2026-09-13 追加）：租户 A = H1+H2（VNI 100，跨 Leaf）；租户 B = H3（VNI 200，L3 单叶）；租户 C = H4（VNI 300，L4 单叶）——覆盖"跨叶同租户 / 单叶独占"两种形态
- 接口映射：GNS3 adapter N ↔ `e1-N` ↔ `ethernet-1/N`（adapter 0=mgmt0）；host 侧 adapter 0=eth0
- **单 eBGP 会话双 AF**：ipv4-unicast（underlay）+ evpn（overlay）同会话承载（Nokia IP Fabric 风格，spine/leaf 各一条会话到对端）
- Spine 作 **eBGP EVPN RR**（bgp 全局级 `route-reflector { client true }`）；实测 **v26 eBGP RR 转售 EVPN 默认不改 NH**（与 FRR 行为一致，无 knob 也无需）
- mac-vrf + 头端复制（type-3 自动），纯 L2 无 IRB；**多租户靠每 VNI 的 RT 隔离**（spine 全量转售，leaf 按 import-rt 只收本 VNI）

## 3. 编址与对象规划

| 项 | 规则 | 例子 |
|---|---|---|
| Spine AS | 两台同 AS 65000（双 RR） | — |
| Leaf AS | 每台独立 6500N | L1=65001 … L4=65004 |
| fabric 链路 | 10.S.L.0/31（Spine .0 / Leaf .1） | S1↔L1 = 10.1.1.0/31，S2↔L3 = 10.2.3.0/31 |
| system 地址 | system0.0 = 10.0.0.X/32（S=1,2；L=11-14）= VTEP 源 = router-id | L2 = 10.0.0.12/32 |
| EVPN RD | `<N>:<VNI>`（每 leaf 每 VNI 唯一） | L3 的 VNI-200 = 3:200 |
| EVPN RT | `target:65000:<VNI>`（同 VNI 全网统一 = 租户标识） | 三租户 = :100 / :200 / :300 |
| 租户 A | VNI 100 ↔ 10.100.100.0/24，H1=.11 H2=.12（跨 Leaf） | — |
| 租户 B | VNI 200 ↔ 10.100.200.0/24，H3=.13 | — |
| 租户 C | VNI 300 ↔ 10.100.3.0/24，H4=.14（**不能写 10.100.300.x——非合法 IPv4**，见坑 11） | — |

> 租户网段无网关（纯 L2）；同名 VNI 的 RD 每 leaf 唯一、RT 全网一致，是 EVPN 多租户的正交设计。

## 4. 配置模板（v26 实测语法，可直接改参推送）

> 与旧版文档/skill 差异极大：`type bridged/routed`（非 mac-vrf/ip-vrf）、`ingress { vni }`（非 ingress-vni）、`egress source-ip` 只接受 `use-system-ipv4-address` 枚举、RD/RT 必须显式、ebgp-default-policy 默认全拒、multipath 默认关。差异全表见 §8。

### 4.1 Spine（S1 全量；S2 把 10.1→10.2、system/router-id 换 10.0.0.2）

```text
enter candidate private
/interface ethernet-1/1 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.1.0/31 } } }
/interface ethernet-1/2 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.2.0/31 } } }
/interface ethernet-1/3 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.3.0/31 } } }
/interface ethernet-1/4 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.4.0/31 } } }
/interface system0 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.0.0.1/32 } } }
/network-instance default {
    interface ethernet-1/1.0 { }
    interface ethernet-1/2.0 { }
    interface ethernet-1/3.0 { }
    interface ethernet-1/4.0 { }
    interface system0.0 { } }
/routing-policy {
    prefix-set LO-ONLY {
        prefix 10.0.0.1/32 mask-length-range exact { }
    }
    policy BGP-EXPORT {
        statement 10 {
            match {
                prefix { prefix-set LO-ONLY }      ← 纯 prefix 匹配：导出 system host 路由（坑 7）
            }
            action { policy-result accept }
        }
        statement 20 {
            match { protocol bgp }                 ← 转售 leaf 路由
            action { policy-result accept }
        }
        default-action { policy-result reject }
    }
    policy BGP-IMPORT-ALL {
        default-action { policy-result accept }
    }
}
/network-instance default protocols bgp {
    admin-state enable
    autonomous-system 65000
    router-id 10.0.0.1
    afi-safi ipv4-unicast { admin-state enable
        import-policy [ BGP-IMPORT-ALL ]
        export-policy [ BGP-EXPORT ] }
    afi-safi evpn { admin-state enable }
    ebgp-default-policy {                          ← v26 默认 true，必须关（坑 2）
        import-reject-all false
        export-reject-all false }
    route-reflector {
        client true }                              ← 全局 RR 开关，4 个 leaf 全是 client
    group leaf1 { peer-as 65001
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    group leaf2 { peer-as 65002
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    group leaf3 { peer-as 65003
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    group leaf4 { peer-as 65004
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    neighbor 10.1.1.1 { peer-group leaf1 }
    neighbor 10.1.2.1 { peer-group leaf2 }
    neighbor 10.1.3.1 { peer-group leaf3 }
    neighbor 10.1.4.1 { peer-group leaf4 }
}
commit save
```

注：每 leaf 独立 AS → spine 需 4 个 group（group 的 peer-as 单值）。spine 不需要 multipath（每前缀单来源）。

### 4.2 Leaf（L1 全量；L_N 换 N 与 10.0.0.11）

```text
enter candidate private
/interface ethernet-1/1 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.1.1.1/31 } } }              # e1-2 → 10.2.N.1
/interface ethernet-1/2 { admin-state enable
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.2.1.1/31 } } }
/interface ethernet-1/3 { admin-state enable       # host 口：bridged
    subinterface 0 { admin-state enable
        type bridged } }
/interface system0 { admin-state enable            # VTEP 源；由 lo0 平移而来（坑 5）
    subinterface 0 { admin-state enable
        ipv4 { admin-state enable
            address 10.0.0.11/32 } } }
/network-instance default {
    interface ethernet-1/1.0 { }
    interface ethernet-1/2.0 { }
    interface system0.0 { }
    next-hop-groups { group BLACKHOLE { blackhole { } } }   # static anchor，见注
    static-routes { route 10.0.0.11/32 { next-hop-group BLACKHOLE } } }
/routing-policy {
    prefix-set LO-ONLY {
        prefix 10.0.0.11/32 mask-length-range exact { }
    }
    policy BGP-EXPORT {
        statement 10 {
            match {
                prefix { prefix-set LO-ONLY }
            }
            action { policy-result accept }
        }
        statement 20 {
            match { protocol bgp }
            action { policy-result accept }
        }
        default-action { policy-result reject }
    }
    policy BGP-IMPORT-ALL {
        default-action { policy-result accept }
    }
}
/tunnel-interface vxlan0 {
    vxlan-interface 100 {
        type bridged                               # ← v26 用 bridged（旧版 mac-vrf）
        ingress { vni 100 }
        egress { source-ip use-system-ipv4-address } } }
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
        bgp-vpn { bgp-instance 1 {                 # ← 不配 RD/RT 则零路由生成（坑 3）
            route-distinguisher { rd 11:100 }
            route-target {
                export-rt target:65000:100
                import-rt target:65000:100 } } } } }
/network-instance default protocols bgp {
    admin-state enable
    autonomous-system 65001
    router-id 10.0.0.11
    afi-safi ipv4-unicast { admin-state enable
        import-policy [ BGP-IMPORT-ALL ]
        export-policy [ BGP-EXPORT ]
        multipath { ebgp { maximum-paths 4 } } }   # ← v26 默认单路径，ECMP 要显式（坑 6）
    afi-safi evpn { admin-state enable }
    ebgp-default-policy {
        import-reject-all false
        export-reject-all false }
    group ebgp-spines { peer-as 65000
        afi-safi ipv4-unicast { admin-state enable }
        afi-safi evpn { admin-state enable } }
    neighbor 10.1.1.0 { peer-group ebgp-spines }
    neighbor 10.2.1.0 { peer-group ebgp-spines }
}
commit save
```

注：static anchor（BLACKHOLE）是首轮按组⑨经验配的，实测被同前缀 system host 路由压制（active false）、真正被 BGP 导出的是 host 路由（坑 7），保留无害。

**多租户扩展 = 在同一台 leaf 上克隆三件套**（L3 增加 VNI 200 例，vni/evi/RD/RT 换号即可）：

```text
/tunnel-interface vxlan0 {
    vxlan-interface 200 {
        type bridged
        ingress { vni 200 }
        egress { source-ip use-system-ipv4-address } } }
/network-instance VNI-200 {
    type mac-vrf
    admin-state enable
    interface ethernet-1/3.0 { }            # host 口移挂到新 VNI（delete 旧 VNI 里的引用）
    vxlan-interface vxlan0.200 { }
    protocols {
        bgp-evpn { bgp-instance 1 { admin-state enable
            vxlan-interface vxlan0.200
            evi 200
            ecmp 2 } }
        bgp-vpn { bgp-instance 1 {
            route-distinguisher { rd 3:200 }                    # <leaf号>:<VNI>
            route-target { export-rt target:65000:200
                import-rt target:65000:200 } } } } }            # <AS>:<VNI>
# 同一 candidate 内：delete /network-instance VNI-100 interface ethernet-1/3.0
```

BGP/RR/underlay 完全不动（evpn AF 与会话级配置与 VNI 数量无关）。

### 4.3 Ubuntu 主机（H_N，console=telnet，**/etc/network/interfaces 持久化**）

镜像开机由 `/gns3/init.sh` 用 **busybox ifup -a -f** 应用 `/etc/network/interfaces`（文件跨容器 stop/start 保留，H1/H3/H4 重启实测：IP 自动回、ping 恢复）。注意：**busybox ifup 不认 CIDR**（address/netmask 分列）、**地址必须是合法 IPv4**（10.100.300.x 这类超界八位组会在 ifup 时静默失败，坑 11）；运行时 shell 里**没有** ifup/ifdown 命令（载波靠 ip 命令或重启拉起）：

```bash
# 首次（拉起载波 → type-3 立即生成；不 up 则 leaf 侧 e1-3 无载波 → EVPN 全挂，坑 1）
ip link set eth0 up
ip addr add 10.100.100.1N/24 dev eth0
# 持久化（base64 写文件，telnet console 多行最稳）
echo <base64> | base64 -d > /etc/network/interfaces
```

文件内容（各 host 按租户换 address）：

```text
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet static
    address 10.100.100.11      # H1 .11 / H2 .12 / H3 10.100.200.13 / H4 10.100.3.14
    netmask 255.255.255.0
```

## 5. 实施步骤（全 MCP + ws console）

1. **建拓扑**：`project_create` → `node_create` 批量 10 节点（自定义名 S1/S2/L1-L4/H1-H4）→ `link_create` 批量 12 条（Spine adapter K↔Leaf adapter 1/2，host adapter 3↔H adapter 0）→ `node_start_all`，约 90s 全 started
2. **推配置**：每台一次 ws 连接整块推送，模板：
   ```bash
   { printf '\r\n'; sleep 4; while IFS= read -r line; do printf '%s\r\n' "$line"; sleep 0.2; done < /tmp/lN_cfg.txt; sleep 12; } \
     | timeout 70 websocat -t --no-close '<node_console 的 ws_url 逐字节复制，token 单次有效>'
   ```
   判据：输出含 `All changes have been committed`。**websocat 输出禁接管道**——先 `> 文件`，再 `sed 's/\x1b\[[0-9;?]*[a-zA-Z]//g'` 清 ANSI 后 grep
3. **host 配 IP**（`ip` 命令拉起载波，EVPN type-3 随即生成；随后写 `/etc/network/interfaces` 持久化，见 §4.3）
4. **验证**（§6），排障时日志用 `node_file_list/get` 直读 GNS3 extra_volumes 暴露的 `var/log/srlinux/file/messages`（无需进容器）

## 6. 验证结果（2026-09-13，全过）

| 检查项 | 结果 |
|---|---|
| eBGP 会话 | S1/S2 各 4/4 Est、L1-L4 各 2/2 Est（8/8），evpn+ipv4 双 AF 同会话 |
| underlay 路由 | leaf 收 5 条远端 system /32；`active-routes 10, active-routes-with-ecmp 3` |
| system 互 ping | L1→10.0.0.13（跨脊）0% 丢包，ttl=63 |
| EVPN type-3 | leaf 收 3 条远端 IMET × 双路径（Best 走 S1，tie-break peer-router-id） |
| EVPN type-2 | ping 触发后 6 条 MAC-IP（3 远端 MAC × 双路径），3 used |
| RR 转售 | NH 保持 10.0.0.1X 不改写、AS 追加 65000、Cluster-List 空 |
| MAC 表 | 本地 1 learnt（ethernet-1/3.0）+ 远端 3 evpn（`vtep:10.0.0.12/13/14 vni:100`） |
| 主机 E2E（单租户时期） | H1→H2/H3/H4 与 H2→H4 均 3/3、0% 丢包（rtt ≈0.8-3ms） |
| 持久化 | 6 台路由器全部 `commit save`（含排障修复项）；4 台 host 写 `/etc/network/interfaces`（H1/H3/H4 经 node stop→start 重启实测：文件保留、init.sh 自动 ifup、IP 自动恢复） |

**三租户划分后复验（2026-09-13 追加）**：

| 检查项 | 结果 |
|---|---|
| 租户 A 内 | H1→H2 3/3 **0% 丢包**（跨 Leaf L2 over VXLAN，rtt ≈2ms）；L1 VNI-100 MAC 表 = H1 本地 learnt + H2 远端 evpn（vtep:10.0.0.12） |
| 租户 B 隔离 | H3（10.100.200.13/24，仅本地直连路由）ping A/C 均 **Network is unreachable**；L3 VNI-200 MAC 表仅 H3 本地 1 条、evpn 0 条 |
| 租户 C 隔离 | H4（10.100.3.14/24）ping A/B 均 **Network is unreachable**；L4 VNI-300 MAC 表仅 H4 本地 1 条、evpn 0 条 |
| A 侧反向 | H1 ping 原 .13/.14（已迁出租户 A）→ 2/2 **100% 丢包**（ARP 无应答，MAC 已从 VNI-100 撤走） |
| RT 过滤 | L3 的 VNI-100 只剩 H1 的 evpn MAC（H3/H4 的 type-2 因 RT 不匹配、且搬去 VNI 200/300 后不再进入本 VNI） |
| MAC 老化 | 静默 5 分钟后 learnt/evpn MAC 自动撤回（L1 VNI-100 一度全空），打流量即重建——正常 EVPN 行为，非故障 |

### 6.0 三租户划分操作摘要

- 只动 L3/L4 两台 leaf：各新增一个 VNI 三件套（vxlan-interface / mac-vrf / bgp-evpn+bgp-vpn），并把 `ethernet-1/3.0` 从 VNI-100 移挂到新 VNI（同 candidate 内 delete+add，一次 commit）
- H3/H4 改 `/etc/network/interfaces` 网段后 node stop→start 生效
- L1/L2/Spine 与租户 A 配置零改动，A 内互通不受影响

### 6.1 关键输出摘录（原文）

L1 会话终态（双 AF、双 spine）：

```
| default | 10.1.1.0 | ebgp-spines | S | 65000 | established | 0d:0h:40m | evpn [4/4/1]  | ipv4-unicast [4/4/2] |
| default | 10.2.1.0 | ebgp-spines | S | 65000 | established | 0d:0h:39m | evpn [4/0/5]  | ipv4-unicast [4/4/5] |
```

type-3 detail（RR 不改 NH 的直接证据）：

```
Route Distinguisher: 2:100   Originating router : 10.0.0.12
  Path 1: <Best,Valid,Used,>
    BGP next-hop : 10.0.0.12          ← 远端 leaf system IP，未经 spine 改写
    AS Path       : i [65000, 65002]  ← spine 转售时追加自己 AS
    Communities   : [target:65000:100, bgp-tunnel-encap:VXLAN]
  Path 1 was advertised to (Modified Attributes): [ 10.2.1.0 ]   ← L1 继续转售给 S2
```

L1 bridge MAC 表（本地 learnt + 远端 evpn，VTEP=远端 system IP）：

```
| 02:42:00:20:A4:00 | ethernet-1/3.0                        | learnt |
| 02:42:19:09:5B:00 | vxlan-interface:vxlan0.100 vtep:10.0.0.12 vni:100 | evpn |
| 02:42:67:4A:73:00 | vxlan-interface:vxlan0.100 vtep:10.0.0.13 vni:100 | evpn |
| 02:42:07:8A:0A:00 | vxlan-interface:vxlan0.100 vtep:10.0.0.14 vni:100 | evpn |
Total Learnt Macs : 1  Total Evpn Macs : 3
```

主机 ping（H1 三连发 + H2→H4 对角）：

```
--- 10.100.100.12 ping statistics --- 3 transmitted, 3 received, 0% loss, rtt min/avg/max = 1.077/2.821/6.084 ms
--- 10.100.100.13 ping statistics --- 3 transmitted, 3 received, 0% loss, rtt min/avg/max = 1.726/2.338/3.498 ms
--- 10.100.100.14 ping statistics --- 3 transmitted, 3 received, 0% loss, rtt min/avg/max = 0.801/1.531/2.977 ms
--- 10.100.100.14 ping statistics --- 3 transmitted, 3 received, 0% loss, rtt min/avg/max = 0.889/2.132/3.501 ms
```

## 7. 排障实录（按时间线，EVPN 从 [0/0/0] 到全通约 1 小时）

1. **underlay Est 但 Rx=0**（8/8 会话 established、ipv4 [0/0/0]）：查 L1 全表——只有 host/local 路由 + static anchor `route 10.0.0.11/32 ... active false`（被同前缀 host 路由 preference 0 压制），而 BGP 只导出 active 路由 → `match protocol static` 落空。修：statement 10 改纯 prefix 匹配（delete + 重建）。Rx 立即 4/4，跨脊 ping 通。
2. **overlay 首推两连语法错**：`type mac-vrf` 被拒（枚举 routed|bridged——v26 已改名）；`egress source-ip 10.0.0.11` 被拒（只接受 `use-system-ipv4-address`——VTEP 源必须是 system 地址）。引出 **system0 平移**：同 candidate 内 `delete /interface lo0 subinterface 0 ipv4 address` + 建 system0（分开两次 commit 会撞"subnet overlaps with lo0"重叠检查，同 candidate 原子过）。
3. **`subinterface ethernet-1/3.0 not found`**：上一步 commit 整体原子回滚，把 e1-3 bridged 子接口也带走，而补推配置里漏了它 → 全量重推（教训：SR Linux commit 失败 = 整块回滚，重推必须完整自包含）。
4. **evpn [0/0/0] 第一因——ebgp-default-policy**：`info from state` 实锤 v26 默认 `import-reject-all true / export-reject-all true`（ipv4 有显式 policy 所以没暴露，evpn AF 裸奔全拒）。6 台统一 false。仍 0。
5. **仍 0，盲试 advertise**：补 `inclusive-mcast advertise true` + `originating-ip`、查 evpn AF/bridge-table state 全正常、RIB（`show ... routes evpn route-type summary`）空——问题在"生成"不在"通告"。期间用 WebFetch 拉 [srl-labs/nokia-evpn-lab](https://github.com/srl-labs/nokia-evpn-lab) leaf1.cfg 对照，发现缺 **`bgp-vpn bgp-instance 1` + RD/RT**（官方标配，旧版"evi 自动推导 RD/RT"不成立）。
6. **L1 补 RD/RT 后 Tx=2，但 spine 只从 L1 收**（对 L2-L4 Rx=0）——L2-L4 还没补 RD/RT。补齐 4 台。
7. **Rx=4/Active=4 后 tunnel-table 仍 `<no_entries>`**：一度疑 NH 被改，type-3 detail 证实 NH=10.0.0.1X 无误；头端复制隧道本就不走 tunnel-table（ip-vrf 专属）——看 bridge-table 的 vtep 字段。**`ping network-instance VNI-100` 对 mac-vrf 直接报错**（"Must be an existing network namespace"），L2 NI 只能主机侧验证。H1 ping H2/H3/H4 全通。
8. **复盘定位第一因——host 载波**：事后读 `var/log/srlinux/file/messages` 发现 `networkInstanceInterfaceDown: ethernet-1/3.0 in VNI-100`（H_N eth0 未 up → e1-3 无载波 → 子接口 down → **bgp-instance 仍显示 oper up 但零路由生成**，最具迷惑性的一环）。host `ip link set eth0 up` 是 type-3 出现的直接前置。正确排障顺序应是：**先 host 载波 → 再 ebgp-default-policy → 再 RD/RT**。
9. **多租户改网段后 H4 重启不配 IP（我选了个非法地址）**：租户 C 网段我随手定了 10.100.300.0/24 —— **第三段 300 > 255，根本不是合法 IPv4**。症状极具误导性：文件内容 cat 看起来完全正确、busybox ifup 静默失败（eth0 起但无地址）、容器里手工跑 `ifup -a -f` 只报两条无上下文的 RTNETLINK 错误：
   ```
   ip addr add 10.100.300.14/24 dev eth0 label eth0
   Error: any valid prefix is expected rather than "10.100.300.14/24".
   ```
   用 `/gns3/bin/busybox ifup -v -f eth0` 拿到失败命令原文才定位（**注意运行时 PATH 无 ifup——init.sh 用 `PATH=/gns3/bin:/tmp/gns3/bin:/sbin:$PATH` 调 busybox applet，其中 `ip` 也会解析到 busybox 版而非 iproute2**，这本身就是排障时的环境差异来源）。改回合法地址（H4=10.100.3.14/24）后 stop/start 一次通过。

## 8. 坑与经验速查（v26，含旧版对照）

| # | 症状/要点 | 原因 | 处置 |
|---|---|---|---|
| 1 | bgp-instance oper up 但 EVPN 零路由、evpn [0/0/0] | mac-vrf 内接口 down（host eth0 未 up 无载波） | 主机先 `ip link set eth0 up`；日志看 messages 的 networkInstanceInterfaceDown |
| 2 | eBGP 某 AF Rx/Tx 恒 0（有会话） | v26 `ebgp-default-policy` 默认 import/export-reject-all=true | fabric 全局 false，或挂显式 policy |
| 3 | bgp-evpn 零输出（接口/AF 全正常） | 缺 `bgp-vpn bgp-instance` 的 rd + export-rt/import-rt | 按 N:VNI 与 target:AS:VNI 显式配 |
| 4 | lo static anchor 不被导出（Tx=0） | anchor 被 host 路由压制非 active；BGP 只导 active | export statement 纯 prefix 匹配 |
| 5 | `type mac-vrf` / `source-ip <ip>` 被拒 | v26 改 `type bridged|routed`、source-ip 仅 `use-system-ipv4-address` | VTEP 源配 system0（与 lo0 同 candidate 平移） |
| 6 | 无 ECMP（active-routes-with-ecmp 0） | v26 默认单路径 | `afi-safi ipv4-unicast multipath { ebgp { maximum-paths 4 } }` |
| 7 | commit 失败后补推仍缺东西 | 原子回滚带走整块 | 重推文件完整自包含 |
| 8 | show 报 usage/Unknown | `tunnels-table`✗（无 s）；`ping network-instance <mac-vrf>`✗；`info from state` 查 list 须带 key 或查父级 | `tunnel-table`；EVPN 路由 `show .../bgp routes evpn route-type {2|3|summary|detail}`；L2 用主机验证 |
| 9 | tree 报 Unknown token 'default' | tree 路径不能带 list key | `tree /network-instance protocols bgp multipath` ✓ |
| 10 | 头端复制隧道哪看 | tunnel-table 是 ip-vrf 的 routed VNI 概念 | `bridge-table mac-table`（vtep: 字段）+ multicast-destinations |
| 11 | host 重启后 eth0 无 IP，ifup 静默失败 | 网段写了非法 IPv4（如 10.100.300.x，八位组>255）；报错只有 "any valid prefix is expected" | 用 `/gns3/bin/busybox ifup -v -f eth0` 看失败命令原文；地址八位组必须 ≤255 |
| 12 | MAC/type-2 过几分钟消失 | learnt MAC 老化（默认 ~300s）后撤回 EVPN 通告 | 正常行为；打流量即重建，检查隔离时别把"表空"当故障 |

通用（承 skill/记忆）：一切协议/AF 显式 `admin-state enable`；neighbor 强制 peer-group；无 `;` 分隔；running 模式发配置静默无效；收尾 `commit save`（禁 save startup）；0.15-0.3s/line 推送；ws token 单次有效、URL 逐字节复制、输出禁接管道。

## 9. 与 DC-Test（XRd）/ FRR-SpineLeaf-Test 对照

| 维度 | XRd（DC-Test） | FRR（FRR-SpineLeaf） | **SR Linux v26（本项目）** |
|---|---|---|---|
| EVPN | ✗（control-plane 版无 NVE，降级 routed tenant） | 内核 VXLAN 手搓 VTEP | **原生 mac-vrf/bgp-evpn** |
| VTEP 源 | — | lo0 任意 | **必须 system0 地址**（枚举强制） |
| overlay 会话 | — | eBGP 双 AF | eBGP 双 AF（同会话 ipv4+evpn） |
| RR | — | spine 转售 | spine `route-reflector client true`，NH 不改 ✓ |
| 默认策略 | — | 需 ebgp-requires-policy 处理 | **ebgp-default-policy 双开关默认 true** |
| 载波依赖 | 无（routed 口） | 无（host down 不挡 vni 起来） | **mac-vrf 接口 down 则零 EVPN 路由** |
| RD/RT | — | vni 自动 | **必须 bgp-vpn 显式** |
| 主机 E2E | routed 互 ping | L2 over VXLAN ✓ | L2 over VXLAN ✓（0% 丢包） |

## 10. 快速重建 checklist

1. `project_create` → 批量 node_create（S1/S2/L1-L4 用 SRLinux 模板，H1-H4 用 Ubuntu Docker Guest）→ 批量 link_create（12 条）→ `node_start_all`，等 90s
2. 推 §4.1/§4.2 模板（已含全部修复项：ebgp-default-policy false、multipath、RD/RT、纯 prefix export）→ `commit save`
3. host 推 §4.3（eth0 up + IP）
4. 验证 5 条：`show /network-instance default protocols bgp neighbor`（8 会话双 AF）→ `info from state /network-instance default route-table ipv4-unicast statistics`（ecmp=3）→ `show ... routes evpn route-type 3 summary`（3 条远端）→ `show /network-instance VNI-100 bridge-table mac-table all`（evpn MAC 带 vtep）→ H1 `ping 10.100.100.12`（租户 A 内 0% 丢包）
5. 多租户：L3/L4 按 §4.2 末尾三件套加 VNI 200/300（改 vni/evi/RD/RT 号 + host 口移挂），host 改网段；验证"同租户通、跨租户 Network unreachable"
6. 全员 `commit save`；host 写 `/etc/network/interfaces`（address/netmask 分列、**地址必须是合法 IPv4**，busybox 不认 CIDR；运行时无 ifup，boot 时 /gns3/init.sh 应用）——首次仍需 `ip link set eth0 up` 拉载波
