# GNS3 MCP Link 模块工具专项复测报告（阶段 23）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 22 同一修复构建） |
| 测试范围 | Link 模块工具全量：**10 个**（create / list / get / update / available_filters / reset / capture_start / capture_stop / capture_download / delete），正常路径 + 错误路径 + filter 数据面实测 |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-link-test-0825`（VPCS×2 + IOU×2 + Alpine docker + 以太交换机，6 链路：4 以太 + 1 串口 + 1 IOU↔IOU 以太），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

> **2026-08-25 阶段 24 修复复测**：本报告的 **L-1 已在上游修复并复测通过**（批量创建按提交序串行化，同模板节点名字/console 分配确定化——首个提交的 IOU 现在确定获得 R-1 与最小 console 号），详见《阶段24_Link模块修复复测报告.md》。P2-3 复验仍未修（维持现状）；P2-4 / W-2 状态不变。

## 0. 环境备注（工具数量口径）

- 用户口径 **9 个**；当前会话工具清单中 link 系共 11 个，其中 `link_marker` 按阶段 19 分组属 Marker 模块（已在其 §10 测过），剔除后 **10 个**，本轮全部实测。与 9 的差值疑似 capture_start/stop 合并计数（或 available_filters 未计），待确认——不影响覆盖度。
- 模板 22 个、`project_list` 起始 count=0，与环境基线一致。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | link_create 单个·对象格式 | PC1↔Switch1 0/0 | ✓ | 端口标签 `"0/0"` 正确（历史 "4/0" 标签 bug 持续未复现） |
| 2 | link_create 单个·紧凑格式 | PC2↔Switch1 0/1（`[id,ad,pt,id,ad,pt]`） | ✓ | 标签 `"0/1"` 正确 |
| 3 | link_create 批量 | R-1↔Sw 0/2 + Alpine↔Sw 0/3 | ✓ | **返回顺序=提交顺序**（N-2① 修复对 link 批量持续成立）；逐项 status |
| 4 | link_create 串口 | R-1 2/0 ↔ R-2 2/0（link_type=serial） | ✓ | 标签 `"2/0"` 正确 |
| 5 | link_create 错误路径 | 假节点 UUID | ✓ | 404 包裹风格（"Unknown Status … Original 404"），语义清晰 |
| 6 | link_list | fields 过滤 ×2（link_id/link_type/suspend/capturing；+capture 字段） | ✓ | 6 链路计数与状态正确 |
| 7 | link_list fields=["markers"] | P2-3 复验 | ⚠️ | **仍报 Unknown fields**（P2-3 复现成立）；报错附 `available_fields` 完整清单，指引清晰 |
| 8 | link_get | 以太 L1 / 串口 L5 / 假 UUID | ✓ | markers/suspend/filters/capture 字段齐全；404 清晰 |
| 9 | link_available_filters | VPCS / docker / 串口 / IOU↔IOU 四种链路形态 | ✓ | 均返回 5 种 filter（frequency_drop/packet_loss/delay/corrupt/bpf）及参数范围；串口链路同样全量返回 |
| 10 | link_update filter | docker 链路 delay[50,5]+packet_loss[1]；IOU↔IOU 链路 delay[100,10] | ✓ | 均生效回显；**P2-4 复验成立（IOU↔IOU 接受 delay）** |
| 11 | link_update suspend | 串口链路 true→false | ✓ | 状态翻转即时回显 |
| 12 | link_update 清空 filter | L1 `filters:{}` | ✓ | 清空后 `filters:{}`；清空后 ping RTT 由 ~390ms 回落 1.0–1.7ms（反向佐证） |
| 13 | link_update 非法值 | packet_loss [150] | ✓ | 409 "Chance must be between 0 and 100 %, got: 150"，报错质量好 |
| 14 | link_update 数据面实测 | L1（VPCS↔ethsw）delay[200,20]，PC1 ping PC2 | ✓ | **RTT 359–428ms（均值 ~390ms ≈ 2×200ms ± jitter）**——delay filter 数据面验证通过，且为双向各计一次的语义佐证 |
| 15 | link_reset | docker 链路（带 delay+loss） | ✓ | filter 配置保留（符合工具描述）；返回 message + 全量 link 详情 |
| 16 | link_capture_start 单个 | L1 + 自定义文件名 l1-cap.pcap | ✓ | capturing:true、capture_file_path 指向 project-files/captures/ |
| 17 | link_capture_start 重复启动 | L1 已抓包再启动 | ✓ | 409 "Packet capture is already activated on port 0"，清晰 |
| 18 | link_capture_start 批量 | [L3, L4] | ✓ | 逐项 success；自动命名 `R-1_0-0_to_Switch1_0-2.pcap`（节点名+端口） |
| 19 | link_capture_stop 单个/批量 | L1 / [L3, L4] | ✓ | 停止后 `capture_file_name/path` 保留（可供下载）；capturing 翻转正确 |
| 20 | link_capture_download 单个/批量 | L1 / [L3, L4] | ⚠️ | 单/批模式均返回 download_url + **现成 Bearer JWT curl 命令**（10 分钟有效期）；**pcap 实际下载本轮未执行**——权限层按铁律拦截了非 MCP 直连 REST（W-2，非服务器问题；pcap 合法性阶段 19 已实测） |
| 21 | link_delete 单个 | L6（IOU↔IOU） | ✓ | |
| 22 | link_delete 批量 | [L3, L4] | ✓ | 逐项 `status:"success"`（N-2② 口径持续成立）且按提交序 |
| 23 | link_delete 错误路径 | 假 UUID | ✓ | 404 清晰 |
| 24 | 级联验证 | node_delete R-2 | ✓ | 其串口链路自动消失（node_links 同口径；阶段 22 结论复验成立） |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **L-1（阶段 23 新发现，观察项）** | 低 | **同模板节点批量创建时，默认名/console 号分配与提交顺序解耦**（创建并行竞态）：首个提交的 IOU 实际获得名 R-2、console 5006（按 console 号推断实际创建序 PC1→PC2→R-1→Alpine→R-2）。**返回顺序本身仍=提交顺序**（N-2① 修复只作用于响应收集层）。自动化按 name 对号会错位，应以 node_id 关联 | node_create 批量（搭环境时发现，影响链路自动化编排） |
| **W-2（观察项，非服务器缺陷）** | 信息 | pcap 实际下载验证被权限层按铁律拦截（工具返回的 curl 命令属非 MCP 直连 REST）。download_url/JWT 结构与有效期说明已从工具响应验证；pcap 合法性以阶段 19 实测结论为准 | link_capture_download（测试方法限制） |

## 3. 已知问题复验状态

| 编号 | 本轮状态 |
|---|---|
| P2-3（link_list 不支持 markers） | **复现成立**，未修；报错附 available_fields 清单 |
| P2-4（IOU↔IOU 链路 filter 由 409 变接受） | **复验成立**（API 层接受 delay）；本轮新增 VPCS↔ethsw 链路 delay **数据面实测通过**（RTT≈2×delay），IOU↔IOU 数据面仍未验 |
| N-2①/N-2②（批量顺序 / delete status 口径） | link_create / link_delete 批量**持续成立** |
| 历史 "4/0" 端口标签 bug | 持续未复现（本轮 6 链路标签全对） |

## 4. 统计

- 实测工具：**10 / 10**（Link 模块口径，不含 link_marker）
- 通过：8 · 通过带注意点：2（link_list——P2-3 已知；link_capture_download——W-2 方法限制）
- 新发现：L-1（同模板批量建节点默认名竞态，观察项）、W-2（下载验证方法限制）；**无新服务器缺陷**
- 数据面增强验证：delay filter 双向语义实测（RTT≈2×delay ± jitter），较阶段 19 的 API 层验证升级
- 测试痕迹：6 节点 + 6 链路 + 3 个 pcap 捕获文件随项目删除全部清理，终态 `project_list` count=0
