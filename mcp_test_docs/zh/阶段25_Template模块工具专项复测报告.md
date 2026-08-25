# GNS3 MCP Template 模块工具专项复测报告（阶段 25）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 24 同一构建，未重启） |
| 测试范围 | Template 模块工具全量：**5 个**（list / get / create / update / delete），正常路径 + 错误路径 + **端到端验证**（MCP 建模板 → 改属性 → 按模板建节点 → 节点 started） |
| 测试方式 | 仅经 MCP 工具接口；临时对象：docker 测试模板 `mcp-tpl-test-0825`（→ 改名 `-v2`）+ 临时项目 `mcp-tpl-test-0825`（1 节点），测完已全部删除，终态 `template_list` count=22、`project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 0. 环境备注

- 工具数量口径：**5 个，与用户口径一致**（list / get / create / update / delete）。
- 模板基线 **22 个**，与阶段 23/24 一致。
- **环境变化：阶段 19 遗留待手工清理的 2 个 MikroTik 误建模板（RB1100AHx4 Dude Edition `7d06e72d-…`、RB450G `bc581894-…`）已不在列表中**——阶段 19 遗留项 #2 消解（本轮仅核对现状，未做删除操作）。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | template_list | fields 裁剪 ×2（4 字段 / 2 字段） | ✓ | 22 个模板；count 与明细一致；fields 过滤生效 |
| 2 | template_get 按 name | "Cisco IOU L3" | ✓ | 全量属性：iou 专属字段（path/ethernet_adapters/serial_adapters/startup_config 等）+ tags |
| 3 | template_get 按 id | Alpine Linux（`5c62ba31-…`） | ✓ | docker 全量属性（image="alpine"、adapters=3、custom_adapters 等） |
| 4 | template_get 错误·name 不存在 | "IOU L3"（实名 Cisco IOU L3） | ✓ | 干净 JSON `{"error": "Template '…' not found"}`——错误发生在 name 解析层，**与 ID 路径的报错风格不一致（见 T-1）** |
| 5 | template_get 错误·假 UUID | | ✓ | "Unknown Status … Original 404" 已知包裹风格 |
| 6 | template_create 正常 | docker + image="alpine" | ✓ | `830c484d-…`；默认 adapters=1、category=guest、symbol 自动分配、default_name_format `{name}-{0}` |
| 7 | template_create 错误·缺必填 image | | ✓ | 400 + pydantic 细节（"Field required"），定位清晰；**无副作用**（终态列表无残留） |
| 8 | template_create 错误·重名 | 与刚建模板同名 | ✓ | 409 "A template with name '…' already exists" |
| 9 | template_update 正常 | 改名 + adapters 1→2 + 中文 usage | ✓ | 三项均生效；`updated_at` 刷新（14:56:09→14:56:36）、`created_at` 不变；**中文无损往返** |
| 10 | template_update 错误 | 假 UUID | ✓ | 404 已知包裹风格 |
| 11 | **端到端验证** | 新模板建节点（不传 name）→ start | ✓ | 节点 `mcp-tpl-test-0825-v2-1`：**默认名跟随 update 后的新名**（default_name_format 用的是当前 name）；started、console 5000——模板真实可用（非仅注册） |
| 12 | template_delete 按 name | 删测试模板 | ✓ | 返回 "Template deleted"；按 name 删除路径可用 |
| 13 | template_delete 错误 | 假 UUID | ✓ | 404 已知包裹风格 |
| 14 | 终态核对 | template_list 复查 | ✓ | count=22，测试模板无残留 |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **T-1（阶段 25 新发现，观察项）** | 低 | `template_get` 两条解析路径的报错风格不一致：**按 name 查不存在** → name 解析层直接返回干净 JSON `{"error": "…"}`；**按 id 查不存在** → 走服务器 REST，返回 "Unknown Status: … (Original 404 Error)" 裸文本包裹。语义均清晰，仅风格不统一（与既有包裹风格问题同族，非新缺陷类别） | template_get |

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| 阶段 19 Template 5 工具结论（全 ✓） | **全部复验成立**；本轮额外补齐：按 name 的 get/delete 路径、create/update 的错误路径、e2e 节点可用性验证 |
| `template_list`（历史上曾坏，08-23 前已修） | 持续正常 |
| 报错风格（"Unknown Status … Original xxx" 包裹） | 全线维持不变（create 400/409、update 404、delete 404 均此风格） |

## 4. 统计

- 实测工具：**5 / 5**（14 个场景）
- 通过：5 · 新发现：T-1（get 双路径报错风格不一致，观察项）；**无新服务器缺陷**
- 端到端增强验证：模板生命周期全链路（建 → 改 → 用 → 删）闭环，节点默认名跟随模板 update 后新名（较阶段 19 的纯 CRUD 验证升级）
- 测试痕迹：临时项目（1 节点）+ 测试模板全部清理，终态 `template_list` count=22 / `project_list` count=0
- 环境遗留项消解：MikroTik 误建模板 ×2 已不在（阶段 19 遗留清单仅剩僵尸项目条目一项）
