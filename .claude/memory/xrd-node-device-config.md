---
name: xrd-node-device-config
description: XRd docker 节点用 device_config_send/device_show_run 全流程可用（server 2026-08-17 更新后分页已修）；config 后要发 end；server 更新会丢 XRd 配置
metadata: 
  node_type: memory
  type: project
  originSessionId: 885a810e-709d-4232-a2b4-24aa21072034
  modified: 2026-08-17T17:33:15.144Z
---

XRd（ios-xr/xrd-control-plane docker 镜像）节点 + MCP device 工具结论（2026-08-17/18 两次 server 更新后）：

- `device_config_send` / `device_show_run` 对 docker 型 XRd 节点可用（绕开旧认知"docker 节点只能 websocat"，见 [[cisco-telnet-no-ws]]、[[gns3-ws-console-usage]]）。自动登录 admin/cisco、自动进 `configure terminal`。
- **分页问题已修**：早前 `show ipv4 interface brief` 等长表格输出报 `netmiko_multiline (failed)`（根因：console 走 `docker exec`，`terminal length 0` 不生效触发 `--More--`）；2026-08-17 晚 server 更新后长输出、`| include` 管道都正常，无需再控制一页内。
- **两个工具共用同一个 XR CLI 会话**：`device_config_send` commit 后停在 config 模式且不自动退出——config_commands 结尾要带 `end`，否则后续 `device_show_run` 的裸 show 报 Invalid input（或临时用 `do` 前缀）。**`commit` 必须手动发**，否则不生效。
- **server 更新会丢 XRd 已 commit 的配置**：gns3server 更新重启时 XRd 容器被重建，Gi0/0/0/0 的 10.1.1.1/24 丢失（/xr-storage 没扛过去）；更新后要检查/重配。
- MCP server 中途更新后，会话内缓存的旧 schema 会导致所有工具报 `-32602: Invalid request parameters`，`/mcp` 重连即可恢复。
- 其他：XRd 首次启动 hostname 是 `ios`；数据口默认 shutdown，配地址后要 `no shutdown`；"同设备一次别发 2 条 show"是旧版坑，新 server 未复测。
