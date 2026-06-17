---
name: mcp-backend-optimization
description: GNS3 MCP 后端性能优化记录（2026-06-15/16）
metadata: 
  node_type: memory
  type: reference
  originSessionId: 7b7f165e-d821-4c71-bfdd-1a8b0b4b525e
---

## GNS3 MCP 后端优化（2026-06-15~16）

2026-06-15 至 2026-06-16，GNS3 MCP 后端经历了多轮热更新迭代，核心优化包括：

1. **10s HTTP 读超时 → 30s + 实际响应大幅缩短**：`requests` 读超时从 10s 调大，后续进一步优化处理逻辑，40 台 qemu IOSv 批量创建从"全部超时"优化到 **1 秒内返回 success**。
2. **`node_create` 响应从全量对象精简到 5 字段**：每节点只返回 `{node_id, name, node_type, status, console}`，避免 11 万字符落盘。
3. **`link_create` 返回从全量 link 对象精简到 `{link_id, link_type, nodes}`**：去掉 `suspend/link_style/filters/capturing/wireshark/project_id` 等冗余字段。
4. **`_filter_link_response` NameError 修复**：批量 `link_create` 响应过滤不再报错。
5. **`node_create` 批量模式支持顶层 `template_id`**：`nodes` 数组中每项无需重复 `template_id`。
6. **`auto_close` 注意**：长批量操作前需 `project_update(auto_close=false)`，避免中途被关闭（非 bug，GNS3 项目默认行为）。
7. **QEMU IOSv 批量创建稳定**：连续 9 轮 × 40 台 = 360 台零故障，全部 1 秒内返回。

### 关键结论
- 优化后批量接口响应极快，40 台 QEMU IOSv 单次创建 < 1 秒
- 参数简化（顶层 template_id）、返回精简（5 字段）、全程无超时
- ~~命名受模板 `default_name_format` 控制，`name` 参数不一定作为最终节点名~~（已修复，见 2026-06-16 更新）

### 2026-06-16 更新（后端热更 + 重启后）
1. **`node_create` 的 `name` 参数现在生效**：之前 docker 模板创建会忽略 `name`、按 `default_name_format` 生成 `AlpineLinux-N`；重启后传 `name="alpine00"` 即得 `alpine00`。但仍建议用返回的 `node_id` 做拓扑定位。
2. **批量接口不再受"≤10"限制**（文档写 up to 10，实测更大）：
   - `node_delete`：单次传 100 个 node_ids，全部 deleted。
   - `link_create`：单次传 50 条 link，全部 success。
   - 即大拓扑（如 100 节点 / 400 链路）只需 ~8-10 次批量调用即可建完。
3. **实测拓扑**：100 Alpine(docker,30 适配器) 节点 + circulant C(100,{1,2,3,4}) 400 链路（每节点度 8，用 adapter 0-7）一次建成，`project_stats` 确认 nodes=100/links=400。
4. **`template_list` 也修好了**：见 [[gns3-mcp-broken-tools]] 更新。

### 2026-06-17 回归测试（stage18）发现
- **`project_create` 的 `auto_close=False` 声明未生效（坑）**：`__init__.py:319` 声明带 `auto_close=False`，但底层 `projects.py:69` 的 `create_project_handler` POST body 只放 `{"name": name}`，**丢弃了 auto_close**。实测 `project_create` 返回 `auto_close: true`，需额外 `project_update(auto_close=false)` 纠正。建议 handler 改成 `json_data={"name": name, "auto_close": params.get("auto_close", False)}`。
- **MCP SSE 通道会中途失效**：所有调用突变为 `-32602: Invalid request parameters`，`/mcp` 重连后恢复。GNS3 server 不在 localhost（`curl 127.0.0.1:3080` 不通），疑 JWT/SSE 过期或后端热更重启致会话失效。
- 8 项本轮改动全部回归通过，详见 `mcp_test_docs/zh/阶段18_本轮改动回归测试.md`。
