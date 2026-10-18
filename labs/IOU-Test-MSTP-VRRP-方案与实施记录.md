# IOU-Test MSTP + VRRP 方案与实施记录（2026-08-31）

项目：iou-test（7699c7cd-5813-466c-8582-247e497868f5），7 节点 / 9 链路。
场景：接入层双上联核心，MSTP 按实例负载分担 + VRRP 双活网关 + 双出口 OSPF。
全部实施与验证于 08-31 一次完成，基线与三灾演练均通过。

## 拓扑与端口映射

```
                ┌──────────┐
                │ IOU-R-1  │  Lo0 10.255.255.254/32 · Lo1 203.0.113.1/32（模拟外网）
                └─┬─────┬──┘
          10.0.12.0/30  10.0.22.0/30（routed，OSPF area 0）
              e0/2│       │e0/2
          ┌────────┐ e0/1─e0/1 ┌────────┐
          │IOU-SW-1│═══════════│IOU-SW-2│  ← 核心 trunk（VRRP 心跳命脉）
          └┬─────┬─┘           └─┬────┬─┘
       e0/0│  e0/3│          e0/3│  e0/0│
      ┌─────┴──┐ ┌─┴────────┐ ┌─┴──────┴┐
      │IOU-SW-3│ │IOU-SW-4  │ │（SW1↔SW3、SW1↔SW4、SW2↔SW3、SW2↔SW4 全交叉）
      └────────┘ └──────────┘
       e0/2↑              ↑e0/2
   UbuntuGuest-1      UbuntuGuest-2
   10.1.10.101/24     10.1.20.101/24
```

| 链路 | 端口 | 角色 |
|---|---|---|
| SW1 e0/0—SW3 e0/0、SW1 e0/3—SW4 e0/1 | 接入上联 | trunk |
| SW2 e0/3—SW3 e0/1、SW2 e0/0—SW4 e0/0 | 接入上联 | trunk |
| SW1 e0/1—SW2 e0/1 | 核心互联 | trunk（**必须**：instance 阻塞在接入侧，被阻 VLAN 的 VRRP hello 只能走这条） |
| SW1 e0/2—R1 e0/0 | 出口 L3 | 10.0.12.1↔10.0.12.2 /30 |
| SW2 e0/2—R1 e0/1 | 出口 L3 | 10.0.22.1↔10.0.22.2 /30 |
| SW3 e0/2—Guest-1、SW4 e0/2—Guest-2 | 主机接入 | access vlan 10/20 + portfast |

## 编址与 VRRP

| VLAN | 网段 | VIP | SW1 SVI | SW2 SVI | VRRP 主 |
|---|---|---|---|---|---|
| 10 USR-A | 10.1.10.0/24 | 10.1.10.254 | 10.1.10.2（pri 110） | 10.1.10.3 | SW1 |
| 20 USR-B | 10.1.20.0/24 | 10.1.20.254 | 10.1.20.3 | 10.1.20.2（pri 110） | SW2 |

Loopback：SW1=10.255.255.1、SW2=10.255.255.2、R1=10.255.255.254（均 /32，router-id）。

## MST 域

- name `GNS3` / revision 1，四台交换机一致（R1 不参与）
- **instance 1 = VLAN 10，instance 2 = VLAN 20**，其余在 IST(0)
- SW1：mst1 priority 4096（根）、mst2 8192；SW2 镜像（mst2 4096、mst1 8192）
- VRRP 主与 instance 根同侧绑定 → 网关与二层路径同故障域

收敛后实测端口角色（与设计一致）：

| 设备 | inst1 (VLAN10, 根 SW1) | inst2 (VLAN20, 根 SW2) |
|---|---|---|
| SW3 | e0/0 RP / **e0/1 BLK** | e0/1 RP / **e0/0 BLK** |
| SW4 | e0/1 RP / **e0/0 BLK** | e0/0 RP / **e0/1 BLK** |
| SW1 | 全 Desg | e0/1 RP |
| SW2 | e0/1 RP | 全 Desg |

## 路由

- SW1/SW2 `ip routing`，e0/2 `no switchport` 三层口；R1 双 transit，全网 OSPF area 0
- SW1/SW2 经 `network` 宣告两个 VLAN 网段（SW1↔SW2 经 Vlan10/Vlan20 SVI 亦有邻接，天然冗余）
- R1：`ip route 0.0.0.0 0.0.0.0 Null0` + `default-information originate`
- 基线实测：PC1 出口走 SW1（traceroute 10.1.10.2→10.0.12.2），PC2 走 SW2（10.1.20.2→10.0.22.2）

## 配置全文

### IOU-SW-1（SW2 镜像对称）
```
spanning-tree mode mst
spanning-tree mst configuration
 name GNS3
 revision 1
 instance 1 vlan 10
 instance 2 vlan 20
spanning-tree mst 1 priority 4096
spanning-tree mst 2 priority 8192
vlan 10
 name USR-A
vlan 20
 name USR-B
ip routing
interface range Ethernet0/0,Ethernet0/1,Ethernet0/3
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk allowed vlan 10,20
interface Ethernet0/2
 no switchport
 ip address 10.0.12.1 255.255.255.252
interface Loopback0
 ip address 10.255.255.1 255.255.255.255
interface Vlan10
 ip address 10.1.10.2 255.255.255.0
 vrrp 10 ip 10.1.10.254
 vrrp 10 priority 110
interface Vlan20
 ip address 10.1.20.3 255.255.255.0
 vrrp 20 ip 10.1.20.254
router ospf 1
 router-id 10.255.255.1
 network 10.0.12.0 0.0.0.3 area 0
 network 10.1.10.0 0.0.0.255 area 0
 network 10.1.20.0 0.0.0.255 area 0
 network 10.255.255.1 0.0.0.0 area 0
```

### IOU-SW-3 / IOU-SW-4（纯二层）
```
spanning-tree mode mst
spanning-tree mst configuration
 name GNS3
 revision 1
 instance 1 vlan 10
 instance 2 vlan 20
vlan 10 / vlan 20（同上）
interface range Ethernet0/0-1
 switchport trunk encapsulation dot1q
 switchport mode trunk
 switchport trunk allowed vlan 10,20
interface Ethernet0/2
 switchport mode access
 switchport access vlan 10|20
 spanning-tree portfast
```

### IOU-R-1
```
interface Ethernet0/0
 ip address 10.0.12.2 255.255.255.252
interface Ethernet0/1
 ip address 10.0.22.2 255.255.255.252
interface Loopback0
 ip address 10.255.255.254 255.255.255.255
interface Loopback1
 ip address 203.0.113.1 255.255.255.255
router ospf 1
 router-id 10.255.255.254
 network 10.0.12.0 0.0.0.3 area 0
 network 10.0.22.0 0.0.0.3 area 0
 network 10.255.255.254 0.0.0.0 area 0
 default-information originate
ip route 0.0.0.0 0.0.0.0 Null0
```

### Ubuntu 客户端（Ubuntu Docker Guest 模板）
`/etc/network/interfaces`（busybox 不认 CIDR，address/netmask 分列）——**启动时自动加载，持久化有效**（09-12 DC-Test 重启实证）；运行态 `ip addr add` / `ip route add` 仅用于不重启热生效。

## 验证与演练结果（2026-08-31 实测）

| 项 | 结果 |
|---|---|
| MST 域/端口角色 | 与设计表逐项一致（上图） |
| VRRP | SW1 grp10 Master / SW2 grp20 Master，Master addr 指向各自实体 IP |
| OSPF | R1 双邻居 FULL；两 VLAN 网段 ECMP；SW1↔SW2 SVI 邻接 FULL ×2 |
| 双 PC 数据面 | ping VIP 4/4、ping 203.0.113.1 4/4；traceroute 路径分侧 |
| **演练 1** shut SW3 e0/0（L2 上联） | 170/170 **0% 丢包**，MST 毫秒级切换 |
| **演练 2** shut SW2 Vlan20（网关切换） | 复跑：外网流 250/250 0%，VIP 流 98/100（丢 2，≈0.6–1s）；traceroute 三连拍路径 SW2→SW1 可见；恢复后 preempt 回切 |
| **演练 3** shut SW1 e0/2（出口切换） | 249/250 仅丢 1 包；SW1 默认路由即时改经 Vlan10/Vlan20→SW2；traceroute 10.1.10.2→10.1.20.2→10.0.22.2 |
| 恢复 | VRRP 主备、OSPF 邻接、ECMP 全部回到基线 |

VRRP 快速切换机理：master 的 SVI 被 shut 时发 priority-0 通告，backup 按 skew=(256-pri)/256（pri100≈0.61s）立即接管，不必等 3.6s master-down。

## 坑与备忘

1. **首切黑洞异常（未复现）**：演练 2 首跑出现 ~11s 黑洞——SW1 已 Master（syslog 证实 +0.61s 接管）但 PC2 全丢。复跑（双 ping 流+traceroute 探针）干净。期间观察到 SW1 VLAN20 MAC 表中 vMAC `0000.5e00.0114` 为 DYNAMIC 学自 Et0/1（新 master 未本地化 vMAC 表项），复跑时同表项存在却无影响。定性为 ioul2 镜像 VRRP 首次切换的 gARP/CAM 竞态，非确定性问题，留意即可。
2. **Ubuntu Docker Guest 无 ifup/ifdown 命令**，但**启动流程会自动加载 `/etc/network/interfaces`**（08-31 当时误判为"仅存档、重启必须重推"；09-12 在 DC-Test 以 busybox 分列语法写文件 + node 重启实证：IP/默认路由自动恢复）。运行态改 IP 才用 `ip addr add`/`ip route add`。
3. **docker 节点 console 禁止发 `exit`**：console 挂的主进程 bash，exit 即杀容器会话（本次踩过，node_stop→node_start 恢复）。会话结尾用 echo 标记行，靠 timeout 断开。
4. **MCP 工具链延迟 10–20s/跳**：故障演练的时间轴不能靠「工具返回即生效」排程，客户端侧一律用 base64 写入的自计时脚本（nohup 后台双 ping+定时 traceroute），事件对齐靠设备 syslog 时间戳。
5. 核心 trunk（SW1↔SW2）是本设计命门：缺了它，被阻 instance 侧的 VRRP backup 收不到 hello 会双主。
