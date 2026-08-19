---
name: gns3-mcp-broken-tools
description: GNS3 MCP 中 template_list / device_command_run 两个工具坏掉的规避方法
metadata: 
  node_type: memory
  type: reference
  originSessionId: db3a48e2-aa5a-4d4f-ac25-22095fda3027
  modified: 2026-08-18T14:46:01.325Z
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

### 2026-08-15 更新：`device_show_run` 拓扑反查曾坏、已修复
曾报 `Failed to get device info from topology`（节点明明有 `device_type:cisco_ios_telnet` 标签且 started）。用户修复 gns3server 后恢复正常，`device_show_run`/`device_config_send` 均可用（Comprehensive Regression Testing 项目 7200 组验证）。另一坑：**一次 `device_config_send` 带 3 台设备时，第 1 台成功、后 2 台报 `netmiko_send_config (failed)`（无细节）**——疑似并发 telnet 会话冲突；拆成单台逐个发即可。

### device_show_run 禁 ping 之外的命令（2026-08-18）
`traceroute` 被 MCP 服务端 forbidden pattern 拦截（用户确认：执行时间长、可能占死 console，故意禁的）。路径验证替代法：看 FIB 下一跳（`show ip route X` 的 `via ... from ...`，from≠via 即 route-server/RR 指纹）或 `ping`（允许）。另：IOS 15.2(4)M 的 ping **不支持 `ttl` 内联关键字**（交互式扩展 ping 才有，netmiko 走不了），TTL 探测法在此镜像不可用。

### netmiko 处理不了交互确认（2026-08-15）
带 y/n 确认的 exec 命令（如 `clear ipv6 ospf process` → "Reset OSPF process? [no]:"）用 `device_config_send` 的 `do` 前缀发会报 `netmiko_send_config (failed)` 且可能把控制台留在半截提示上。**需要重启进程才生效的配置（router-id 等）：直接 `node_stop` + `node_start` 重启节点**（前提：已 `write memory`），重载后配置生效，比折腾交互命令可靠。

参见 [[mcp-backend-optimization]]（命名仍受 `default_name_format` 控制；批量接口已很快）。
