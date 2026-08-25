# GNS3 MCP Node 模块工具专项复测报告（阶段 21）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 20 同一构建，project lock 修复版） |
| 测试范围 | Node 模块工具全量：节点本体 16 + 节点文件 4 = **20 个**（正常路径 + 错误路径 + 电源生命周期专项） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-node-test-0825`（VPCS×3 + IOU L3 + Alpine docker + 以太交换机，3 链路），测完已全部删除，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

> **2026-08-25 阶段 22 修复复测**：本报告的 N-1 / N-2① / N-2② / P2-2 已在上游修复并复测通过（VPCS/IOU suspend 改为诚实 405、批量按提交序返回、delete status 统一 "success"、node_file_get 字节保真），详见《阶段22_Node模块修复复测报告.md》。新发现 N-3（suspend_all 对已挂起 docker 节点 409 already-paused 上抛、非幂等）。

## 0. 环境备注

- **工具数量口径**：本轮会话 MCP 工具清单中 node 系共 **20 个**（阶段 19 同口径：节点 16 + node_file 4）。若按 22 计，差的 2 个不在当前 schema 中，待确认。
- 模板 22 个，与阶段 20 一致（MikroTik 误建模板清理后状态保持）。
- 测试拓扑：PC1/PC2/PC3（VPCS，PC3 为 PC1 复制体）、R-1（IOU L3）、AlpineLinux-1（docker）、Switch1（ethernet_switch）；3 条以太链路汇接 Switch1。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | node_list | 空项目基线 + fields 过滤 ×3 | ✓ | console 号、状态齐全；ethernet_switch console=null 符合类型特性 |
| 2 | node_create 单个 | VPCS（不传 name） | ✓ | 默认名 PC1，`default_name_format` 生效 |
| 3 | node_create 批量 | IOU+Alpine+ethsw+VPCS 4 节点 | ✓ | 逐项 status；**返回顺序与提交顺序不一致**（见 §3 N-2） |
| 4 | node_get | R-1 全量字段 + 假 UUID | ✓ | IOU 16 端口表（2 以太+2 串口适配器）、properties 含 md5sum；command_line 空系 stopped 所致；假 UUID 清晰 404 |
| 5 | node_update | 坐标 + console_auto_start | ✓ | 即时生效；返回全量节点详情（输出大，已知行为） |
| 6 | node_duplicate | stopped 复制 / running 复制 | ✓ | stopped→PC3（默认名、tags 与 console_auto_start 继承、新 console 5006）；running→409（已知约束复验成立） |
| 7 | node_start 单个/批量 | PC1 / 3 节点 | ✓ | 批量 3/3 逐项 success |
| 8 | node_start_all | 全量 | ✓ | 6/6 started（含 stopped 的 PC2 拉起） |
| 9 | node_suspend 单个 | VPCS / IOU | ⚠️ | 返回成功消息，但**状态不翻转为 suspended（仍 started）**——见 §2 状态矩阵 |
| 10 | node_suspend_all | 全量 | ⚠️ | 同上：仅 docker 节点翻转，VPCS/IOU/ethsw 保持 started |
| 11 | node_stop 单个 | PC2（挂起态之后） | ✓ | |
| 12 | node_stop_all | 全量 | ✓ | 5 个可停节点全 stopped；Switch1 保持 started（always-running 内建类型，符合设计） |
| 13 | node_console | 已启动 PC1 | ✓ | ws_url + 10 分钟 JWT + 现成 websocat 命令；含 `token_sha256_prefix` 便于对号 |
| 14 | node_links | Switch1（3 条）/ PC1（1 条） | ✓ | 含 suspend/markers/filters 字段 |
| 15 | node_isolate | PC1 | ✓ | 其链路 `suspend:true` 实测生效 |
| 16 | node_unisolate | PC1 | ✓ | `suspend` 复位 false |
| 17 | node_file_list | Alpine 节点目录 | ✓ | 含 `etc/` 目录与时间戳 |
| 18 | node_file_write | 中英混排文本 | ✓ | UTF-8 无损 |
| 19 | node_file_get | 读回 + offset/limit 分页 | ⚠️ | 内容正确、分页（offset=1/limit=1、truncated/has_more）正确；**P2-2 复现：returned_bytes(131)≠total_bytes(132) 仍差尾换行 1 字节，未修** |
| 20 | node_file_delete | 删测试文件 + 复读 | ✓ | 复读 404，报错含完整 API 路径 |

错误路径：node_get/node_start/node_delete 假 UUID 均清晰 404；node_duplicate 运行中节点 409；node_file_get 读已删文件 404。

## 2. 电源生命周期状态矩阵（专项观察）

| 节点类型 | start 后 | suspend 后状态 | stop 后 |
|---|---|---|---|
| VPCS | started | **仍 started**（消息报成功） | stopped ✓ |
| IOU L3 | started | **仍 started**（消息报成功） | stopped ✓ |
| docker（Alpine） | started | **suspended ✓（唯一翻转的类型）** | stopped ✓（可从 suspended 直接停） |
| ethernet_switch | started（天生） | 仍 started | 不可停（always-running，符合设计） |

- **无 `node_resume` 工具**：恢复挂起用 `node_start`（IOU 上验证成功）。
- 结论：suspend 的"是否生效"对 VPCS/IOU **通过 MCP 状态查询不可见**（要么静默 no-op、要么不上报，API 层无法区分）。依赖挂起语义的自动化应只对 docker（及 qemu 系）节点使用，或改用 isolate/stop。

## 3. 问题汇总

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| N-1（阶段 21 新发现） | 中 | suspend/suspend_all 对 VPCS、IOU 返回成功但节点状态不翻转（仅 docker 翻转 suspended），挂起效果经 MCP 不可观测；阶段 19 仅验证了调用链成功，未查状态，故未暴露 | node_suspend / node_suspend_all |
| N-2（口径） | 低 | ① 批量接口（node_create、link_create）返回顺序与提交顺序不一致（并行执行），按下标配对会错位；② 批量 node_delete 逐项 status 用 `"deleted"`，与 create/start 的 `"success"` 口径不一致 | node_create / node_delete / link_create |
| P2-2（复现，未修） | 低 | node_file_get 字节计数差 1（尾换行）：returned_bytes 131 vs total_bytes 132 | node_file_get |

## 4. 统计

- 实测工具：**20 / 20**（节点 16 + 节点文件 4，当前会话工具清单口径）
- 通过：17 · 通过带注意点：3（node_suspend / node_suspend_all / node_file_get）
- 新发现问题：N-1（suspend 状态不透明）、N-2（批量顺序与 status 口径）；已知 P2-2 复现未修
- 正向复验：默认命名、tags 继承、运行中复制 409、isolate/unisolate 链路 suspend 翻转、"4/0" 端口标签 bug 未复现、ethsw always-running
- 测试痕迹：6 节点 + 3 链路 + 测试文件全部清理，项目已删，终态 `project_list` count=0
