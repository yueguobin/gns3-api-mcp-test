# Memory Index

- [MCP 后端优化记录](mcp-backend-optimization.md) — 批量接口提速/精简、auto_close、命名受 default_name_format 控制
- [MCP 坏工具规避](gns3-mcp-broken-tools.md) — template_list / device_command_run 报错的绕过方法（反查 template_id；用 do 前缀跑 show/ping）
- [MCP 返回双重包裹](gns3-mcp-double-envelope.md) — 结果 text 里套 {"type":"text","text":"..."}，取数据要先解包（用 _lib/gns3_mcp.py 的 _unwrap_envelope）
