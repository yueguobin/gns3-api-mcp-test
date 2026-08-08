---
name: frr-ospf
description: 给 GNS3 里的 FRR docker 节点（FRR 9/10.x）配置 OSPFv2 + OSPFv3 双栈的技能：编址规划、vtysh 配置模板（无 instance 模式的 FRR 10.x 语法）、ws console 推送姿势、邻接/路由/ping 验证。触发场景：用户要求配置 FRR 路由器的 OSPF/OSPFv3、搭建 FRR 全网状 OSPF 网络、OSPF 排错。
---

# FRR OSPF 配置技能（GNS3 docker 节点）

在 GNS3 中给 FRR docker 节点配 OSPFv2+OSPFv3 双栈。本文全部经 6 节点 full-mesh 实测验证（FRR 10.3，2026-08）。

## 1. 前置：确认节点与链路

- `node_list` 确认节点；用 `link_list` 推导接口↔对端映射（ethN 严格对应 adapter N），**不要猜**。
- full-mesh 6 节点 = 15 链路、每节点 5 端口；缺链路用 `link_create` 批量补齐（compact 格式 `[node_id, adapter, port, ...]`）。
- 全节点 `node_start_all`，等 ~10s 容器起来。
- FRR 镜像 console 主进程是 **vtysh**（`show daemons` 可见 mgmtd/zebra/ospfd/ospf6d 全启）。

## 2. 编址规则（沿用 100-node-iou 约定，可复用到任意 N 节点 mesh）

- Loopback：`10.1.0.N/32` + `2026::N/128`
- 链路 R_A↔R_B（A<B）：IPv4 `10.1.AB.0/30`（AB=编号拼接，如 12、34），IPv6 `2026:AB::/64`；**小号取 `.1`/`::1`，大号取 `.2`/`::2`**
- 所有网段都在 `10.1.0.0/16` 内 → OSPFv2 一条 `network 10.1.0.0/16 area 0` 全覆盖

## 3. 配置模板（FRR 10.x 语法，每节点一份）

> **关键差异（vs 8.x/9.x）**：FRR 10.x 无 OSPF instance 模式。
> ❌ `router ospf 1` / `ip ospf 1 area 0` → 报 "instance not running"
> ✅ `router ospf`（无 pid）+ `network` 语句；接口模式用 `ip ospf area 0`
> `router ospf6` 仍存在，但块内 router-id 命令是 **`ospf6 router-id X`**（`router-id` 会被静默忽略、config 块为空）

```text
conf t
int eth0                        ; 每端口重复，按 link_list 映射
 ip add 10.1.12.1/30
 ipv6 address 2026:12::1/64
 ip os ne point-to-point        ; 全缩写等价 ip ospf network point-to-point
 ipv6 ospf6 network point-to-point
 ipv6 ospf6 area 0
int lo
 ip add 10.1.0.1/32
 ipv6 address 2026::1/128
 ipv6 ospf6 area 0
end
conf t
router ospf
 router-id 10.1.0.1
 network 10.1.0.0/16 area 0     ; v2 用 network 覆盖 lo + 全部链路
end
conf t
router ospf6
 ospf6 router-id 10.1.0.1       ; 注意是 ospf6 router-id，不是 router-id
end
wr                              ; 写 /etc/frr/frr.conf，容器重启自动加载
```

## 4. ws console 推送姿势（node_console → websocat）

```bash
{ sleep 2; printf 'vtysh\r\n'; sleep 1.2; printf 'end\r\n'; sleep 0.4;
  cmds=(...上述命令...); for c in "${cmds[@]}"; do printf '%s\r\n' "$c"; sleep 0.3; done;
  sleep 3~4; } | timeout 30 websocat -t --no-close '<ws_url from node_console>'
```

- **流开头固定 `vtysh` + `end` 兜底**：容器会话可能停在 bash（裸 `exit` 会把 vtysh 挤到 bash）或任意模式（见过 `(config-if)#`）。已在 vtysh 时这俩命令只是无害报错。
- 结尾**不要发裸 `exit`**（会退出 vtysh 掉 bash，污染下一个会话）。
- 命令尾必须 `\r\n`；token 10 分钟过期，每节点配置前重新 `node_console`。
- **websocat 的 timeout 必须贴输入时长**（`--no-close` 下 stdin EOF 后 websocat 不退出，墙钟时间 = timeout 值）：46~50 条配置（~20s 输入）用 `timeout 30`；2~3 条验证命令（~6s 输入）用 `timeout 15`；带 ping 的验证（~15s 输入）用 `timeout 20`。
- **Bash 工具级 timeout 同样要贴**：= 命令内 timeout + 前导 sleep（验证带 `sleep 20` 收敛 + 命令 `timeout 15` → 工具给 45s；纯验证 → 20s；配置 → 32s）。别随手给 60s/120s——设大了用户会骂。
- 输出 grep 检查：`grep -a -E '% |saved|Configuration'`；出现 "Building Configuration... [OK]" 即保存成功。
- FRR 10.3 `wr` 输出：`Building Configuration... Integrated configuration saved to /etc/frr/frr.conf [OK]`

## 5. 验证

先 `terminal length 0` 关分页（避免 show 卡住）：

```text
show ip ospf neighbor       ; 期望每节点 N-1 个 Full/-（full-mesh 6 节点 → 5 个）
show ipv6 ospf6 neighbor    ; 期望 N-1 个 Full/PointToPoint
show ip route ospf          ; loopback /32 + 链路 /30，非直连带 ECMP 双路径
show ipv6 route ospf6       ; /128 + /64，via fe80:: link-local
ping 10.1.0.6               ; 双栈 ping 非直连 loopback，期望 0% loss
ping 2026::6
```

- vtysh 的 `ping` **没有 source 参数**（只有 `ping WORD|ip|ipv6`，按地址族自动选），带 source 会报 Unknown command。
- 配置完成后建议 ping 前等 ~20s 收敛（dead timer 40s）。

## 6. 坑速查

| 现象 | 原因 | 解法 |
|---|---|---|
| `bash: configure: command not found` | 会话在 bash，没进 vtysh | 流开头加 `vtysh`；别发裸 `exit` |
| `% [ospfd]: ... instance that is not running` | 用了 `ip ospf 1 area 0` | 去掉 pid |
| `% OSPF is not running in instance mode` | `router ospf 1` | 用 `router ospf` |
| `router ospf6` 块 config 为空 | 用了 `router-id` | 用 `ospf6 router-id` |
| `ping ... source ...` Unknown | vtysh ping 无 source | `ping <addr>` / `ping 2026::6` |
| websocat 等满 timeout 才结束 | `--no-close` 特性 | timeout 贴输入时长 |
| Bash 工具级 timeout 给了 60s | 没贴输入时长 | 工具 timeout = 命令 timeout + 前导 sleep（配置 ~32s、验证 ~20s） |
| node_file_* 对 docker 404 | 仅 qemu/iou 支持 | 只能走 ws console |

## 7. 相关

- memory：[[1000-frr-node]]（6 节点 full-mesh 实测记录）、[[100-node-iou-ospf]]（IOU 版同编址）、[[gns3-ws-console-usage]]（ws 连接模板）
