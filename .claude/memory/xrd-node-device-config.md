---
name: xrd-node-device-config
description: XRd docker 节点用 device_config_send/device_show_run 全流程可用（server 2026-08-17 更新后分页已修）；config 后要发 end；server 更新会丢 XRd 配置
metadata: 
  node_type: memory
  type: project
  originSessionId: 885a810e-709d-4232-a2b4-24aa21072034
  modified: 2026-08-19T07:00:39.326Z
---

XRd（ios-xr/xrd-control-plane docker 镜像）节点 + MCP device 工具结论（2026-08-17/18 两次 server 更新后）：

- `device_config_send` / `device_show_run` 对 docker 型 XRd 节点可用（绕开旧认知"docker 节点只能 websocat"，见 [[cisco-telnet-no-ws]]、[[gns3-ws-console-usage]]）。自动登录 admin/cisco、自动进 `configure terminal`。
- **分页问题已修**：早前 `show ipv4 interface brief` 等长表格输出报 `netmiko_multiline (failed)`（根因：console 走 `docker exec`，`terminal length 0` 不生效触发 `--More--`）；2026-08-17 晚 server 更新后长输出、`| include` 管道都正常，无需再控制一页内。
- **两个工具共用同一个 XR CLI 会话**：`device_config_send` commit 后停在 config 模式且不自动退出——config_commands 结尾要带 `end`，否则后续 `device_show_run` 的裸 show 报 Invalid input（或临时用 `do` 前缀）。**`commit` 必须手动发**，否则不生效。
- **server 更新会丢 XRd 已 commit 的配置**：gns3server 更新重启时 XRd 容器被重建，Gi0/0/0/0 的 10.1.1.1/24 丢失（/xr-storage 没扛过去）；更新后要检查/重配。
- MCP server 中途更新后，会话内缓存的旧 schema 会导致所有工具报 `-32602: Invalid request parameters`，`/mcp` 重连即可恢复。
- 其他：XRd 首次启动 hostname 是 `ios`；数据口默认 shutdown，配地址后要 `no shutdown`；"同设备一次别发 2 条 show"是旧版坑，新 server 未复测。

**2026-08-19 更新（⑧组部署实证）**：
- 重建后的 "XRd Control Plane" 模板（1e5df5c0）**自带 `netmiko_device_type: cisco_xr_telnet`**，节点不需要 device_type tag，device 工具直接可用（旧模板 404 后节点 tags 空曾报 "no device type found"）。
- **gns3server 纯重启后已 commit 的配置存续**（/xr-storage 扛住了；8-17 丢配置那次是 server 更新重建容器）。commit 即持久，无需额外保存命令。
- **XR 24.4 BGP 语法三坑**：① eBGP 默认零路由收发，必须 `route-policy PASS / pass / end-policy` 挂邻居 AF 的 in/out；② `no bgp enforce-first-as` 报 Incomplete，XR 写法 `bgp enforce-first-as disable`；③ **AF 子模式里敲 `neighbor X` 会跳出 AF 进全局 neighbor 上下文**，route-policy 挂不进、后续命令全体错位——正统三层结构 `neighbor X` → `address-family …` → `route-policy …`（提示符 config-bgp-nbr-af），邻居的 AF 激活即由此产生。
- OSPF：`router ospf 1 / area 0 / interface X / network point-to-point`；ospfv3 必须先 `address-family ipv6 unicast` 再进 area；默认注入在 ospf 进程级和 ospfv3 AF 级各一条 `default-information originate always`。
- ping 非交互：`ping ipv4 <dst>` / `ping ipv6 <dst>`（默认 5 发即返回）；XRd 数据面是 Linux 内核，跨组 RTT 仅 3-7ms。
