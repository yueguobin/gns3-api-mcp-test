# GNS3 MCP Link 模块修复复测报告（阶段 24）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（服务器重启 + `/mcp` 重连后的构建） |
| 复测范围 | 阶段 23 报出的 **L-1（同模板批量建节点默认名竞态）** 专项 + Link 模块 10 工具全量回归（与阶段 23 同一流程逐步对照） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-link-retest-0825`（拓扑与阶段 23 完全一致：VPCS×2 + IOU×2 + Alpine + ethsw，6 链路），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 1. 修复项验证

### 1.1 L-1 同模板批量建节点名字竞态 → **已修**（创建按提交序串行化）

与阶段 23 **完全相同的提交序**（[IOU(-300,-100), IOU(-300,+100), Alpine, ethsw, VPCS, VPCS]）：

| 观察点 | 阶段 23（修复前） | 阶段 24（本次） |
|---|---|---|
| 返回顺序 | =提交序（修复只作用于响应收集层） | =提交序 ✓ |
| 首个提交的 IOU（位置 -300,-100）获得的名字 | **R-2**（竞态错位） | **R-1** ✓（node_list 坐标核验） |
| console 号分布 | 5000(PC1)/5002(PC2)/5004(R-1)/5005(Alpine)/5006(R-2)——实际创建序≠提交序 | **5000(R-1)/5001(R-2)/5002(Alpine)/5003(PC1)/5005(PC2)**——console 随提交序单调递增 ✓ |
| 结论 | 创建并行、名字分配竞态 | **创建已按提交序串行化**，名字/console 分配确定化；按 name 与按 node_id 对号 now 等价 |

附注（外观项，非缺陷）：console 序列在 5003→5005 处跳过 5004，分配存在单个空洞，不影响对号。

### 1.2 P2-3 link_list 不支持 markers → **未修**（维持现状）

`fields=["markers"]` 仍报 `Unknown fields: ['markers']`（附 available_fields 清单，报错质量不变）。看 markers 仍需 `link_get` / `node_links`。

## 2. Link 10 工具全量回归（与阶段 23 逐项对照）

| # | 工具 | 场景 | 结果 | 与阶段 23 差异 |
|---|---|---|---|---|
| 1 | link_create 单个·对象 | PC1↔Sw 0/0 | ✓ | 无（标签 "0/0" 正确） |
| 2 | link_create 单个·紧凑 | PC2↔Sw 0/1 | ✓ | 无 |
| 3 | link_create 批量 | R-1↔Sw 0/2 + Alpine↔Sw 0/3 | ✓ | 无（返回序=提交序） |
| 4 | link_create 串口 | R-1 2/0 ↔ R-2 2/0 | ✓ | 无（标签 "2/0"） |
| 5 | link_create 错误路径 | 假节点 UUID | ✓ | 报错风格不变（"Unknown Status … Original 404"） |
| 6 | link_list | fields 过滤；fields=["markers"] | ✓ / ⚠️ | P2-3 复现（未修） |
| 7 | link_get | 以太 / 串口 / 假 UUID | ✓ | 无（字段齐全，404 清晰） |
| 8 | link_available_filters | docker / 串口 | ✓ | 无（5 种 filter 及参数范围完整） |
| 9 | link_update filter | docker delay[50,5]+loss[1]；IOU↔IOU delay[100,10] | ✓ | 无；**P2-4 复验仍成立** |
| 10 | link_update suspend | 串口 true→false | ✓ | 无 |
| 11 | link_update 非法值 | packet_loss [150] | ✓ | 409 报错文案不变 |
| 12 | link_update 数据面 | L1 delay[200,20] → ping → 清空 → ping | ✓ | **数据面复验成立**：RTT 352–410ms ≈ 2×200ms；清空后回落 0.8–1.6ms |
| 13 | link_reset | docker 链路（带 filter） | ✓ | 无（filter 保留） |
| 14 | link_capture_start | 单个（自定义名）/ 重复启动 / 批量 | ✓ | 无（重复启动 409 文案不变；自动命名正常） |
| 15 | link_capture_stop | 单个 / 批量 | ✓ | 无（停止后文件名保留） |
| 16 | link_capture_download | 单个 / 批量 | ⚠️ | 无（Bearer JWT curl 命令正常；**W-2 仍适用**——pcap 实际下载被权限层按铁律拦截，未执行） |
| 17 | link_delete | 单个 / 批量 / 假 UUID | ✓ | 无（逐项 "success"、按提交序） |
| 18 | 级联 | node_delete R-2 | ✓ | 无（串口链路自动清理） |

## 3. 统计

- 实测：L-1 专项复验 + 10/10 工具全量回归
- **修复确认：L-1 ✓（创建串行化，名字/console 确定化）**；P2-3 未修（已知遗留）；P2-4 复验成立（数据面仍未验，W-2 同前）
- 无新增服务器缺陷；报错风格（"Unknown Status … Original xxx" 裸文本包裹）全线维持，未见变化
- 测试痕迹：6 节点 + 6 链路 + 3 个 pcap 随项目删除清理，终态 `project_list` count=0
