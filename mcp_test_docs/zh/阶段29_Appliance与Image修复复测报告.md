# GNS3 MCP Appliance 与 Image 修复复测报告（阶段 29）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-26 |
| 被测对象 | gns3server **3.1.0a5**（阶段 28 后用户更新修复，服务器重启；MCP 会话 `/mcp` 重连） |
| 复测范围 | 阶段 28 三项发现：**P1-1**（appliance_install 成功路径响应非 JSON）· **P2-1**（image_install 同名重复模板）· **I-1**（image_install 返回不含新建清单）+ 错误路径回归 |
| 测试方式 | 仅经 MCP 工具接口；无项目/节点；误建模板全部清理，终态 `template_list` count=22 / `project_list` count=0 |
| 结果标记 | ✓ 通过 · ✗ 缺陷 |

## 0. 环境备注

- 服务器重启后 MCP 首批调用报 -32602（会话失效），`/mcp` 重连后全部恢复正常——与既往"server 更新需重连"经验一致。
- **僵尸项目条目 `mcp-regress-loadtest`（0d8f1a5e-…-0001）重启后自愈消失**：project_list count=0，阶段 19 遗留清单最后一项消解（此前记忆"重启后按子目录重扫自愈"得到验证）。
- 基线：模板 22 / 镜像 57 / 项目 0（与阶段 28 终态一致）。

## 1. 逐项复测结果

| # | 项 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | **P1-1 修复复测** | appliance_install FRR 8.2.2（与阶段 28 完全同条件：本地 md5 一致镜像、无同名模板） | ✓ **已修** | 返回正常 JSON：`{"message": "Appliance … installed", "template": {template_id, name, version, template_type}}`——不再报 `Expecting value: line 1 column 1`，且直接带回新模板摘要 |
| 2 | 错误路径回归·同名 | 对刚装的 FRR 8.2.2 再次 install | ✓ | 409 "A template with name 'FRR' and version 8.2.2 already exists"（含 name+version）——同时佐证 #1 模板真实落库 |
| 3 | 错误路径回归·缺镜像 | Ostinato 1.3.0 | ✓ | 409 "Could not find 'ostinatostd-1.3.0-1.qcow2'"——前置校验维持，无副作用 |
| 4 | **P2-1 修复复测** | image_install（模板 23 = 基线 22 + FRR） | ✓ **同名重复已修** | created 11 个（Debian 12.6 + 10 个 MikroTik 7.8，全部**不同名**）；**"Cisco CSR1000v" 被跳过，理由 "a template named 'Cisco CSR1000v' already exists"**——阶段 28 的同名重复模板（effd6a7f vs 存量 4ec41c92）不再产生 |
| 5 | **I-1 修复复测** | 同上返回内容核对 | ✓ **已修** | 返回结构化 `created`（11 项：template_id/name/version/template_type）+ `skipped`（11 项：name + reason）；**与 template_list 落库逐 id 核对完全一致**（22→34，新增 11 个 id 一一对应） |
| 6 | 引用跳过逻辑 | skipped 明细 | ✓ | 已被模板使用的镜像被跳过（如 frr-8.2.2.qcow2 "image is already used by one or more templates"——因 #1 刚建的 FRR 模板引用它；csr1000v-16.12.03 同理）——镜像级 + 模板名级**双层去重** |
| 7 | 清理与终态 | 12 个测试模板（11 image_install + 1 appliance_install FRR）按 template_id 删除 | ✓ | 全部成功；终态 template_list count=22，无残留 |

## 2. 行为保留项（非缺陷，记录）

- **单镜像多 appliance 匹配仍会建多个不同名模板**：chr-7.8.img（md5 匹配 10 个 MikroTik 型号 appliance）→ 本轮 created 10 个 MikroTik 模板。属合理行为（各型号 appliance 定义都引用同一 CHR 镜像），且现在有 created 清单透明可查、可批量清理，风险可控。
- 笔误修正：阶段 28 当日文字写"9 个 MikroTik"，实际明细（同日 template_list 存档）与本轮均为 **10 个**（阶段 28 的 13 = Debian + CSR1000v 重复 + 10 MikroTik + FRR）——阶段 28 报告已同步更正；阶段 19 报告"9 个"为当时现场记录，无明细存档，不作回溯改动。

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| P1-1（appliance_install 成功路径响应非 JSON） | **已修复**——正常 JSON 且含模板摘要 |
| P2-1（image_install 批量建模板，核心：同名重复） | **同名重复已修复**（双层去重：模板名 + 镜像引用）；单镜像多不同名模板行为保留（见 §2） |
| I-1（image_install 返回不含新建清单） | **已修复**——created/skipped 结构化返回，与落库核对一致 |
| 报错风格（"Unknown Status … Original xxx" 包裹） | 同名 409 / 缺镜像 409 维持不变 |
| 阶段 19 遗留 #1（僵尸项目条目 mcp-regress-loadtest） | **消解**——服务器重启后自愈，project_list 干净 |

## 4. 统计

- 复测场景：7 个，**全部通过**；阶段 28 三项发现（P1-1 / P2-1 同名重复 / I-1）全部修复确认
- 修复质量增强点：① appliance_install 成功响应直接携带模板摘要（调用方无需二次 get）；② image_install 的 skipped 带原因（同名 / 镜像已引用），副作用完全透明
- 测试痕迹：12 个测试模板全部清理，终态模板 22 / 项目 0 / 镜像 57
