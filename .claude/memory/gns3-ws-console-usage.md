---
name: gns3-ws-console-usage
description: GNS3 WebSocket console 正确连接姿势（websocat 选项、127.0.0.1、BusyBox 命令差异）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7729fc62-68f9-4e13-868d-c39a05902088
  modified: 2026-07-26T02:59:43.667Z
---

通过 MCP `node_console` 拿 ws URL 后，用 websocat 连接配置 Linux/Docker 节点（Cisco 设备直接用 `device_config_send`，不走 ws）。

**Why:** device_config_send 是 netmiko（只认 Cisco IOS），对 Alpine/BusyBox 等 Docker 容器无效，必须走 ws console 发 shell 命令。

**How to apply:**
- ws URL 的 host **直接用 `node_console` 返回值**（当前环境为 `10.5.1.1`），不要改成 `127.0.0.1`（曾误记 127.0.0.1 更稳，用户纠正：应以 node_console 返回的 URL 为准）。
- 连接模板（关键是 `--no-close` + 保持 stdin 打开，否则 heredoc EOF 立刻关连接、读不到输出）：
  `{ printf '\r\n<cmd>\r\n'; sleep 6; } | timeout 9 websocat -t --no-close "ws://127.0.0.1:3080/v3/projects/<pid>/nodes/<nid>/console/ws?token=<jwt>"`
- 命令行尾必须 `\r\n`。token 10 分钟过期，重连要重取（`node_console` 每次发新 token）。
- **controller token revoked 坑**：GNS3 server 重启后 admin 旧 token 全部 revoke，新 token 也立即失效（报 `Token has been revoked for 'admin'`）；需让 server 侧重置鉴权（修复后 token payload `ver` 会变，如 0→1）。
- Alpine/BusyBox 不支持 `ip -br addr`（那是 iproute2），用 `ip addr`；配 IP `ip addr add 10.4.12.1/30 dev eth1`。
- GNS3 docker 容器 eth0/1/2 严格对应 adapter 0/1/2（MAC 末字节 :00/:01/:02 可佐证）。
- 持久化写 `/etc/network/interfaces`（GNS3 docker 的 `/gns3/init.sh` 启动时执行 `ip link set ethN up` + `ifup -a -f` 自动生效；且 `/etc/network` 是 bind mount 持久卷 `GNS3_VOLUMES=/etc/network`，容器销毁重建也保留文件）。
- **关键坑：BusyBox ifup 不认 CIDR**——`address 10.4.12.1/30` 会让 ifup 报 `don't have all variables for ethN/inet`，全部接口 ifup 失败、IPv4 不恢复（运行时 `ip addr add CIDR` 没问题，因 iproute2 认 CIDR；但给 ifup 的文件必须 `address 10.4.12.1` + `netmask 255.255.255.252` 分开写）。曾因此导致容器重启后网络全丢。
- 重启 docker 节点验证持久化要用 **node_stop → node_start**（销毁重建路径，跑 init.sh），不要用 node_reload（reload 后 console 曾无响应、行为不一致）。
- ws 写多行文件避免 `\r` 污染配置行：host 上 `base64 -w0` 编码内容，ws 发 `echo <b64> | base64 -d > /file`。直接 heredoc 会让每行带 `\r` 导致 ifup 解析失败。
- Alpine 不跑 OSPF，docker 节点接骨干只作为 IP 主机；骨干路由器学不到容器网段路由（除非装 FRR/BIRD 或加静态路由）。

参见 [[gns3-mcp-double-envelope]]（node_console 返回值也要先解包再取 ws_url）。
