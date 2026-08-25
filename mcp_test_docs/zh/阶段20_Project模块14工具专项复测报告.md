# GNS3 MCP Project 模块 14 工具专项复测报告（阶段 20）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（当日 project lock 修复 + MCP schema 更新后，`/mcp` 重连复测） |
| 测试范围 | Project 模块 **14 个工具**全量（正常路径 + 错误路径 + lock 四象限专项） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-proj-test-0825b` / `mcp-lock-test-0825`，测完已全部删除，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✅ 符合设计 · 已知遗留 |

## 0. 环境备注

- 本轮开局 `project_list` count=0：系 08-25 事故（阶段 19 P0-1，projects 根目录被 rmtree）的损害结果，用户已确认；僵尸条目 `mcp-regress-loadtest`（0d8f1a5e-…-0001）未再出现在列表中。
- 服务器更新切换期间（`/mcp` 重连前）`project_list` 一度报 `MCP error -32602: Invalid request parameters`（无参调用被新 schema 拒绝）；重连后恢复正常。属切换窗口现象，非稳定缺陷。
- `project_load` 已不在 MCP 工具清单中（阶段 19 为 15 个，本轮 14 个）——P0-1 地雷组合（`project_load` + `project_delete`）从 MCP 层面消失。
- 模板 22 个：阶段 19 遗留的 2 个误建 MikroTik 模板已由用户手工清理。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | project_list | 基线 / 收尾 ×3 | ✓ | count=0 与环境状态一致（见环境备注） |
| 2 | project_create | 建临时项目 ×2 | ✓ | path 为独立子目录、auto_close=false、创建即 opened |
| 3 | project_get | 详情 + 假 UUID | ✓ | 字段完整；404 报错信息清晰 |
| 4 | project_stats | 空项目统计 | ✓ | nodes/links/drawings/snapshots/markers 五项计数 |
| 5 | project_update | zoom=150 + show_grid=true | ✓ | 即时生效；close→open 周期后保留 |
| 6 | project_readme_update | 写中文 README | ✓ | 落 README.txt |
| 7 | project_readme_get | 读回 | ✓ | 中英混排往返无损 |
| 8 | project_close | 关闭 | ✓ | |
| 9 | project_open | 重开 | ✓ | |
| 10 | project_lock | opened 加锁 / closed 加锁 | ⚠️ | opened ✓（四象限复测通过，见 §2）；closed 状态返回裸 403 文本（"Unknown Status…Original 403"）——**已知遗留，维持原样（用户确认）** |
| 11 | project_locked | 加锁前 / 加锁后 / 解锁后查询 ×7 | ✓ | 修复后状态翻转正确（见 §2）；空项目恒 false 符合设计 |
| 12 | project_unlock | 解锁 ×4 | ✓ | 修复后复测通过；曾发现"返回成功但状态不翻转"缺陷（当日修复，见 §3） |
| 13 | project_duplicate | 复制 + 假 UUID | ✓ | 副本 status=closed、属性（zoom/show_grid）继承；404 清晰 |
| 14 | project_delete | 删副本 + 本体 + 假 UUID | ✓ | 均干净删除（终态 count=0）；404 清晰 |

## 2. Lock 四象限专项（修复验证）

测试项目 `mcp-lock-test-0825`，锁定拦截用例覆盖 update / delete 双路径：

| 象限 | 场景 | lock → locked | unlock → locked | 编辑（update） | 删除（delete） |
|---|---|---|---|---|---|
| Q1 | 空项目（0 节点 0 绘图） | 成功消息，locked=false | false | — | — |
| Q2 | 仅绘图 ×1 | true ✓ | false ✓ | drawing_update **放行** | drawing_delete **409 拦截** ✓ |
| Q3 | 仅节点 ×1（VPCS） | true ✓ | false ✓ | — | — |
| Q4 | 节点 + 绘图 | true ✓ | false ✓ | node_update **放行**（节点 locked:true 可见） | node_delete **409 拦截** ✓ |

### 语义定论

1. **lock 是逐项锁**：`project_lock/unlock` 遍历所有节点+绘图，逐项置位/复位对象级 `locked` 标志；`project_locked` 为聚合查询。加锁时 `drawing_get`/`node_update` 返回中可见对象 `locked:true`，解锁同步复位。
2. **空项目无事可锁，恒报 false**：修复在 `controller/project.py` 的 `locked` 属性加了空集守卫（无 drawings 且无 nodes 直接 return False）。修复前走 vacuous-True → 永远报 true 且解不开（即本轮发现的缺陷，同一根因）。Q1 行为 ✅ 符合设计。
3. **locked 是删除保护，不是编辑保护**：锁定下 `node_update` / `drawing_update`（含挪坐标）全部放行；仅 `node_delete` / `drawing_delete` 被 409 拦截。与工具描述 "prevent accidental changes" 有偏差——实际防删/防 GUI 拖动，不防 API 修改属性。

### 回归套件口径（用户确认）

- 方向性断言（lock→true / unlock→false）：项目里至少放 1 个 node 或 drawing。
- 空项目用例：断言 `locked` 恒 false，lock/unlock 仅断言返回成功。

## 3. 当日发现并修复的缺陷

| 编号 | 级别 | 问题 | 状态 |
|---|---|---|---|
| P1-3 | 高 | 空项目 `project_lock` 后 `locked` 恒 true，`project_unlock` 返回成功消息但状态不翻转（vacuous-True 根因；两轮复现） | **当日已修复**（空集守卫）并四象限复测通过 |

## 4. 已知遗留（维持原样）

| 项 | 表现 | 处置 |
|---|---|---|
| closed 状态调 `project_lock` | 返回裸 403 文本（"Unknown Status: The project is not opened (Original 403 Error)"），信息生硬 | 用户确认维持原样，不再跟进 |

## 5. 统计

- 实测工具：**14 / 14**（project 模块全部；`project_load` 已从工具清单移除）
- 通过：13 · 已知遗留：1（project_lock 的 closed 态文案）
- 当日缺陷：发现 1（P1-3）→ 修复 → 复测通过
- 测试痕迹：2 个临时项目及全部节点/绘图已删除，终态 `project_list` count=0
