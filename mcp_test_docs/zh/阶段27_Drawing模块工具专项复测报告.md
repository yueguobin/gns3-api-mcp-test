# GNS3 MCP Drawing 模块工具专项复测报告（阶段 27）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 26 同一构建，未重启） |
| 测试范围 | Drawing 模块工具全量：**5 个**（create / list / get / update / delete），正常路径 + 错误路径 + **SVG 内容保真验证**（中文/特殊字符往返、四种形状）+ **条目级 locked 语义复验**（删除保护 vs 编辑放行） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-draw-test-0825`（无节点，纯绘图：矩形/中文文本/椭圆/虚线直线 + 1 个非法 SVG 清洗项），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 0. 环境备注

- 工具数量口径：**5 个，与用户口径一致**（create / list / get / update / delete）。
- 起始/终态 `project_list` count=0，模板基线 22 个（未触碰），与环境基线一致。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | drawing_create 正常·四种形状 | 实心矩形（`#4A90D9`）/ 文本标签 / 椭圆（空心描边）/ 虚线直线（`stroke-dasharray`） | ✓ | 均返回 drawing_id + 全量字段；**SVG 内容逐字回显**；默认值 z=0 / locked=false / rotation=0 |
| 2 | drawing_create 错误·假 project UUID | | ✓ | 404 包裹风格（"Unknown Status … Original 404"），已知风格 |
| 3 | drawing_create 非法 SVG | `svg="plain text, definitely not SVG <>&\" quotes"` | ⚠️ | **不报错：静默创建成功，但内容被替换为空 `<svg></svg>`**（原始字符串丢弃，见 D-1）；list/get 复核确认落盘的就是空 SVG |
| 4 | drawing_list | 5 个绘图（4 有效 + 1 清洗项） | ✓ | count=5 与明细一致；全量字段（含 svg/rotation/z/locked） |
| 5 | drawing_get 正常·中文保真 | 文本标签（内容含中文 + 希腊字母 α + 引号转义） | ✓ | **中文/α 逐字符无损往返**；字段与 create 回显一致 |
| 6 | drawing_get 错误·假 UUID | | ✓ | 404 包裹风格 |
| 7 | drawing_update 组合更新 | x/y 坐标 + rotation=45 + z=10 + SVG 整体替换 | ✓ | 五项同时生效；返回更新后全量对象 |
| 8 | drawing_update 单项更新 | locked=true | ✓ | **部分更新安全**：仅动 locked，其余字段（坐标/SVG/z/rotation）原样保留不被清空 |
| 9 | drawing_update 错误·假 UUID | | ✓ | 404 包裹风格 |
| 10 | locked 语义复验·删除保护 | 对 locked=true 的绘图调 drawing_delete | ✓ | **409 "cannot be deleted because it is locked"**——条目级 locked 与 project_lock 置位的是同一开关，拦截一致 |
| 11 | locked 语义复验·编辑放行 | 同一 locked=true 状态下调 drawing_update 挪坐标 | ✓ | 放行成功——**locked 是删除保护、不是编辑保护**（与阶段 20 lock 语义定论一致，本轮落到绘图条目级复验） |
| 12 | drawing_delete 正常 | 解锁后删 D1 + 其余 4 个（含清洗项） | ✓ | 逐个返回 message + drawing_id；解锁后删除无阻碍 |
| 13 | drawing_delete 错误·假 UUID | | ✓ | 404 包裹风格 |
| 14 | 终态核对 | drawing_list → 项目删除 → project_list | ✓ | list count=0 → 项目干净删除 → 全局 count=0 |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **D-1（阶段 27 新发现，观察项）** | 低 | `drawing_create` 对**非 SVG 内容不校验、不报错**：传入纯文本（含 `<>&"` 等字符）返回"创建成功"，但内容被静默替换为空 `<svg></svg>`，原始字符串丢弃且无任何告警。调用方拼错内容（如忘包 `<svg>` 标签）会静默产出空绘图，只能靠回读发现。建议：要么 400 拒绝，要么至少在响应中提示已清洗 | drawing_create（update 换 SVG 同路径，推断同样行为，未单独复测） |

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| 阶段 19 Drawing 5 工具结论（全 ✓） | **全部复验成立**；本轮额外补齐：假 UUID 三类错误路径、组合/部分更新语义、中文 SVG 保真、四种形状覆盖 |
| 阶段 19 "锁定状态删除被 409 拒绝" | **复验成立**，且细化：条目级 `locked`（drawing_update 置位）与 project_lock 拦截同源；locked 下 update 放行 |
| 报错风格（"Unknown Status … Original xxx" 包裹） | create 假项目 / get / update / delete 假 UUID 均此风格，维持不变 |
| 阶段 26 恢复回滚中"绘图回原位" | 交叉印证（snapshot restore 对 drawing 的回滚已在那边验证） |

## 4. 统计

- 实测工具：**5 / 5**（14 个场景）
- 通过：5 · 新发现：D-1（非法 SVG 静默清洗为空 `<svg></svg>`，观察项）；**无新服务器缺陷**
- 增强验证：① SVG 内容保真（中文 + α + 转义引号逐字符往返，四种形状全覆盖）；② 条目级 locked 语义定论（删除 409 / 编辑放行，与 project_lock 同一开关）；③ 部分更新安全性（单字段更新不清空其余字段）
- 测试痕迹：5 个绘图逐个删除复核 + 临时项目整体删除，终态 `project_list` count=0
