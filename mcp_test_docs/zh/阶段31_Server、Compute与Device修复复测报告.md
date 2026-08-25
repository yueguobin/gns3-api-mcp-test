# GNS3 MCP Server、Compute 与 Device Config 修复复测报告（阶段 31）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-26 |
| 被测对象 | gns3server **3.1.0a5**（阶段 30 后用户更新修复并重启，uptime 238s 起测；MCP `/mcp` 重连） |
| 复测范围 | 阶段 30 三项发现：**V-1**（vpcs_config_set 无节点类型校验）· **C-1**（compute_get/compute_images 强制 UUID，"local" 被拒、描述与 schema 矛盾）· **E-1**（device 系错误契约不统一）+ emulator 枚举校验观察项 + 正常/错误路径回归 |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-device-retest-0826`（IOU L3 + VPCS + Alpine docker），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 |

## 0. 环境备注

- 服务器重启后 `/mcp` 重连（既往经验一致）；阶段 30 → 31 之间无其他变更。
- 复测节点：R-1（IOU L3）、PC1（VPCS）、AlpineLinux-1（docker 无 tag）——与阶段 30 同构。

## 1. 逐项复测结果

| # | 项 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | **C-1 修复复测·compute_get** | `compute_id="local"` | ✓ **已修** | 返回 local compute 完整详情：protocol/host/port/user/connected + **capabilities**（version、13 种 node_types、platform、cpus/memory/disk）——描述引导的路径走通，正常路径**首次可达** |
| 2 | **C-1 修复复测·compute_images** | `"local"` + emulator=qemu | ✓ **已修** | 返回 50 个 qemu 镜像（filename/path/md5sum/filesize）——local compute 镜像查询打通 |
| 3 | compute_images·docker 模式 | `"local"` + emulator=docker | ✓ | 11 个 docker 镜像（alpine/srlinux/frr/xrd 等）——第二 emulator 路径覆盖 |
| 4 | compute_get 错误回归·假 UUID | | ✓ | 404 "Compute '…' not found"（文案不变） |
| 5 | compute_images 错误回归·假 UUID + 非法 emulator | | ⚠️ | 404 "Compute ID … doesn't exist" 维持；**emulator 枚举校验仍未加**（`notanemulator` 无独立报错，被 compute 404 掩盖——观察项维持） |
| 6 | compute_list 回归 | | ✓ | 空列表（无远程注册），与阶段 30 一致 |
| 7 | **E-1 修复复测** | device_config_send 假项目 | ✓ **已修** | 拓扑级错误从裸 `[{"error": …}]`（无 status）改为 **`status: "failed"` + error**——device 系错误契约统一为同一风格 |
| 8 | **V-1 修复复测** | vpcs_config_set 对 R-1（IOU） | ✓ **已修** | 不再把命令发进 IOS CLI，明确拒绝：`status: "failed"`，报错 **"Device 'R-1' is a iou node, not a VPCS node; use device_config_send / device_show_run for network devices"**（含正确工具指引） |
| 9 | vpcs_config_set 错误回归·假项目 | | ✓ | `status: "failed"` + "Device 'PC1' not found in topology"（风格不变） |
| 10 | device_show_run 错误回归·无 tag docker | AlpineLinux-1 | ✓ | 高质量报错文案逐字维持（netmiko_device_type 指引 + 已测类型清单 + 当前 tags） |
| 11 | vpcs_config_set 正常回归 | PC1：`ip 192.168.50.1/24` + `save` | ✓ | 输出完整（DAD、startup.vpc 保存 done）；`show ip` 复核 IP 生效——**类型校验未误伤正常路径** |
| 12 | device_config_send 正常回归 | R-1：lo0 / 40.40.40.40 | ✓ | 下发成功；`show running-config interface lo0` 复核落盘 |
| 13 | device_show_run 正常回归 | R-1 + PC1（VPCS 路径） | ✓ | IOU show run 全文；PC1 `show ip` 显示刚配 IP——VPCS 可走 device 工具的正向行为不变 |
| 14 | 终态核对 | 项目删除 → project_list + server_statistics | ✓ | count=0；nodes/links/capturing 全 0，无残留 |

## 2. 修复质量评价

- **C-1**：不止放宽了校验——`compute_get("local")` 返回的 capabilities（node_types 全集、硬件规格）是 server_statistics 里没有的信息，local compute 查询现在有了独立价值；compute_images 双 emulator（qemu 50 / docker 11）与 image_list（57，全 emulator 合计）口径互洽。
- **V-1**：报错文案给出替代工具指引（"use device_config_send / device_show_run for network devices"），自动化可按 `status` 字段可靠判错。
- **E-1**：统一后 device 系三类错误（拓扑级/设备级/VPCS 找不到）全部 `status: "failed"` + error，契约一致；compute/server 系仍为 MCP Error 包裹风格（模块间差异保留，属可接受）。

## 3. 已知问题复验状态

| 项 | 本轮状态 |
|---|---|
| V-1（vpcs_config_set 无类型校验） | **已修复**——非 VPCS 节点明确拒绝 + 指引 |
| C-1（compute_id 强制 UUID，描述矛盾） | **已修复**——"local" 可用，描述指引成立；正常路径首次覆盖 |
| E-1（device 系错误契约不统一） | **已修复**——拓扑级错误补上 status:"failed" |
| emulator 枚举校验缺失 | **维持**——非法值仍被 compute 404 掩盖（低优先级观察） |
| 报错风格（"Unknown Status … Original xxx" 包裹） | compute 系 404 维持不变 |

## 4. 统计

- 复测场景：14 个，**12 通过 + 2 通过但有注意点**（emulator 校验维持）；阶段 30 三项发现（V-1 / C-1 / E-1）**全部修复确认**
- 修复质量增强点：① compute_get("local") capabilities 信息量超预期；② V-1 报错带替代工具指引；③ E-1 统一后正常路径无回归（IOU/VPCS 四条正常链路全过）
- 测试痕迹：临时项目（3 节点）整体删除，终态 project 0 / 模板 22（未触碰）/ statistics 全 0
