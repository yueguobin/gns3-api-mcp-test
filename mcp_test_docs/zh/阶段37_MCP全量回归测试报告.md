# GNS3 MCP 80 工具全量回归测试报告（阶段 37）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-11-03 |
| 被测对象 | gns3vm21（192.168.101.21）gns3server **3.1.0.dev8+6a4cbe39c**（server_version 实测，带 build hash）；本地 controller compute |
| 被测改动 | gns3-server 提交 6a4cbe39c「copilot 复用 MCP 工具桥；抽取共享 device runner」——MCP 侧仅 `gns3server/agent/mcp/device_config.py` 改为纯委托（device_config_send / device_show_run / vpcs_config_set），Jinja2 渲染从 MCP handler 下移进 runner；工具注册文件（agent/mcp/__init__.py）未改，80 个工具的名称/描述/schema 不变 |
| 测试范围 | 80 个工具全量：Project 14 / Template 5 / Node 19 / Link 13 / Drawing 7 / Snapshot 4 / Appliance 3 / Image 5 / Server+Compute 5 / Device 3 / Skill 2；重点深测 device 三工具（重构直接目标）：直发、Jinja2 模板、错误契约、持久化 |
| 未覆盖（环境/安全限制） | ① 远程 compute（compute_list 为空，全本地）；② appliance_install 成功路径（本机无 MikroTik 镜像，仅验 409 拒绝）；③ image_prune（语义=删除所有未被模板引用的镜像，属破坏性，**故意不测**）；④ device 工具只实测 FRR docker + VPCS，IOS/IOU/dynamips 未逐类型重测（依赖同一 runner，行为为原样搬移）；⑤ node_console_exec 仅冒烟（本提交未触碰该文件，阶段36 已 36 项深测） |
| 测试方式 | 仅经 MCP 工具接口；测试项目 `Stage37-MCP-Reg`（459f8f20…）与 `Stage37-Template-Check`（befcfeb0…），测毕全部删除，11 个测试新建模板已删，基线核对恢复 |
| 结果标记 | ✓ 通过 · ⚠ 注意/存量缺陷 · 未测 |

## 1. 结论

**本提交对 MCP 80 个工具没有引入回归。** device 三工具走新共享 runner 后，直发配置、Jinja2 模板渲染、错误契约、配置持久化、跨调用落点全部按基线工作；其余 77 个工具的行为与既有基线一致（数据面 delay 实测 RTT≈100.5ms、抓包 pcap 实取、快照恢复四维核对、中文/转义逐字保真等均复验）。

**发现两个存量缺陷（均非本轮引入）**：① `vpcs_config_set` 混批里只要有一台不合格设备，同批合法 VPCS 的命令被整批跳过且不回报；② `marker_definition` 的 update 不带 `bpf` 必被拒（必须重发 bpf 原值）。

**一个破坏性工具未测**：`image_prune`（会删除所有未被模板引用的镜像）。

## 2. 测试项

### 测试01 Server/Compute 基础面 ✓
`server_version` 返回 3.1.0.dev8+6a4cbe39c；`server_statistics` 返回 computes/项目/节点/链路统计；`compute_list` 空（无远程）；`compute_get(local)` 返回 capabilities（node_types 13 种、ubridge_tc netem 11 种、ebpf/cbpf、tap/vxlan 全 true）；`compute_images(docker)` 返回 15 个镜像。

### 测试02 Project 创建/查询/统计 ✓
`project_create` 建 Stage37-MCP-Reg（auto_close=false，status=opened）；`project_get` 回读一致；`project_stats` 空项目 0/0/0/0/0。

### 测试03 Project 更新 ✓
`project_update` 改 scene_width 2000→3000、show_grid false→true，返回体已更新。

### 测试04 Project README 往返保真 ✓
`project_readme_update` 写入含中文、Ω、✓、中文引号「」、`&lt;&amp;&gt;`、日期、服务器版本号的 Markdown；`project_readme_get` 逐字一致。

### 测试05 Project 锁定语义 ✓
空项目 `project_lock` 后 `project_locked`=false（基线：空项目恒 false）；有节点/绘图后 lock→locked=true；`project_unlock` 后恢复 false。

### 测试06 Project 列表/关闭/重开 ✓
`project_list` 返回 18 个项目（测试项目在内）；`project_close` 后 `project_open` 正常重开（节点/绘图保留）。

### 测试07 Project 复制 ⚠
`project_duplicate`（不带 reset_mac_addresses）成功：6 个节点全部重生成 node_id（与源项目无重复），status=closed；副本节点列表核对一致，随后 `project_delete` 删除。
带 `reset_mac_addresses=true` 时**裸报 Error**——存量缺陷路径（见观察四）。

### 测试08 Template 五工具 ✓
`template_list` 返回 27 个模板；`fields=["name","template_type"]` 过滤生效；`template_get(name="VPCS")` 成功；`template_create` 建 Stage37-VPCS → `template_update` 改名 Stage37-VPCS-Renamed（updated_at 变化）→ 被占用时 `template_delete` 拒绝（409）→ 解除占用后删除成功。

### 测试09 Node 创建/列表/查询/更新 ✓
`node_create` 批量 5 节点（2×VPCS + FRRDocker + 自建模板 PC3 + Ethernet switch）：按提交序返回、默认名递增去重（PC1/PC2/FRRDocker-1/PC3/Switch1）、Switch1 直接 started；`node_list`/`node_get` 的 fields 过滤生效（含 ports/MAC）；`node_update` 改名、挪位、打 `device_type:` tag 均生效，label 跟随改名。

### 测试10 Node 启停/挂起 ✓
`node_start` 批量 3 节点成功；`node_suspend` 对 VPCS 诚实拒绝（405 系，客户端显示 Error executing tool）、对 docker 生效为 suspended；再 `node_start` 恢复 started。

### 测试11 Node 批量启停/挂起 ✓
`node_start_all` 全部启动；`node_suspend_all` 返回 All nodes suspended（docker suspended、VPCS 保持 started——批量静默跳过，见观察三）；`node_stop_all` 全部 stopped（Switch1 保持 started，stateless 正常）。

### 测试12 Node 复制 ⚠
`node_duplicate`：停止节点 PC3-Moved 复制成功（新 node_id、console 5007、名字 PC3-Moved1）；运行中的 PC2 复制被 compute 侧拒绝（controller 无显式拦截，存量行为）。

### 测试13 Node 文件四件套字节保真 ✓
`node_file_write` 写含中文/Ω/✓/引号/`<> &`/tab 的文件 → `node_file_get` 逐字一致（total_bytes=95）→ `node_file_list` 显示 UTF-8 文本与大小 → `node_file_delete` 删除成功。

### 测试14 Link 创建/查询 ✓
`link_create` 批量 3 条：2 条成功（均为 kernel_datapath=true），1 条因 VPCS 无 1/0 端口诚实拒绝；改用 PC3 建第三条成功；`link_list` 3 条全 kernel；`link_get`、`node_links` 正确列出两端。

### 测试15 Link 可用 filter 清单 ✓
`link_available_filters` 返回 kernel 链 13 种 filter（frequency_drop/packet_loss/delay/corrupt/bpf/rate/reorder/gemodel/duplicate/seed/limit/quota/window_drop），参数与范围齐全。

### 测试16 Link filter 数据面实证 ✓
`link_update` 设 `delay=[50]`；PC1 ping PC2 RTT 稳定 100.4–100.6ms（双向各 50ms，与基线「delay 双向叠加」一致）；`filters={}` 清空成功。

### 测试17 vpcs_config_set 纯 VPCS 批 ✓
两台 VPCS 批配 IP 成功（含 "Checking for duplicate address..." 提示与回显）；`show ip` 查询批返回 success 输出；单独调用 `ip`/`show ip` 均正常。

### 测试18 vpcs_config_set 混批短路 ⚠
`[{PC1: ip ...}, {PC2: ip ...}, {FRRDocker-1: show version}]` 只返回 FRRDocker 的 failed 条目（带"use device_config_send"指引），**PC1/PC2 的命令未执行、IP 仍 0.0.0.0/0、返回中无 success 条目**；`[Switch1, PC1]` 时整调用裸报 Error（全局异常通道，无 in-band 明细）。见缺陷一。

### 测试19 Link marker 三动作 ✓
`link_marker create`（icmp、tag 37、红色）返回完整配置；`update enabled=false` 生效；`delete` 成功；`link_get` 中 markers 归空。

### 测试20 Link 抓包闭环 ✓
`link_capture_start` 成功（文件名 PC1_0-0_to_PC2_0-0.pcap）；ping 后 `link_capture_stop`；`link_capture_download` 返回带 ticket 的 curl URL；按原样执行 curl 下载 pcap，tcpdump 读出 ARP 请求/应答 + 5 组 ICMP echo request/reply，时间戳与 delay 50ms 吻合。

### 测试21 Node 隔离/恢复 ✓
`node_isolate(PC1)` 后 `link_get` 显示 suspend=true（filter 保留 delay）；`node_unisolate` 后 suspend=false。

### 测试22 Link 复位 ✓
`link_reset` 成功，filters 保留（delay=[50] 仍在），返回完整 link 体。

### 测试23 marker_definition 项目级定义 ⚠
`create`（arp、tag 99）成功并扇出到全部 3 条链（list 返回 link_ids 3 条）；`list` 正确；`update` 只传 color **裸报 Error**，带 bpf=arp 后 color 更新成功（缺陷二）；`delete` 后链上继承副本清除。

### 测试24 device_show_run 直发（FRR vtysh）✓
`show version` 返回 FRRouting 10.3、900 字符 configure 行单行完整；`show running-config` 回读正确。

### 测试25 device_config_send 直发 + 自动收尾 ✓
3 条 config_commands（configure terminal/interface lo/description）：runner 自动进 config 模式、逐行执行、自动 end；重复 configure terminal 报 Unknown 属 FRR 特性；`description stage37-jinja` 经 show running-config 确认持久化。

### 测试26 device_config_send Jinja2 模板 ✓
template=`interface {{ lo }}\ndescription {{ desc }}` + vars 渲染后执行，返回 config_commands 为展开后的两行，配置生效。

### 测试27 device_show_run Jinja2 模板 + 无效模板 ✓
template=`show ip {{ proto }} neighbor` + vars 渲染为 `show ip ospf neighbor` 并执行（FRR 回 "OSPF is not enabled in vrf default"，属设备实情）；无效模板 `{{ proto }` 返回 in-band `{"status":"failed","error":"Template rendering failed: unexpected '}'"}`——模板渲染下移进 runner 后错误路径完好。

### 测试28 device 错误契约（无 device_type）✓
对无 tag 的自建模板节点调用 `device_show_run`，返回 in-band failed，错误含指引（设 netmiko_device_type 或加 device_type: tag、附 Web UI 操作路径、列出 tested types、回显 Current tags: []）。

### 测试29 device_skill_get ✓
`action=list` 返回 8 个技能；`device_type=frr_vtysh, topic=ospf` 返回 OSPFv2/v3 主题正文（含 FRR 10.x 无 instance 模式、ospf6 router-id 陷阱）。

### 测试30 injection_skill_get ✓
`action=list, context=["ospf"]` 返回 6 个匹配故障类别（总数 51）；`injection_ospf_issues, detail=index` 返回 48 个故障条目。

### 测试31 node_console_exec 冒烟 ✓
FRRDocker-1 落 vtysh，`echo` 被 vtysh 判 Unknown（正常）；启动未就绪的协商字节 `��\u0018` 前缀复现（阶段36 已知缺陷，非本轮）。

### 测试32 Drawing 七工具 ✓
`drawing_create_rectangle`（fill none/stroke）、`drawing_create_ellipse`（透明度 0.8）、`drawing_create_text`（中文 + Ω + ✓ + `& <引用>` 自动转义、两行 line_height 25、宽高计算返回）；`drawing_list` 3 条；`drawing_get` 单条；`drawing_update` 挪位 + locked=true；锁定状态 `drawing_delete` 拒绝（409），解锁后删除成功。

### 测试33 Snapshot 四工具 ✓
`node_stop_all` 后 `snapshot_create` 成功；删 drawing + 删节点制造漂移；`snapshot_restore` 后四维核对全中：节点原 node_id 回来、drawing 中文逐字回来、项目设置（scene_width=3000 等）保留、status=opened；`snapshot_list` 恢复后保留条目；`snapshot_delete` 后列表为空。

### 测试34 Appliance 三工具 ⚠
`appliance_list` fields 过滤返回 228 个（含 builtin 标记）；`appliance_get(MikroTik CHR)` 返回 registry_version、images 7 个版本、versions 映射；`appliance_install`（7.22.1，镜像不在本机）按预期拒绝（客户端显示 Error executing tool，底层 409 系）。

### 测试35 Image 五工具 ⚠
`image_list` 73 个（含 3 个 availability=missing）；`image_get` 单条；`image_delete(frr-8.2.2.qcow2.part)` 成功（僵尸 .part 条目，文件本已缺失）；`image_install` 扫描成功：created 11 个模板（chr-7.8.img 匹配 10 个 MikroTik + Cisco IOSvL2，与十二轮基线一致），skipped 19 条含三类原因（镜像已被模板引用 / 同名模板已存在 / 镜像缺失不可读）；测试后 11 个模板已全部删除。**`image_prune` 未测**（会删除所有未被模板引用的镜像，破坏性）。

### 测试36 基线恢复与清理 ✓
删除测试项目 2 个、测试模板（Stage37-VPCS-Renamed 1 个 + image_install 新建 11 个）、僵尸镜像条目 1 个；核对：项目 17 / 节点 196 / 链路 241 / 模板 27，与开场 server_statistics 完全一致。

## 3. 发现与建议

### 缺陷一（存量，中）vpcs_config_set 混批一坏全废
- **现象（一句话）**：一批 VPCS 配置里混进一台不合格设备，同批合格 VPCS 的命令根本不执行。
- **细节**：返回里只有失败条目、没有成功条目；合法设备的命令未送达（IP 仍 0.0.0.0/0）。若首位是无 console 的交换机（如 Ethernet switch），整个调用走全局异常通道（裸 Error、无 in-band 明细）；若是 docker，则走 in-band failed 条目——两种通道表现不一致。
- **根因**：`VpcsCommandRunner.run()` 在 `_prepare_device_hosts_data` 之后有 `error_devices` 短路：只要任一设备带 error 就 return 错误列表，早于 Nornir 执行。**该逻辑为存量**：旧 LangChain 类 `tools_v2/vpcs_tools_netmiko.py:203-205` 同款代码，本提交 git mv 原样搬移（对照 6a4cbe39c^ 源码）。
- **证据**：混批 [PC1, PC2, FRRDocker-1] → 仅 1 条 failed；同批去掉 docker 后两台 IP 配置成功；[Switch1, PC1] → 全局 Error。
- **建议**：预检阶段把错误设备从待执行集中剔除，其余设备照常执行，返回合并结果（error 条目 + success 条目）。

### 缺陷二（存量，低）marker_definition update 必须重发 bpf
- **现象（一句话）**：更新项目级 marker 定义时只改颜色不带 bpf，一定失败。
- **细节**：工具描述与路由 docstring 都写「update 需要 bpf/tag/color/highlight_duration/data_link_type 至少一项」，实际只传 color 被拒；带上 bpf=原值即可成功。
- **根因**：PUT `/{project_id}/marker-definitions/{def_name}` 的 body 模型复用 `MarkerDefinitionCreate`，其 `bpf: str` 为必填（`gns3server/schemas/controller/links.py:346`）；该特性 2026-07-13 引入（31991fe35），与本轮提交无关。
- **证据**：update(color=#00ff00) → 客户端裸 Error；update(bpf=arp, color=#00ff00) → 成功且 color 已改。
- **建议**：PUT 改用独立的 partial-update 模型（bpf: Optional[str] = None），与工具描述对齐。

### 观察一（文档口径）template_list 默认字段与描述不符
描述称不传 fields 时默认只回 `[template_id, name, template_type, category, default_name_format]`，实测回全量字段（node_list/node_get 描述无默认值声明，行为一致）。功能不受影响，建议改描述或改默认。

### 观察二（客户端呈现）错误明细不可见
多例 4xx 拒绝在客户端只显示「Error executing tool X」，不带服务器错误正文（node_suspend VPCS、link_create 端口冲突、drawing_delete 锁定、template_delete 占用、appliance_install 缺镜像、project_duplicate+reset_mac）。经源码对照确认底层均为预期 4xx（非服务器回归、非静默成功）；明细可见性属客户端工具异常呈现层。

### 观察三（文案）node_suspend_all 消息不精确
返回 "All nodes suspended"，但 VPCS 节点保持 started（VPCS 不支持 suspend，单发时诚实 405，批量时静默跳过）。语义与基线一致，仅消息容易误读。

### 观察四（存量）project_duplicate + reset_mac_addresses=true 失败
该参数会把节点的 `properties.mac_address` 置 None（`gns3server/controller/import_project.py:225-228`），docker 节点重开时校验失败，导致复制整体失败；不带该参数正常。属存量 controller 行为，建议 reset 分支改为重新生成 MAC 而非置 None。

## 4. 覆盖范围与限制（如实声明）

- 本轮所有结论均**经 MCP 接口实测**（除明确标注"源码对照"的根因定位）。
- 远程 compute 不存在于本机注册表（compute_list 空），多 compute 代理路径未覆盖；阶段36 已验证该路径。
- device 三工具只实测 FRR docker（vtysh 落点）与 VPCS；IOS/IOU/dynamips 走同一 runner（本提交为原样搬移 + 渲染下移），未逐类型重测。
- `node_console_exec` 本提交未触碰，仅冒烟；深测结论见《阶段36_node_console_exec 工具模块复测报告》。
- `image_prune` 未测（破坏性：会删除所有未被模板引用的镜像，本机约 40+ 个）。
- `appliance_install` 成功路径未测（本机无匹配镜像）。
