---
name: 1000-frr-node
description: "1000-FRR-Node 项目 FRR(docker, FRR 10.3) full-mesh 双栈 OSPFv2/v3：6 节点原型→复制到 1002 节点/2505 链路；FRR 10.3 语法坑、ws 配置、link label 坑"
metadata: 
  node_type: memory
  type: project
  originSessionId: 137244e6-b2f8-4f75-a22a-01b8e8dd41e5
  modified: 2026-08-09T17:14:03.040Z
---

1000-FRR-Node（project_id `86c88244-cd8e-47aa-8ef3-eac3e439c61b`）：6 台 FRR docker（模板 `2fae8873-b194-4f1f-a306-c8a469e099a8`，镜像 FRRouting 10.3，console 5000~5005），**15 链路 full-mesh**（每节点 5 邻居，eth0~eth4），单 Area0，OSPFv2 + OSPFv3 双栈。2026-08-08 验证：双协议各 30 邻接全 FULL，非直连 loopback 双栈 ping 0 丢失。

**编址（沿用 [[100node-iou-ospf]] 规则）**：lo=`10.1.0.N/32`+`2026::N/128`；链路 R_A↔R_B=`10.1.AB.0/30`+`2026:AB::/64`，小号 `.1/::1`。接口映射（link_list 推导）：R1=eth0→2,eth1→4,eth2→5,eth3→3,eth4→6；R2=eth0→1,eth1→3,eth2→5,eth3→4,eth4→6；R3=eth0→2,eth1→6,eth2→5,eth3→1,eth4→4；R4=eth0→1,eth1→5,eth2→2,eth3→3,eth4→6；R5=eth0→6,eth1→4,eth2→2,eth3→1,eth4→3；R6=eth0→3,eth1→5,eth2→2,eth3→1,eth4→4。

**FRR 10.3 语法（与 8.x/9.x 不同，重要）**：
- **无 OSPF instance 模式**：`router ospf 1`/`ip ospf 1 area 0` 报 "instance not running" / "OSPF is not running in instance mode"；必须 `router ospf`（无 pid）+ `network 10.1.0.0/16 area 0` 语句，或接口 `ip ospf area 0`。
- `router ospf6` 仍存在（10.x 未合并），但块内 router-id 命令是 **`ospf6 router-id X`**，不是 `router-id`（后者被静默忽略，config 里块为空）。
- 接口启用 OSPFv3 仍是 `ipv6 ospf6 area 0` + 可选 `ipv6 ospf6 network point-to-point`；OSPFv2 接口 `ip ospf network point-to-point`。
- vtysh `ping` 无 source 参数：只有 `ping WORD|ip|ipv6`（`ping 10.1.0.6`、`ping 2026::6` 均可，自动按地址族）。**且 ping 不自动停止**（无限回包），验证流里 ping 后需补发 `\x03`（Ctrl+C）终止，否则会话卡住、websocat 挂满 timeout。
- 所有 6 台 `wr`（集成 config 写 /etc/frr/frr.conf）已持久化。

**Console 会话态坑（FRR docker 节点）**：容器主进程是 vtysh，**裸 `exit` 会退出 vtysh 掉到 bash**（`root@FRR-N:/#`），且断连可能让会话停在任意模式（见过 (config-if)#）。对策：**每条 ws 配置流开头固定发 `\x03` + `vtysh` + `end` 兜底**（已在 vtysh 则无害报错），结尾不发裸 exit。`show daemons`：mgmtd zebra ospfd ospf6d bgpd watchfrr staticd 全启。**ping 不自动停止且 ws 断开杀不掉**：容器侧 vtysh 里的 ping 会一直跑（实测断开 6 分钟后 icmp_seq 350+），必须 `\x03` (Ctrl+C) 手动终止，开头 `\x03` 顺带清残留。

**ws 用时坑**：websocat `-t --no-close` 在 stdin EOF 后不退出，墙钟时间 = timeout 值。**timeout 要贴输入时长**：验证 2~3 条命令（~6s 输入）用 `timeout 15`；50 条配置（~25s 输入）用 `timeout 40`。用户明确批评过 120s 的等待。

**node_file 工具对 docker 节点不可用**（404，仅 qemu/iou 节点目录支持）；配 FRR 只能走 ws console。

**复制到 1000 节点（2026-08-08）**：6 节点原型用 `replicate_mesh.py`（`mcp-manual-test/`，IOU 版同脚本，docker 同样适用——**docker 无 IOU application_id 512 上限**）复制成 **167 组 × 6 = 1002 节点 / 2505 链路**（FRRDockerLite-1~1002，全 stopped）。布局：组内正六边形（r=150，顶点 P1~P6 对应 R1~R6）、组间 16:9 矩形（步长 800×600，帧 ~12800×7200）；`--grid 16x11 --spacing 200 --origin=-6400,-3600`。**配置随复制携带**：`node_duplicate` 复制 `project-files/docker/{id}/etc/frr/frr.conf`（bind 卷），副本启动即自动加载 OSPF 配置，无需重推。所有副本带源节点 IP/router-id，但**各组之间无跨组链路、物理隔离（独立 L2 广播域），相同 IP 不冲突**——每组启动后独立运行 OSPF、互不干扰，不需要换编址。（曾误判"同时启动多组会 IP 冲突"，错——IP 冲突只在同一广播域内发生。）

**link label 坑（重要）**：`link_create` 的 `nodes` 若不带 `label` 字段，GNS3 自动生成 `"{adapter}/{port}"`（如 "4/0"）而非端口名 "eth4"——GUI 手画的链路才有 "ethX"。**斜杠前数字就是 eth 编号**（"4/0"=eth4），接线功能正确（adapter_number 才绑定容器 eth），仅显示难看。解法：建链时 `nodes` 用对象格式带 `{"label":{"text": f"eth{adapter_number}"}}`（紧凑 `[id,ad,pt]` 格式无法带 label）；已建的用 `link_update` 传 `kwargs={"nodes":[{...,label}]}` 批量修。批量修脚本 `mcp-manual-test/fix_link_labels.py`（限并发 20，跳过已正确，2489 条 0 失败）。`replicate_mesh.py` 的 create_links/repair_links 已改为带 label。

**UDP 端口范围**：本 fork 默认 `udp_start/end_port_range = 10000~30000`（20001 个，`gns3server/utils` port_manager）。每链路占 2 端口，1000 节点 ~5000 端口远未耗尽。批量建链（100 条/批）的 `Read timed out (30s)` 是客户端读超时——服务端实际已建成（实测 2490=166×15 一条不少），非端口枯竭（枯竭会直接 409 "No available port"）。

相关：[[gns3-ws-console-usage]]（ws 连接模板）、[[mark-test-ipv6]]（老 FRR 8.2.2 语法）、[[100node-iou-ospf]]（IOU 版同编址 + replicate_mesh 脚本参数）。
