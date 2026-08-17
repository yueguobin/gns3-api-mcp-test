---
name: cisco-telnet-no-ws
description: Cisco telnet 节点（dynamips/IOU/IOSv）只走 device_config_send/device_show_run，禁止 websocat WS console
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 26925966-39a5-4879-91ca-d19104aeba3a
  modified: 2026-08-15T15:44:56.580Z
---

用户明确要求：cisco_ios_telnet 类型的节点（dynamips/IOU/IOSv）不允许用 WS console 方式（websocat），要用 `device_config_send` / `device_show_run`（netmiko telnet）。WS console 只用于 docker 类节点（FRR/Alpine 等，见 [[gns3-ws-console-usage]]）。

**Why:** telnet 节点走 netmiko 更稳、输出结构化；WS 方式是 docker 节点没有 netmiko 通道时的替代。

**How to apply:** 配 Cisco 设备前确认节点有 `device_type:cisco_ios_telnet` 标签；show/ping 用 `device_show_run`（每设备每次 1 条命令），配置用 `device_config_send`；批量多台失败时单台重试（见 [[gns3-mcp-broken-tools]]）。
