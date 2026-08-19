---
name: srlinux-v26-gns3
description: Nokia SR Linux v26.7.1 (GNS3 docker 模板) 的语法/加固默认值/静默坑清单——admin-state 显式 enable、nexthop ip-address、transport local-address、OSPF export 无效等
metadata: 
  node_type: memory
  type: project
  originSessionId: 26925966-39a5-4879-91ca-d19104aeba3a
  modified: 2026-08-19T16:49:09.180Z
---

GNS3 docker 模板 `ghcr.io/nokia/srlinux:latest`（实测 v26.7.1-554，模板 usage 说明有错处）。console_type=docker_exec，直接落 sr_cli（`A:root@srlinux#`）。与 FRR/XRd 完全不同的模型，坑极多（2026-08-19 十组联调实证）：

**Why:** v26 大量"加固默认值"（协议默认 disable、AF 默认不启用）+ CLI 语义怪癖（空大括号 no-op、列表关键字顺序），照 IOS/FRR/XR 经验写配置会静默失败。

**How to apply:**
- **console 姿势**：docker_exec 是**持久流**，残留输入下轮 attach 才被消化（每轮开头 `\r\n` 唤醒+核对提示符）；CLI 300s idle 自动登出（会话自然重启）；`show` 是**相对当前上下文**的，深处上下文用 `show /network-instance ...` 绝对路径最稳，读状态优先 `info from state /network-instance default route-table`（route-table 无 show 家族后缀）。`tree /network-instance <容器>` 渲染 schema（不写 list key）。**发现子项用错 token 报错枚举**（完整列表）；`?` 帮助会截断且"press '?' again"状态吞后续命令，别连发。
- **paste 竞态**：连续同叶子列表行（如一接口两个 ipv6 address）会被吞/错位，0.15s/行送大块 + 关键叶子改单行 path 命令补。
- **admin-state 三连（v26 默认全 disable）**：① ospf instance 要 `admin-state enable`（否则接口面板 Adm Up/Oper Down、Tx Hello=0、邻居空）；② bgp 全局+每个 group 的 `afi-safi ipv4-unicast`/`ipv6-unicast` 都要 `admin-state enable`；③ neighbor **强制挂 peer-group**（`group ebgp-rs { peer-as ... }` + `neighbor X { peer-group ebgp-rs }`）。
- **OSPF**：`protocols/ospf/instance <名> { version ospf-v2|ospf-v3 }`；v3 必须 `address-family ipv6-unicast`，v2 **不许**配 address-family；接口引用 `ethernet-1/N.0`；transit 口要 `advertise-subnet true`（默认只通告 /32）；环回=lo0.0（`passive true`）。
- **静态路由（v26 无 `next-hop discard`）**：`next-hop-groups group BH { blackhole { } }`（Null0 等价）+ `static-routes route <pfx> { next-hop-group BH }`；**nexthop 条目必须带 ip-address 子叶**（`nexthop 1 { ip-address 10.x.x.x }`）——空 `{ }` 是 no-op，组空 → 静默黑洞（ping 超时≠路由在转发）。
- **BGP**：顶层 `import-policy [ 名 ]`/`export-policy [ 名 ]` 是**列表语法**；**v6 多地址源选择坑**：上联口同时有 2026::N 和 2026:254:254::N 时源选错 → 对端 RS 拒收（v6 会话 connect/active 徘环但 ping 通）→ `neighbor <v6> transport local-address 2026:254:254::N` 显式钉住。
- **routing-policy**：`/routing-policy prefix-set X { prefix 0.0.0.0/0 mask-length-range exact { } }`；match 里写法是 **`prefix prefix-set <名>`**（prefix 是引导词）+ `protocol static|bgp`；`action`/`default-action` 里 `policy-result accept|reject`。
- **OSPF export-policy 对 static 实测无效**（Type-5 恒 0，全收策略也 0；`table-connections` 的 destination-protocol 值域只有 bgp|gribi|isis|local|static，根本不含 ospf）→ 组内默认路由改用**内部节点静态 ECMP**（next-hop-groups 双边界 nexthop）替代 default-information originate。
- ping 是 Linux 风格：`ping network-instance default <ip> -c 3 [-I 源] [-t ttl]`；持久化=**`save startup`**（写 /etc/opt/srlinux/config.json；模板 usage 写的 `save config` 不存在）。改配置 `enter candidate private` + `commit now`（原子，错一处全不生效）。

参见 [[bgp-rr-dual-stack]]（⑨组部署）、[[gns3-ws-console-usage]]。
