---
name: prefer-mcp-tool-desc-over-stale-memory
description: 用 GNS3 MCP 工具时优先看工具自带 description，不要依赖 memory 里陈旧的用法细节
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 877e239e-bcda-407c-9b1d-75f6325c3a8f
  modified: 2026-07-26T03:02:44.180Z
---

调用 GNS3 MCP 工具时，**优先以系统提示里该工具的 description 为准**（参数怎么填、连哪个 host、命令姿势等），不要去翻 memory 文件找用法。

**Why:** memory 是某次会话的点状观察，会过时；MCP 工具描述随 server 更新经常刷新，是最权威的用法来源。例如 [[gns3-ws-console-usage]] 曾误记 console WS 要用 `127.0.0.1`，用户纠正：应以 `node_console` 返回的 URL（当前为 `10.5.1.1`）为准——这种细节工具描述里就有。

**How to apply:** 遇到"这个工具参数怎么填 / 连哪个地址 / 用什么选项"时，先读该工具的 description 和示例；memory 仅在工具描述没覆盖时作补充参考，且引用前必须在当前环境验证，不能照搬。
