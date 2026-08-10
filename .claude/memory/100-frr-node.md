---
name: 100-frr-node
description: "100-FRR-Node 项目：17 组六边形 full-mesh FRR(docker, FRRDockerLite 模板)=102 节点/255 链路；link_reset 修 uBridge 不通、ping 矩阵验证、.venv 跑 replicate_mesh"
metadata: 
  node_type: memory
  type: project
  originSessionId: d236e8af-7eec-496e-8330-2ef9c24f362a
  modified: 2026-08-10T06:22:04.372Z
---

100-FRR-Node（project_id `61957ccd-faeb-41fa-8fa7-821c4033bdc4`，模板 **FRRDockerLite `63e5a176-afe7-4618-8884-4ea57f79e38b`**，镜像 gns3/frr:latest，8 网卡）：17 组正六边形 full-mesh（源 + 16 副本）= **102 节点 / 255 链路**，全 stopped。2026-08-10 完成。

**结构**：源 mesh 6 节点（FRRDockerLite-1~6，正六边形 r=150），15 链路 full-mesh（eth0~4，带 label）。OSPFv2/v3 双栈配置（编址同 [[1000-frr-node]]：lo=`10.1.0.N/32`+`2026::N/128`，链路 `10.1.AB.0/30`+`2026:AB::/64`，FRR 10.x 无 instance 语法）。**源组 ping 矩阵验证：6 节点 × 5 目标 × 双栈 = 60 ping 全通**。然后 `node_stop_all` → `replicate_mesh.py --grid 4x4 --origin=1000,-1200 --spacing 200` 复制 16 副本（FRRDockerLite-7~102）+ 240 链路。

**新教训（vs [[1000-frr-node]]）**：
1. **link_reset 修复 uBridge 不通**：链路在 stopped 节点间 link_create + node_start 后，**部分链路 GNS3 记录正确但 uBridge 数据平面没通**（直连 ping 100% loss，OSPF 邻接 Init/缺失，路由绕行 cost=20）。`link_reset` 全部 15 条（重建 UDP 连接）后修复，直连 ping 0% loss。排查路径：link_list 确认两端 adapter 对接正确 + running-config 确认 IP/OSPF 正确 → 指向数据平面 → 用 **ping 直连接口地址**（不是邻居表）定位哪条链路断。
2. **ping 矩阵 > OSPF 邻居表计数**：ws 查 `show ip ospf neighbor` 时，**timeout 截断输出导致 grep 'Full' 计数偏低**（假象，显示 1~2 而实际 5 个 Full）。验证端到端连通用 **ping 矩阵**（每节点 ping 其他所有节点 lo，v4+v6）最可靠——60 ping 0 不可达 = 全网通。别再纠结邻居表 Full 计数。ws 查邻居表也要长 timeout（≥15s）+ sleep，否则截断。
3. **replicate_mesh.py 用项目 .venv**：脚本 `from mcp import ClientSession`，系统 `/usr/bin/python3` 无 mcp 包；用 `/home/yueguobin/myCode/GNS3/gns3-api-mcp-test/.venv/bin/python` 跑（项目 venv 含 mcp，python3.13）。

**副本 IP 不冲突（曾误判，已纠正）**：node_duplicate 复制 frr.conf，16 副本带源组相同 IP/router-id。但 **17 组之间无跨组链路、物理隔离**（各自独立 L2 广播域），相同 IP **不冲突**——每组启动后独立运行 full-mesh OSPF，互不干扰，**不需要换编址**。IP 冲突只在同一广播域内发生；曾误以为"同时启动多组会冲突"，错（[[1000-frr-node]] 同款误判已纠正）。

**500-FRR-Node-temp 扩展（2026-08-10）**：project_id `c509e934-2a47-4c58-93f2-9fa2d7c1fc9e`，从 100-FRR-Node-temp 复制（102 节点/255 链路，17 组）。用 `replicate_mesh.py --grid 12x7 --skip-existing --origin=1000,-1200 --spacing 200` 扩到 **510 节点/1275 链路（85 组）**——16 个已有副本位置 skipped、68 个新副本（网格化扩组就用 `--skip-existing` 同 origin 大 grid 补缺）。3 条链路报 Read timeout 是客户端超时假象（stats 1275=85×15 一条不少）。扩展法可复用到 1000+。

相关：[[1000-frr-node]]（同套路老模板 2fae8873）、[[node-naming-use-default]]（建节点不传 name，沿用 FRRDockerLite-{N}）、[[gns3-ws-console-usage]]、[[gns3-mcp-double-envelope]]。
