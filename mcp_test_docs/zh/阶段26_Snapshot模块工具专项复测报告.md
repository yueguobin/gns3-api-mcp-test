# GNS3 MCP Snapshot 模块工具专项复测报告（阶段 26）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 25 同一构建，未重启） |
| 测试范围 | Snapshot 模块工具全量：**4 个**（create / list / restore / delete），正常路径 + 错误路径 + **恢复回滚完整性验证**（拓扑/链路/绘图/节点文件四类状态变更后恢复） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-snap-test-0825`（2×VPCS + ethsw + 2 链路 + 1 绘图 + PC1 存档配置），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 0. 环境备注

- 工具数量口径：**4 个，与用户口径一致**（create / list / restore / delete）。
- 起始/终态 `project_list` count=0，模板基线 22 个（未触碰），与环境基线一致。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | snapshot_create 错误·前置违规 | PC1 处于 started 状态直接建快照 | ✓ | 409 "Project must be stopped in order to export it"，前置校验生效（**文案说 "project"，实义为"所有可停节点须停止"，见 S-1**） |
| 2 | snapshot_create 正常 | node_stop_all 后建 `snap-1` | ✓ | 返回 snapshot_id/文件名 `snap-1.gns3snapshot`/created_at；**自动生成描述** "Snapshot 'snap-1' taken on 2026-08-25 at 15:04:55" |
| 3 | snapshot_create 错误·重名 | 再建 `snap-1` | ✓ | 409 "The snapshot name snap-1 already exists" |
| 4 | snapshot_list | 单快照 | ✓ | name/description/snapshot_id/filename/created_at 齐全，count 一致 |
| 5 | 变异操作（恢复前奏） | 删原 PC2（链路级联消失）→ 建新 PC2（默认名回填复用 "PC2"）→ 绘图挪至 (500,500) → PC1 节点目录写入 `mutation-marker.txt` | ✓ | 变异态留证：3 节点/1 链路/绘图新位置/标记文件在列 |
| 6 | **snapshot_restore 正常** | 恢复 `snap-1` | ✓ | 返回全量项目详情，**项目自动重开**（status=opened） |
| 7 | 恢复核对·节点 | | ✓ | **原 PC2 按 同 node_id（e0dc2bf6…）完整复原**于原坐标 (200,0)；变异 PC2（b96c62e7…）消失；PC1/Switch1 原样（stopped/started） |
| 8 | 恢复核对·链路 | | ✓ | 级联删除的链路 b9791ff3 复原，2/2 |
| 9 | 恢复核对·绘图 | | ✓ | 挪动过的矩形回滚到原位 (-100,150)，SVG 内容不变 |
| 10 | 恢复核对·节点文件 | | ✓ | **`mutation-marker.txt` 被清除**（快照后写入的文件不残留）；`startup.vpc` 内容保真（`set pcname PC1` + `ip 10.0.0.1 24`，30/30 字节——P2-2 修复口径持续成立） |
| 11 | snapshot_restore 错误 | 假 UUID | ✓ | 404 "Snapshot ID … doesn't exist"，已知包裹风格 |
| 12 | snapshot_delete 错误 | 假 UUID | ✓ | 404 同上 |
| 13 | 多快照管理 | 建 `snap-2` → list ×2 → 删 `snap-1` → list | ✓ | 双快照按创建时间排序、created_at 单调；**restore 不清空快照列表**（恢复后 snap-1 仍可再恢复/删除）；删除后仅剩 snap-2 |
| 14 | 终态核对 | 项目删除 → project_list | ✓ | count=0，快照随项目级联清理 |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **S-1（阶段 26 新发现，观察项）** | 低 | `snapshot_create` 前置校验的报错文案为 "Project must be stopped in order to export it"——**主语是 "project"，但实际校验的是"所有可停节点须停止"**（本项目中 always-running 的 ethsw 处于 started 并不阻挡建快照，行为正确）。文案与实义有偏差，易让调用方误以为需要 project_close | snapshot_create |

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| 阶段 19 Snapshot 4 工具结论（全 ✓） | **全部复验成立**；本轮额外补齐：前置违规/重名/假 UUID 三类错误路径 + 恢复回滚完整性验证（阶段 19 仅核对"6 节点/链路完整恢复"） |
| P2-2（node_file_get 字节保真，已修） | 恢复后回读 startup.vpc 30/30 字节，**持续成立** |
| 报错风格（"Unknown Status … Original xxx" 包裹） | restore/delete 假 UUID 均此风格，维持不变 |

## 4. 统计

- 实测工具：**4 / 4**（14 个场景）
- 通过：4 · 新发现：S-1（前置校验文案主语与实义偏差，观察项）；**无新服务器缺陷**
- 增强验证：恢复回滚四维核对（节点含 **node_id 稳定性** / 链路 / 绘图 / 节点文件含越权文件清除 + 配置内容保真），较阶段 19 的恢复验证升级
- 语义定论：① 恢复后项目自动重开、节点全部 stopped；② **node_id 跨恢复保持稳定**（同拓扑位同 id，自动化可按 id 关联）；③ restore 不影响快照列表（可反复恢复）；④ 快照后新写入的节点文件会被回滚清除
- 测试痕迹：临时项目（3 节点 + 2 链路 + 1 绘图 + 2 快照）整体删除，终态 `project_list` count=0
