---
name: gns3-mcp-double-envelope
description: "GNS3 MCP 返回结果双重包裹（text 里套 {\"type\":\"text\",\"text\":\"...\"}），取数据要先解包"
metadata: 
  node_type: memory
  type: project
  originSessionId: e87c1022-af7f-4c93-b1c1-82746f211c74
---

GNS3 MCP server（`My_GNS3_Server`，SSE transport）返回的工具结果存在**双重包裹**：text content block 的 `.text` 本身是一个 JSON 字符串 `{"type":"text","text":"<真实数据的 JSON 字符串>"}`。直接 `json.loads(b.text)` 得到的是 envelope，取不到真实字段。

例：`appliance_list` 的 text 实为 `{"type":"text","text":"{\"appliances\":[...]}"}`，要解开两层才能拿到 `appliances`。

**Why:** 写手工测试脚本解析 MCP 返回时会踩坑，尤其是需要从 list 工具里提取 id 再喂给 get 工具的场景（appliance/compute/image/template 等都有此现象）。

**How to apply:** 复用 `mcp-manual-test/_lib/gns3_mcp.py` 里的 `payload()` 函数——自动走 `content[0].text` → `json.loads` 一次（与 Claude Code 行为一致）。提取 id 用该函数即可，无需自己递归解嵌套。格式化展示用 `format_result()`，它也只显示 `content` 块。另见 [[gns3-mcp-broken-tools]]、[[mcp-backend-optimization]]。

**已验证（非序列化伪影）：** 这是后端行为，不是测试脚本 `json.dumps` 造成的——直接 `repr(result.content[0].text)` 仍为 envelope。取值路径：`result.content[0].text` → `json.loads` 一次（_unwrap_envelope 自动处理后端可能的额外嵌套）。

**注意：** `structuredContent` 是 Python MCP SDK 本地解析后附加的字段，**不属于 MCP 协议标准**，Claude Code（TypeScript SDK）只认 `content`。测试代码不应依赖 structuredContent。`_lib/gns3_mcp.py` 的 `payload()` 和 `raw_result()` 均已排除此字段。
