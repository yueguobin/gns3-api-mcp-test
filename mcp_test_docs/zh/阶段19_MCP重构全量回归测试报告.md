# GNS3 MCP 接口全量回归测试报告（阶段 19）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（MCP 接口重构后，uptime 170s 起测） |
| 测试方式 | MCP 工具逐个调用，正常路径 + 关键错误路径；临时项目 `mcp-regress-0825`（2×IOU L3 + 3×VPCS + 1×Alpine docker，4 链路，测完已删） |
| 存量环境影响 | 5 个存量项目经校验完好；测试中发生一次局部误删事故（见 P0-1），已评估并记录 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 · ⏭️ 未执行 |

## 1. Server

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| server_version | 查版本 | ✓ | 3.1.0a5 / controller 127.0.0.1 |
| server_statistics | 查统计 | ✓ | computes/projects/nodes/links 分组统计正常 |

## 2. Project（15 个工具）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| project_create | 建临时项目 ×2 | ✓ | auto_close=false 如工具描述；同名重建无冲突 |
| project_get | 查详情 | ✓ | |
| project_list | 查列表 ×3 | ✓ | |
| project_stats | 查统计 | ✓ | 新增 `markers` 计数字段 |
| project_update | show_grid/zoom 修改 | ✓ | 改动即时生效 |
| project_readme_update | 写 README | ✓ | 落 README.txt |
| project_readme_get | 读 README | ✓ | 中文内容无损往返 |
| project_duplicate | 复制项目 | ✓ | 副本 closed、属性继承 |
| project_open | 开项目 ×3 | ✓ | |
| project_close | 关项目 ×2 | ✓ | |
| project_lock | 锁项目 | ⚠️ | closed 状态下调用返回原始 403 文本（"Unknown Status…Original 403"）——**已知遗留，维持原样（用户确认 08-25）**；opened 后正常，修复后四象限复测通过 |
| project_locked | 查锁定 | ✓ | 修复后四象限复测：lock→true / unlock→false（需项目含 ≥1 节点或绘图）；空项目恒 false（守卫，符合设计，无事可锁） |
| project_unlock | 解锁 | ✓ | 修复后复测通过。曾发现空项目 vacuous-True 缺陷（unlock 返回成功但 locked 不翻转），当日修复（controller/project.py `locked` 空集守卫） |
| project_load | 从文件加载 | ⚠️ | 正常路径 ✓（限允许目录）；/tmp 路径 403 ✓；缺 computes 字段报清晰 pydantic 409 ✓；**但见 P0-1：加载 projects 根目录裸 .gns3 会产生 path 指向根目录的条目** |
| project_delete | 删项目 | ✗ | 常规路径 ✓（副本、临时项目均干净删除）；**但 path=projects 根的条目触发 rmtree 整个 projects 目录（P0-1）** |

## 3. Template（5）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| template_list | 全量 + fields 裁剪 ×3 | ✓ | 24 个模板，fields 过滤生效 |
| template_get | 按 id 查 IOU L3 | ✓ | 含 16 端口等全量属性 |
| template_create | 建 docker 模板 | ✓ | alpine:3.19 |
| template_update | 改名 + adapters | ✓ | updated_at 同步刷新 |
| template_delete | 删测试模板 ×13 | ✓ | 本次清理 11 个 image_install 误建模板时 9 个成功、2 个被本地权限层拦截（非服务器问题） |

## 4. Appliance（3）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| appliance_list | fields 过滤 ×2 | ✓ | 225 个，含 appliance_id |
| appliance_get | 查 FRR | ✓ | versions/images/download_url 完整 |
| appliance_install | 409 冲突路径 / 成功路径 | ✗ | 冲突路径报错正常；**成功路径模板已创建但响应非 JSON，MCP 解析报 `Expecting value: line 1 column 1`（P1-1）** |

## 5. Compute（3）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| compute_list | 查远程 compute | ✓ | 空（仅内置 local，符合环境） |
| compute_get | "local" / 假 UUID | ⚠️ | compute_id 仅收 UUID："local" 被 pydantic 拦截（约束非 bug）；假 UUID 返回清晰 404 |
| compute_images | — | ⏭️ | 无注册远程 compute，无可测对象 |

## 6. Image（5）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| image_list | 全量 | ✓ | 59 个镜像 |
| image_get | 按 filename | ✓ | |
| image_install | 扫描并自动建模板 | ⚠️ | 功能可用，但一次生成 **12 个模板**：chr-7.8.img 单镜像匹配出 9 个 MikroTik、还建了与现有模板同名的 CSR1000v 重复项（P2-1） |
| image_delete | 不存在的镜像 | ✓ | 404 信息清晰；真实删除未执行（无测试镜像，破坏性） |
| image_prune | — | ⏭️ | 会真删未引用镜像，主动跳过 |

## 7. Node（16 + 批量模式）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| node_create 单个 | VPCS | ✓ | 默认名 PC1（default_name_format 生效） |
| node_create 批量 | 4 节点混合类型 | ✓ | 逐项 status 返回 |
| node_list | fields 过滤 ×4 | ✓ | |
| node_get | 全量字段 | ✓ | 端口表/properties/command_line 完整 |
| node_update | 坐标 + console_auto_start | ✓ | 返回全量节点详情 |
| node_duplicate | 复制 VPCS | ✓ | 新默认名 PC3，tags 继承 |
| node_links | 查 R-1 链路 | ✓ | 含 suspend 状态与 markers |
| node_isolate / node_unisolate | 隔离/恢复 PC1 | ✓ | link suspend:true 实测生效，恢复正常 |
| node_start 单个/批量 | R-1 / 4 节点 | ✓ | 批量逐项 status |
| node_start_all | 全量启动 | ✓ | 6/6 started（含此前 stopped 的节点） |
| node_stop / node_suspend 单个 | PC2 | ✓ | suspend→stop 链路正常 |
| node_suspend_all / node_stop_all | 全量 | ✓ | 6/6 stopped |
| node_delete 单个/批量 | 1 + 5 节点 | ✓ | 批量逐项 status |
| node_console | VPCS 取 WS 信息 | ✓ | ws://10.5.1.1:3080 + 10 分钟 JWT + 现成 websocat 命令 |

## 8. Node files（4）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| node_file_list | alpine 节点目录 | ✓ | |
| node_file_write | 写中英混排文本 | ✓ | UTF-8 无损 |
| node_file_get | 读回 + metadata | ⚠️ | 内容正确；`returned_bytes`(50)≠`total_bytes`(51)，行尾换行计数不一致（P2-2） |
| node_file_delete | 删测试文件 | ✓ | |

## 9. Link（11）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| link_create 单个/批量 | 以太 ×3 + 串口 ×1 | ✓ | 批量紧凑格式可用；**端口标签正确（"2/0"/"0/0"，历史 "4/0" 标签 bug 未复现）** |
| link_list | fields 过滤 ×2 | ⚠️ | **fields 不支持 `markers`**，报 Unknown fields（看 marker 用 link_get/node_links，P2-3） |
| link_get | 单链路 ×3 | ✓ | 含 markers/suspend/filters |
| link_update | filter + suspend | ✓ | docker 链路 delay[50,5]+packet_loss[1] 生效；serial suspend 开关正常；filters 清空正常。**IOU↔IOU 链路现在也接受 delay filter（旧版 409，行为反转，数据面效果未验，P2-4）** |
| link_available_filters | docker 链路 | ✓ | 5 种 filter 及参数范围完整 |
| link_reset | 单链路重置 | ✓ | filter 配置保留（符合描述） |
| link_capture_start / stop | 以太链路抓包 | ✓ | capturing 状态与文件路径正确 |
| link_capture_download | 带 JWT 下载 | ✓ | 返回现成 Bearer curl 命令；实测下载为合法 pcap |
| link_delete 单个/批量 | 1 + 2 条 | ✓ | 批量逐项 status |

## 10. Marker（2）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| link_marker | create/update/delete | ✓ | bpf/color/direction 修改生效，删除干净 |
| marker_definition | create/list/update/delete | ✓ | 项目级扇出到 3 条以太链路（串口被跳过=DLT 默认 Ethernet-only，符合设计）；update 同步传播；delete 联动清理全部链路 |

## 11. Drawing（5）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| drawing_create / list / get | 矩形（实心填充） | ✓ | |
| drawing_update | 坐标/旋转/锁定 | ✓ | |
| drawing_delete | 删除 | ✓ | 锁定状态删除被正确 409 拒绝，解锁后成功 |

## 12. Snapshot（4）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| snapshot_create | 全停后创建 | ✓ | |
| snapshot_list | 列出 | ✓ | |
| snapshot_restore | 恢复 | ✓ | 项目自动重开，6 节点/链路完整恢复（stopped） |
| snapshot_delete | 删除 | ✓ | |

## 13. Symbol（5）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| symbol_list | 全量 | ⚠️ | 663 条约 98k 字符，超 MCP 输出上限落盘（P2-5） |
| symbol_dimensions | 内置 / 自定义 | ✗ | 内置 60×60 正确；**自定义 70×40 的 SVG 返回默认 60×60（P1-2）** |
| symbol_get | 内置 / 自定义下载 | ✗ | 内置 ✓（18KB 合法 SVG）；**自定义 raw 下载返回的是另一个内置图形（P1-2）** |
| symbol_upload | 上传自定义 SVG | ✗ | **仅落盘不注册**：文件在 `~/GNS3/symbols/` 但服务端索引不识别（P1-2） |
| symbol_delete | 自定义 / 内置 | ✗ | 内置 403 拒绝 ✓（正确）；**自定义符号也被当 built-in 403 拒绝，无法通过 MCP 删除（P1-2）** |

## 14. Device / VPCS（3）

| 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|
| device_show_run | R-1 show version / show run int lo0 | ✓ | 输出干净，配置落地验证通过 |
| device_config_send | R-1+R-2 两台批量 lo0 配置 | ✓ | 自动 conf-t/end；2 台并发正常（3 台并发的历史问题未复测） |
| vpcs_config_set | PC1 设 IP + save | ✓ | startup.vpc 保存成功 |

## 问题汇总

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| P0-1 | 严重 | `project_load` projects 根目录裸 .gns3 → 条目 path 指向根；`project_delete` 对其执行 rmtree 整个 projects 目录。测试中实际误删了一个项目目录及文件（本次为测试自建项目，存量 5 项目已校验无损），靠 root 属主孤儿文件权限中止。遗留僵尸条目 `mcp-regress-loadtest`（0d8f1a5e-…-0001）**重启服务器前不可删除** | project_load / project_delete |
| P1-1 | 高 | `appliance_install` 成功路径响应非 JSON，MCP 解析报错；副作用（建模板）已实际发生 | appliance_install |
| P1-2 | 高 | 自定义 symbol 链路整体坏：上传不注册、dimensions 回默认值、raw 下载内容错、删除被误判 built-in 拒绝 | symbol_upload / symbol_get / symbol_dimensions / symbol_delete |
| P2-1 | 低 | image_install 单镜像可批量生成多个（含同名重复）模板 | image_install |
| P2-2 | 低 | node_file_get 字节计数差 1（行尾换行） | node_file_get |
| P2-3 | 低 | link_list fields 不支持 markers | link_list |
| P2-4 | 待确认 | IOU↔IOU 链路 filter 由 409 变为接受（API 层；数据面未验证） | link_update |
| P2-5 | 低 | symbol_list 输出超限（663 条/98k 字符） | symbol_list |
| P1-3（已修复） | — | 空项目 lock 后 `locked` 恒 true、`unlock` 返回成功但状态不翻转（vacuous-True 根因）；08-25 当日修复（controller/project.py `locked` 空集守卫）并四象限复测通过。附语义定论：lock=逐项置位节点/绘图、locked=聚合查询+删除保护（update 放行、delete 409）。closed 态 lock 裸 403 文案转**已知遗留**（维持原样） | project_lock / project_locked / project_unlock |

## 统计

- 实测工具：**62**（另有批量模式覆盖 8 个工具；compute_images、image_prune 2 个未执行）
- 通过：52 · 通过带注意点：7 · 存在缺陷：8 个工具受 3 个缺陷影响（P0-1/P1-1/P1-2）· 未执行：2
- 与 08-23 基线对比：marker 体系、capture 下载、批量逐项 status、默认命名、device 工具等结论全部复验成立；IOL filter 结论反转（P2-4）
- 遗留待手工处理：
  1. 僵尸项目条目 `mcp-regress-loadtest`（`0d8f1a5e-0000-4000-8000-000000000001`，重启服务器按子目录 `0d8f1a5e-…/` 重扫后再删）
  2. 误建模板 `MikroTik RB1100AHx4 Dude Edition`（`7d06e72d-5c4b-4e3a-bb4c-ef3defb4d142`）、`MikroTik RB450G`（`bc581894-fba9-4b34-b37e-83b3c6e1151a`）
