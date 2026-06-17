---
name: gns3-mcp-broken-tools
description: GNS3 MCP 中 template_list / device_command_run 两个工具坏掉的规避方法
metadata: 
  node_type: memory
  type: reference
  originSessionId: db3a48e2-aa5a-4d4f-ac25-22095fda3027
---

## GNS3 MCP 两个坏掉的工具 + 规避（2026-06-16 验证）

本环境（GNS3 3.1.0.dev4）的 MCP 服务里，以下两个工具返回值包装有 bug，调用即报错：

1. **`template_list`**：报 `1 validation error for DictModel / dict_type`——它把 MCP 信封 `[{type,text}]`（内含 `"count": N` 的真实数据）直接喂给了期望 dict 的 `DictModel`。带不带 `fields` 都一样。
2. **`device_command_run`**：报 `Error executing tool device_command_run: 'commands'`（`KeyError('commands')`），无论设备是否就绪。疑似内部读了 `["commands"]` 而非 `["show_commands"]`。

### 2026-06-16 更新：`template_list` 已修复
后端热更+重启后，**`template_list` 已正常**（返回 15 个模板，不再报 DictModel 错误）。可直接 `template_list(fields=[template_id,name,template_type,category])` 拿模板；docker 模板用 `template_get(template_id=...)` 看 `adapters` 数（Alpine Linux 模板 id `ef7d4150-d6d1-4ff4-816b-403e2235776e`，30 适配器）。
`device_command_run` 修复情况未测，仍建议先用 `device_config_send` + `do` 前缀。

### 规避（历史，template_list 已修后多数不再需要）
- **查模板**（旧）：不要用 `template_list`。打开任意含目标类型节点的既有项目，`node_list(fields=[name,node_type,template_id])` 反查 `template_id`，再 `template_get(template_id=...)` 拿细节。本环境 IOU L3 模板 id = `cc8dbf81-03b7-4dc5-99fc-f2947cb4998e`（名 `Cisco IOU L3`，镜像 `x86_64_crb_linux-adventerprisek9-ms.iol`，4 eth 适配器）。
- **跑 show/ping**：不要用 `device_command_run`。改用 `device_config_send` 传 `config_commands=["do show ip interface brief", "do ping 10.x.y.z"]`——它先进 enable+`configure terminal`，`do` 前缀在 config 模式下执行 exec 命令，控制台输出会随结果回传，完全可用。

参见 [[mcp-backend-optimization]]（命名仍受 `default_name_format` 控制；批量接口已很快）。
