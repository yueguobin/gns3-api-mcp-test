# GNS3 MCP Appliance 与 Image 模块工具专项复测报告（阶段 28）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 27 同一构建，未重启） |
| 测试范围 | Appliance 模块 **3 个**（list / get / install）+ Image 模块 **5 个**（list / get / install / delete / prune），正常路径 + 错误路径；重点复测 **P1-1**（appliance_install 成功路径响应非 JSON）与 **P2-1**（image_install 单镜像批量建模板）现状 |
| 测试方式 | 仅经 MCP 工具接口；本轮无项目/节点（纯服务器层对象）；真实删除经用户批准（2 个浏览器残留文件）；测完模板/镜像终态核对，`template_list` count=22 / `image_list` count=57 / `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 · ⏭️ 未执行 |

## 0. 环境备注

- 工具数量口径：**appliance 3 + image 5 = 8 个，与用户口径一致**。
- 起始基线：project 0 / 模板 22 / 镜像 59；终态：project 0 / 模板 22 / **镜像 57**（用户批准删除 2 个 crdownload 残留）。
- 镜像库背景：`chr-7.8.img`（P2-1 上次触发源）仍在，本轮复现路径一致；另有 `SONiC-…gns3a`（1KB appliance 定义文件被当 QEMU 镜像扫入）与 2 个 `.crdownload` 浏览器残留——后者本轮用作 image_delete 真实删除测试对象（用户批准）。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | 基线核对 | project_list / template_list / image_list | ✓ | 0 / 22 / 59，与环境基线一致 |
| 2 | appliance_list | fields 裁剪（appliance_id/name/category/vendor_name） | ✓ | 225 个；count 与明细一致；过滤生效 |
| 3 | appliance_get 正常 | FRR（`64f3dd9e-…`） | ✓ | registry_version/qemu 规格/images（4 版本含 md5/filesize/download_url）/versions 完整 |
| 4 | appliance_get 错误 | 假 UUID | ✓ | 404 "Could not find appliance …"（已知包裹风格） |
| 5 | appliance_install 错误·同名冲突 | CSR1000v 16.12.3（存量同名模板） | ✓ | 409 "A template with name 'Cisco CSR1000v' and version 16.12.3 already exists"——报错含 name+version，定位清晰；**无副作用** |
| 6 | appliance_install 错误·缺镜像 | Ostinato 1.3.0（本地无 ostinatostd qcow2） | ✓ | 409 "Could not find 'ostinatostd-1.3.0-1.qcow2'"——**缺镜像前置校验生效，无副作用**（行为确认，见 A-1） |
| 7 | appliance_install 成功路径 | FRR 8.2.2（本地 frr-8.2.2.qcow2 md5 与 appliance 定义一致） | ✗ | **P1-1 复现**：MCP 报 `Expecting value: line 1 column 1 (char 0)`（响应非 JSON）；**副作用已发生**——模板 FRR（`0ed179ca-…`，qemu）实际创建且完整可用（hda=frr-8.2.2.qcow2、version 8.2.2、appliance_metadata 可溯源 appliance_id）。template_get 佐证后 template_delete 清理 ✓ |
| 8 | image_list | 全量 ×2（起/终） | ✓ | 59 → 57；path/size/md5 checksum/时间戳齐全 |
| 9 | image_get 正常 | chr-7.8.img（按 filename） | ✓ | 全量字段 |
| 10 | image_get 错误 | 不存在 filename | ✓ | 404 "Image … not found"（已知包裹风格） |
| 11 | image_install | 扫描并自动建模板 | ⚠️ | 返回正常 JSON "Image installation completed"；**P2-1 复现且较阶段 19 更多：一次建 13 个模板（22→35）**——Debian + FRR + 10 个 MikroTik（chr-7.8.img 匹配；当日文字误记 9 个，按明细修正）+ **与存量同名的 Cisco CSR1000v 重复模板**（`effd6a7f` vs 存量 `4ec41c92`，无同名校验，与 appliance_install 的 409 形成对照）；返回值不含新建清单（I-1）。13 个全部按 template_id 删除（重名必须走 id），基线恢复 22 ✓，本轮无权限拦截 |
| 12 | image_delete 错误 | 不存在 filename | ✓ | 404 信息清晰（与阶段 19 一致） |
| 13 | image_delete 正常·真实删除 | 2 个 crdownload 残留（用户批准） | ✓ | **首次覆盖真实删除路径**：返回 message + image_id；image_list 复核 59→57，两文件从列表消失 |
| 14 | image_prune | — | ⏭️ | 主动跳过：会真删所有未引用镜像（破坏性，维持阶段 19 口径） |
| 15 | 终态核对 | template_list / image_list / project_list | ✓ | 22 / 57 / 0，无测试残留 |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **A-1（阶段 28 新观察）** | 信息 | `appliance_install` 对**本地缺镜像**的 appliance 前置 409 拒绝（"Could not find 'xxx.qcow2'"），无副作用——阶段 19 未记录过此校验。属正向行为确认（防止建出无镜像可用的模板），非缺陷 | appliance_install |
| **I-1（阶段 28 新发现，观察项）** | 低 | `image_install` 返回仅 `{"message": "Image installation completed"}`，**不返回新建模板清单/数量**——实际建了 13 个模板，调用方只能靠 template_list 前后 diff 才能知道副作用范围。且与 appliance_install 成功路径"响应坏"形成对照：两个 install 的返回行为一个不透明、一个坏。**→ 08-26 阶段 29 修复复测：已修**（created/skipped 结构化返回，与落库逐 id 相符） | image_install |

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| **P1-1（appliance_install 成功路径响应非 JSON）** | **复现，未修（本轮当时）**——症状逐字一致（`Expecting value: line 1 column 1`）；副作用仍是"模板实际已建且完整可用"（本轮 FRR qemu 模板含 appliance_metadata 溯源，较阶段 19 的记录更实锤）。规避：调用后以 template_list diff 核对 + template_delete 清理。**→ 08-26 阶段 29 修复复测：已修**（返回 message+template 摘要 JSON） |
| **P2-1（image_install 单镜像批量建模板）** | **复现且加重**：本轮 13 个（阶段 19 为 12 个），核心问题不变——**chr-7.8.img 匹配 10 个 MikroTik 模板 + 与存量同名的 CSR1000v 重复模板并存**（image_install 无同名校验；appliance_install 对同名 409）。清理全部成功，本轮无权限层拦截（阶段 19 曾有 2 个被拦）。**→ 08-26 阶段 29 修复复测：同名重复已修**（模板名+镜像引用双层去重，skipped 带原因；单镜像多不同名模板行为保留） |
| 报错风格（"Unknown Status … Original xxx" 包裹） | appliance_get 假 UUID / image_get / image_delete 404 均此风格，维持不变 |
| 阶段 19 Appliance/Image 其余结论 | appliance_list/get、image_list/get 复验全部成立 |

## 4. 统计

- 实测工具：**7 / 8**（15 个场景；image_prune 主动跳过）
- 通过：5（appliance_list/get、image_list/get/delete）· 缺陷复现：appliance_install（P1-1，未修）· 注意点：image_install（P2-1 加重 + I-1 返回不透明）· 未执行：image_prune
- 增强验证：① image_delete **真实删除路径首次覆盖**（用户批准的 2 个 crdownload，删后列表复核）；② appliance_install 三条路径完整矩阵（同名 409 / 缺镜像 409 / 成功 P1-1），副作用逐条核对；③ P1-1 副作用质量佐证（新建模板含 appliance_metadata 溯源、镜像绑定正确）
- 对照定论：**同名校验行为不一致**——appliance_install 对同名模板 409 拒绝，image_install 无校验直接建重复项（P2-1 核心成因）
- 测试痕迹：appliance_install 误建 1 个 + image_install 误建 13 个模板全部清理；2 个 crdownload 镜像删除为用户批准的定向清理（非测试残留）；终态模板 22 / 镜像 57 / 项目 0
