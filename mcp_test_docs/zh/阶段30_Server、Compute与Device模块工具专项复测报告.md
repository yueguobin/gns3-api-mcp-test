# GNS3 MCP Server、Compute 与 Device Config 模块工具专项复测报告（阶段 30）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-26 |
| 被测对象 | gns3server **3.1.0a5**（与阶段 29 同一构建，服务器 uptime ~12 分钟起测——阶段 29 后未再重启） |
| 测试范围 | Server 模块 **2 个**（version / statistics）+ Compute 模块 **3 个**（list / get / images）+ Device config **3 个**（device_config_send / device_show_run / vpcs_config_set），正常路径 + 错误路径 + **Jinja2 模板模式** + **数据面闭环验证**（配置→show 落盘、配 IP→互 ping） |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-device-test-0826`（IOU L3 + VPCS×2 + 1 链路 + Alpine docker），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 · ⏭️ 未执行（环境不可达） |

## 0. 环境备注

- 工具数量口径：**server 2 + device config 3 + compute 3 = 8 个，与用户口径一致**。
- **compute_get / compute_images 正常路径本环境不可达**：无任何远程注册 compute（compute_list 空），内置 local compute 的 id 是字符串 `"local"`，过不了两工具的 UUID 参数校验（见 C-1）。错误路径与参数校验路径已覆盖。
- Device 测试节点：R-1（Cisco IOU L3，自带 tag `device_type:cisco_ios_telnet`）、PC1/PC2（VPCS，自带 tag `device_type:gns3_vpcs_telnet`，二者直连链路）、AlpineLinux-1（docker，**无 tag**）。

## 1. 逐工具测试结果

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | server_version | 正常调用 | ✓ | `{"controller_host": "127.0.0.1", "version": "3.1.0a5", "local": false}` 三字段齐全 |
| 2 | server_statistics | 正常调用 ×2（起/终） | ✓ | uptime / computes（local 详情：CPU 型号·24 线程·内存·磁盘·负载）/ projects / nodes / links / capturing / webwireshark 全齐；**两次统计与实际对象状态对齐**（projects.total=0 与 project_list count=0 一致；终态 nodes/links 全 0 与项目删除一致） |
| 3 | compute_list | 正常调用 | ✓ | 空列表（无远程注册 compute），符合描述"不含内置 local"；与 server_statistics 只见 local 互洽 |
| 4 | compute_get 错误·假 UUID | | ✓ | 404 "Compute '…' not found"（已知包裹风格） |
| 5 | compute_get 参数·"local" | | ⚠️ | **pydantic 参数层拒绝**（uuid_parsing，"local" 非合法 UUID）——见 C-1 |
| 6 | compute_images 错误·假 UUID | | ✓ | 404 "Compute ID … doesn't exist"（包裹风格；文案与 compute_get 略异，均清晰） |
| 7 | compute_images 参数·"local" / 非法 emulator | | ⚠️ | "local" 同被 pydantic 拒（C-1）；emulator=`notanemulator` 无独立校验报错（compute 404 先行，枚举校验不存在或靠后） |
| 8 | device_config_send 正常·直接命令 | R-1：`interface lo0` + `ip address 30.30.30.30/32` + `end` | ✓ | 回显完整（conf t → config-if → end）；**show run 复核 Loopback0 配置真实落盘** |
| 9 | device_config_send 正常·Jinja2 模板 | template + vars（n=1, ip=31.31.31.31） | ✓ | 渲染正确（`interface lo1` / `ip address 31.31.31.31 …`），返回的 config_commands 即渲染后命令，下发成功 |
| 10 | device_config_send 错误·假项目 / 假设备名 | | ✓ | 均返回 `[{"error": "Failed to get device info from topology or no valid devices…"}]`——**内嵌 error 不抛异常**（见 E-1 风格观察）；无副作用 |
| 11 | device_show_run 正常 | R-1：`show running-config interface lo0` | ✓ | 全文回显（含配置段），佐证 #8 落盘 |
| 12 | device_show_run 正常·VPCS | PC1：`show ip` | ✓ | **正向发现**：VPCS 节点自带 `device_type:gns3_vpcs_telnet` tag，device_show_run 直接可用（描述的"Docker/Linux not supported"边界不含 VPCS）——输出 VPCS 原生 show ip（NAME/IP/MASK/GATEWAY/MAC…） |
| 13 | device_show_run 错误·无 tag docker | AlpineLinux-1：`ip addr` | ✓ | `status: "failed"` + **高质量报错**：指引设 `netmiko_device_type` 字段或加 `device_type:<type>` tag（含 Web UI 路径），列出已测类型（cisco_ios_telnet / gns3_huawei_telnet_ce / gns3_ruijie_telnet）与当前 tags——与工具描述声明一致 |
| 14 | vpcs_config_set 正常·批量 2 台 | PC1/PC2：`ip 192.168.100.x/24` + `save` | ✓ | 两台并行下发，输出完整（DAD 检查、startup.vpc 保存 done）；**PC1→PC2 ping 5/5 通（0.4–0.8ms）**——配置真实生效、数据面闭环 |
| 15 | vpcs_config_set 错误·假项目 | | ✓ | `status: "failed"` + "Device 'PC1' not found in topology" |
| 16 | vpcs_config_set 错误·非 VPCS 节点 | R-1（IOU）发 `ip 1.1.1.1/32` | ⚠️ | **V-1：不拒绝**——命令原样发进 IOS CLI，设备报 `% Invalid input`，但工具返回 `status: "success"`；无配置副作用（IOS 拒了），可只看 status 会误判 |
| 17 | 终态核对 | 项目删除 → project_list + server_statistics | ✓ | count=0；nodes/links/capturing 全 0，无测试残留 |

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **V-1（阶段 30 新发现）** | 低 | `vpcs_config_set` **无节点类型校验**：对非 VPCS 节点（本轮 IOU）不拒绝，把 VPCS 语法命令发进该设备的 console——IOS 报 `% Invalid input`，工具却返回 `status: "success"`，错误只藏在 output 正文里。调用方只判 status 字段会误判成功（本轮无副作用，因命令被设备 CLI 拒绝）。**→ 08-26 阶段 31 修复复测：已修**（非 VPCS 节点明确拒绝，报错带替代工具指引） | vpcs_config_set |
| **C-1（阶段 30 新发现）** | 低 | `compute_get` / `compute_images` 的 `compute_id` 参数在 MCP 层**强制 UUID 校验**：传内置 local compute 的实际 id `"local"`（即 server_statistics 返回值）直接被 pydantic 拒绝。而 compute_images 工具描述引导"local compute 的 compute_id 从 server_statistics 获取"——**描述与 schema 矛盾**，本地 compute 实际永远不可查（正确路径确实只剩 server_statistics，但描述指了条走不通的路）。**→ 08-26 阶段 31 修复复测：已修**（"local" 可用，compute_get 返回 capabilities、compute_images 返回镜像清单，正常路径首次可达） | compute_get、compute_images |
| **E-1（阶段 30 新观察）** | 信息 | **device 系工具错误契约不统一**（三类并存）：① 拓扑级错误（假项目/假设备名）返回 `[{"error": …}]` **无 status 字段**；② 设备级错误（tag 缺失 / VPCS 找不到）返回 `status: "failed"` + error；③ compute/server 系则抛 MCP Error（"Unknown Status … Original xxx" 包裹）。同为 device_config_send 一个工具内就同时存在 ①② 两种。自动化判错需按位置分别处理。**→ 08-26 阶段 31 修复复测：已修**（拓扑级错误补上 status:"failed"，device 系契约统一；compute/server 系模块间差异保留） | device_config_send、device_show_run、vpcs_config_set |
| **compute_images emulator 无枚举校验** | 信息 | emulator 传非法值（`notanemulator`）无独立报错，compute 404 先行——参数校验缺失或顺序在后。**→ 08-26 阶段 31 复测：维持未修**（低优先级观察） | compute_images |

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| 阶段 19 device 工具结论（IOU config/show 正常、批量 ≤2 台建议） | **复验成立**：单台直接命令 + Jinja2 模板两模式均过，show 复核落盘 |
| 阶段 19 VPCS 结论（ip/save/ping 正常） | **复验成立**，且补齐批量 2 台 + 数据面闭环（互 ping 5/5） |
| "device_type tag not found" 报错（工具描述声明） | **实测确认**（Alpine docker 无 tag），文案质量高（含修复指引） |
| 报错风格（"Unknown Status … Original xxx" 包裹） | compute_get / compute_images 404 维持；device 系为内嵌 error 风格（见 E-1） |
| 阶段 28/29 遗留 | 本轮无关联项（P1-1/P2-1/I-1 已修，未触碰） |

## 4. 统计

- 实测工具：**7 / 8 个完整**（17 个场景）；compute_get / compute_images 正常路径**环境不可达**（无远程 compute，local 被 UUID 校验挡），错误路径 + 参数校验已覆盖
- 通过：Server 2/2、Compute 3/3（错误路径口径）、Device 3/3 正常路径全过；新发现：V-1（vpcs_config_set 无类型校验）、C-1（compute id 描述与 schema 矛盾）、E-1（错误契约三样并存）
- 增强验证：① **数据面闭环**——IOU 配置经 show run 复核落盘、VPCS 配置经互 ping 验证生效；② Jinja2 模板模式首次专项验证（渲染正确且返回渲染后命令）；③ VPCS 可走 device_show_run 的正向确认（tag 机制）；④ 无 tag docker 的报错文案完整指引
- 测试痕迹：临时项目（4 节点 + 1 链路）整体删除，终态 project 0 / 模板 22（未触碰）/ statistics 全 0
