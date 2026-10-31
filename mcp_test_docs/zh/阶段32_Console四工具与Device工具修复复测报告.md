# GNS3 MCP Console 四工具与 Device 工具修复复测报告（阶段 32）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-10-31 |
| 被测对象 | gns3server **3.1.0.dev8+862b78a4f**（server_version 实测值）；MCP 侧版本不可经工具观测——用户口述"console 四工具（exec/send/read/close）与 device config/display 已修复"（转述，非实测） |
| 复测范围 | 92bc5f2dd 之后的新一轮修复：console 四工具全矩阵回归 + device_config_send / device_show_run 正常/错误路径 |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `Console-Device-Recheck-1031`（3×UbuntuDockerGuest[telnet/docker_exec/ssh] + UbuntuCloudGuest[qemu] + IOU L3 + FRRDocker），测完已删，终态 project_list 无残留 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 回归/未修 |
| 上一轮基线 | 92bc5f2dd（2026-10-31 上午）：串口争用+MOTD 劫持双修复验全绿；已知未修=登出后缓存会话竞速（F4 前身） |

## 0. 环境备注

- 节点 netmiko_device_type 均为 node_update 直设（不打 tag，用户既定偏好）；console_type 节点级改动一律 stop→update→start。
- **关键环境差异**：本轮 UbuntuCloudGuest 为全新节点，`default_username/default_password` 初始为 **null**（凭据只存在于模板 usage 文本）；上一轮测试节点这两个字段已设过。此差异直接改写了 QEMU 登录线的测试结论（见 F3）。

## 1. Console 四工具（24 场景）

### 1.1 前置判型与拒收

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 1 | exec：节点缺 netmiko_device_type | ✓ | 拒绝并指引两处写法（节点字段优先/tag 后备），语义与 77bb4a0b5 一致 |
| 2 | exec：IOU（cisco_ios_telnet） | ✓ | NOS 带内拒绝，指路 device_config_send/device_show_run 并说明原因（"batch drivers manage config mode themselves"） |
| 3 | device_config_send：Linux 家族节点（gns3_linux_telnet） | ✓ | **对称拒收**："is a Linux shell node; this tool serves network OS consoles. Use console_exec"——两族工具互相指路成闭环，疑为本轮新增 |

### 1.2 exec 正常路径（telnet / ssh 双传输）

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 4 | 基础命令（whoami; tty） | ✓ | telnet=root//dev/pts/0；**ssh console + gns3_linux_telnet 家族标识正交组合**通（改传输不用改第二处，复验成立） |
| 5 | exit_code 精确性（`sh -c 'exit 7'`） | ✓ | 双传输均精确返回 7 |
| 6 | 180 字符回行命令 marker 泄露 | ✓ | 输出纯净，无 `__MCP_DONE__`/`__MCP_PROMPT__` 泄露（77bb4a0b5 修复保持） |
| 7 | 会话上下文（cd /tmp + export）跨 exec | ✓ | 双传输存活，pwd/变量均可回收 |

### 1.3 docker_exec 传输

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 8 | exec/send on console_type=docker_exec | **✗ F1** | **回归**。两种形态：全新启动即 docker_exec → `Connection refused`；telnet→docker_exec 翻转后 → `Command execution failed: telnet connection closed`（错误文案自述 telnet 驱动）。同节点切回 telnet 一切正常 ⇒ 节点健康、传输路径坏。**92bc5f2dd 时代实测通（tty=/dev/pts/2）**。推断（非实测）：新代码把 docker_exec 误映射到 telnet 驱动去连 TCP 5001（docker_exec 无 TCP 监听者）。**定性更新见 §6 勘误：docker_exec 设计人群=SRL/XRd 类镜像，Ubuntu+docker_exec 属边缘组合** |

### 1.4 send / read 语义

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 9 | send 裸文本（无 \r） | ✓ | 只见回显不执行、命令停输入行；回执 `sent` 字段一眼可辨——第一坑行为保持 |
| 10 | send 裸 `\r`（仅一个控制字符） | ⚠️ **F2** | U1(telnet) 一次被转成字面 `\r` 两字符进 shell（积压行变 `echo NOCR_PROBE\recho CR_TEST`，bash 转义吃 `\` 后 echo 出 `NOCR_PROBErecho CR_TEST`，证据闭环）；CG1 上三连发又全部正常送达。**非确定性**，推断发生在调用链/harness 层（MCP sent 回执与 shell 回显一致=忠实转发）。教训：恢复积压行别用裸 `\r` 单发，风险不可控 |
| 11 | 复合发送 `command\r` | ✓ | CR 正确送达并执行（多轮验证） |
| 12 | send+read 长命令闭环（ping -c 15） | ✓ | 双传输 15 包全量输出+统计完整回收；毛边：U1 首次 read 混入驱动自身 `export TERM=dumb PAGER=cat PS1=' '` 初始化行 |
| 13 | read 增量语义 | ✓ | 多轮 read 只返回新增输出 |

### 1.5 超时契约

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 14 | exec `sleep 30` + timeout=5 | ✓ | status=timeout、exit_code=null、hint 齐全（指路 read 轮询/DONE 标记/\x03），双传输一致 |
| 15 | 超时后 read 收尾 | ✓ | `SLEEP_DONE` + `__MCP_DONE_0__` 双传输完整回收，会话不死 |
| 16 | 超时后会话复用 | ✓ | 下一发 exec 正常 |

### 1.6 QEMU 串口 getty（UbuntuCloudGuest，ubuntu/ubuntu）

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 17 | exec 自动登录（首次） | **✗ F3** | 120s 停在 `ubuntu-cloud login:` 不推进 |
| 18 | exec 自动登录（重试） | **✗ F3** | 60s 停在 `Password:`，getty 自身 60s 超时重印 |
| 19 | 手工 send/read 登录（telnet 串口） | ✓ | 凭据有效、完整 MOTD+提示符——排除 cloud-init/密码问题 |
| 20 | exec 复用已登录会话 | ✓ | telnet 与 ssh 代理两路径均 whoami/tty/exit0 正常 ⇒ **F3 范围=登录自动化段，复用段无恙** |
| 21 | 缺凭据（default_password=null）ssh 路径 | ✓ | **干净报错**："Console asks for a password but the node has no default_password configured"——快速失败不挂死（疑为本轮新增契约）；但 telnet 路径同状态是挂死（形态不一致，并入 F3） |
| 22 | 设凭据后 exec 自动登录 | **✗ F3** | dance 真跑起来了但 **Login incorrect**（同凭据手工登录成功）⇒ 自动登录发送内容/时序有缺陷。**92bc5f2dd 双传输全通为对照基线** |
| 23 | 登出后立即 exec（92bc5f2dd 已知边界） | **✗ F4** | 仍未修：90s 干等，输出只有 getty 重印 banner+`login:`，命令石沉大海，无自动重登录；恢复仍靠 console_close。注：本轮此测试在凭据已设但 dance 已坏（F3）状态下进行，若 F3 修复此处行为需复测 |
| 24 | close→重连 / identity 争用 / `\x03` | ✓ | close 后重连连接层正常；CG1 telnet→ssh 翻转（原始翻车方向）无争用错误、旧会话自动换新（92bc5f2dd 修复保持，docker 方向本轮被 F1 遮蔽未验）；**`\x03` 中断在 ssh 代理/getty 路径首测通过**（`^C`+提示符回归、shell 存活；docker 主 bash 雷区按纪律不发） |

## 2. Device 两工具（9 场景）

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| D1 | show_run 多命令单条目（R-1×2） | ✓ | 两条输出完整按序返回，10-04"多条覆盖"修复无回归；FRR 多命令同样无覆盖 |
| D2 | config_send 直连命令 + write memory | ✓ | conf t 步进、`[confirm]` 交互自动处理、落盘复核（lo0 40.40.40.40/32 up/up） |
| D3 | config_send Jinja2 多设备（R-1+FRR 一次调） | ✓ | 模板 `interface {{ifname}}\n ip address {{ip}}{{mask}}` 双 NOS 渲染推送全成（IOS 点分掩码 / FRR CIDR+lo，差异全由 vars 吸收），回执含各自渲染后命令 |
| D4 | show_run Jinja2 | ✓/⚠️ | R-1 渲染验证 ✓；FRR 侧 vtysh 不认 `show running-config interface lo`（`% Unknown command`）但 status=**success**——CLI 内错误不做状态判定，调用方须自查输出（与 E-1 的传输/拓扑层错误契约是两层，维持既往行为） |
| D5 | FRR 无判型 → 报错 | ✓ | 指引文案含 netmiko_device_type 写法+已测类型清单+当前 tags（E-1 契约保持） |
| D6 | FRR 配置落盘复核 | ✓ | `show interface lo`（inet 41.41.41.42/32）+ `show ip route connected`（C>* 直连）双确认 |
| D7 | 假设备 config_send | ✓ | status=failed + "no valid devices…Devices: ['NO-SUCH-DEV']" |
| D8 | show_run 塞非只读命令（reload） | ✓/⚠️ | 正确拒收，但错误文案只有裸 `Subtask: netmiko_multiline (failed)`，未说明"只收 show/display/ping/traceroute"（文案质量降级，功能没降级） |
| D9 | 判型字段 node_update 直设 | ✓ | FRR 设 cisco_ios_telnet 后即通（不须 tag，用户既定流程复验） |

## 3. 本轮发现汇总

| 编号 | 级别 | 内容 | 对照基线 |
|---|---|---|---|
| **F1** | ✗ 回归（§7 正确用法复刻实证：**server 侧传输端到端断**，非用法问题） | docker_exec 传输三层全断：console 工具 refused/closed、device 工具 netmiko 失败 ×2、**ws console 本身零输出（纯 server 路径，不经 MCP）**；telnet 对照组同姿势全活 | 92bc5f2dd console 工具实测通 |
| **F3** | ✗ 回归 | QEMU 串口 getty 自动登录损坏：无凭据 telnet 挂死/ssh 干净报错（形态不一致）；有凭据 Login incorrect（手工同凭据成功） | 92bc5f2dd 双传输全通 |
| **F4** | ✗ 未修 | 登出后缓存会话竞速干等（92bc5f2dd 已知边界原样），恢复仍靠 close | 已知未修项，非本轮引入 |
| **F2** | ⚠️ 注意 | 裸 `\r` 单发偶发被转义成字面 `\r`（调用链层，非确定性；复合发送不受影响） | 新发现 |
| 毛边×3 | ⚠️ | read 偶混驱动初始化行；CLI 内错误 status=success；reload 拒收文案裸 | 低优先级 |

**保持已修的既往项**：marker 泄露（77bb4a0b5）、串口争用身份比对（92bc5f2dd）、超时契约（562826a57）、NOS/Linux 双向拒收指路、多条覆盖（10-04）、E-1 错误契约。

**疑为本轮新增的修复**：缺凭据 ssh 路径快速失败契约（#21）、device 工具对 Linux 家族对称拒收（#3）——无旧版对照，按行为质量判。

## 4. 统计

- Console：24 场景 = **19 通过 + 1 注意（F2）+ 3 回归/未修场景（F1/F3/F4）+ 毛边 1**
- Device：9 场景 = **7 通过 + 2 通过但注意**
- 修复建议优先级：F3（登录 dance，阻断 QEMU 全自动链路）> F4（登出边界，人工 close 可绕）> F1（**server 侧 docker_exec 传输断，见 §7**——当前环境 15 个在册 docker 镜像全是 telnet 型无人受影响，但 SRL/XRd 启用前必修）> 文案毛边
- 测试痕迹：临时项目已删，project_list 终态 3 个既有项目、无新增残留

## 5. 给下一轮的复测清单（F1/F3/F4 修复后）

1. docker_exec（§7 定位=server 侧传输断）：server 修复后按序复测 ① ws console 有输出（websocat 对照法）② device 工具通（正确用法主路）③ console 工具（shell 型组合，是否保留属产品决策）；原生 SRLinux appliance 到镜像后整链路复测
2. QEMU getty 自动登录：无凭据（telnet 应与 ssh 同样快速失败）/ 有凭据（应登录成功）/ 首启 boot 中 exec（登录段超时应关会话）
3. 登出边界：登出→exec 应自动重登录或快速失败，不再 60-90s 干等
4. MOTD "Last login:" 劫持回归（92bc5f2dd 修复）——本轮被 F3 阻断未验
5. docker 方向 identity 争用（本轮被 F1 遮蔽）

## 6. 勘误：docker_exec 的设计人群（10-31 晚，用户指正 + appliance 定义佐证）

用户指正 docker_exec 只有 XRd / SR Linux 之类的镜像使用，普通 docker（Ubuntu/FRR）用 telnet/ssh。经 appliance 定义核实**成立**（实测 appliance_get）：

- **SRLinux**（builtin，appliance_id ffa79bec）：docker 模板 `console_type: "docker_exec"`，环境变量 `GNS3_CONSOLE_CMD=/opt/srlinux/bin/sr_cli`，描述明言 console 经 docker_exec 直落 sr_cli TUI；模板自带 `netmiko_device_type: nokia_sros_telnet`
- **XRd Control Plane**（builtin，e4a3a5fe）：同 `console_type: "docker_exec"` + `GNS3_CONSOLE_CMD=/pkg/bin/xr_cli.sh`；自带 `netmiko_device_type: cisco_xr_telnet`
- 常规 docker 镜像（Ubuntu Docker Guest / FRR / FRRDockerLite / cEOS / Alpine / PyATS / Toolbox 等）**全部 `console_type: telnet`**

**对 F1 的影响**：docker_exec 的承载是 `docker exec` 起 GNS3_CONSOLE_CMD（无 TCP console 端口，node_console 走 ws 端点），console 工具的 telnet 驱动连 TCP 自然 refused/closed——根因解释比"误映射"更完整。正式人群（SRL/XRd）的 console 落的是 **NOS CLI 且 appliance 自带 netmiko 判型**，正确工具是 device_config_send/device_show_run，console 工具（Linux-only 家族门槛）本来就会拒它们 ⇒ F1 一度降级为"边缘路径失效"。**但 §7 追加实证推翻了降级：正确用法（device 工具）同样断，且 ws console（纯 server 路径）本身零输出——问题在 server 侧传输，非用法。**

另：本轮 FRRDocker-1 全程 telnet + cisco_ios_telnet，未对 FRR 使用 docker_exec。

## 7. 追加实证：正确用法下 docker_exec 仍断，问题在 server 侧传输（10-31 深夜，接 §6）

用户追问"没有正确使用还算问题吗"后做的鉴别实验（探针项目 DockerExec-SRL-Probe-1031，已删；SRLinux appliance 装后模板已删）。

**复刻方法**（原生 srlinux/xrd 镜像不在 compute 上——在册 15 个 docker 镜像全是 telnet 型，无法起真 appliance；改用 gns3/frr 逐项复刻 appliance 定义的机制，机制本身与镜像无关——此句为推断，标注）：节点 console_type=docker_exec + `properties.environment` 注入 `GNS3_CONSOLE_CMD=/usr/bin/vtysh`（后换 `/bin/bash`）+ netmiko_device_type=cisco_ios_telnet —— 与 SRLinux/XRd appliance 的"docker exec 起 GNS3_CONSOLE_CMD 落 NOS CLI、自带判型走 device 工具"完全同构。

**结果矩阵（全实测）**：

| 探针 | 结果 |
|---|---|
| device_show_run（正确用法该走的路）`show version` | ✗ `netmiko_multiline (failed)` ×2（非白名单拒收——同错误形态对比 reload 拒收可辨，这是连接层失败） |
| websocat → node_console 发的 ws console 端点（**纯 server 路径，不经 MCP**），GNS3_CONSOLE_CMD=vtysh | ✗ 连接建立、12s 零输出（单次新 token） |
| 同上，GNS3_CONSOLE_CMD=/bin/bash（必然存在的路径） | ✗ 仍零输出 —— 排除命令路径问题 |
| 对照组：同姿势 websocat → telnet console 节点 | ✓ bash 提示符 + `WS_PROBE_OK` 执行回显 |

**结论**：docker_exec console 传输在 **server 侧（gns3server 3.1.0.dev8+862b78a4f）端到端断**——ws console 连必然存在的 /bin/bash 都起不来，不是"用法不标准"（§6 勘误的方向对，但修过头了：正确用法同样断）。console 工具（refused/closed）、device 工具（netmiko 失败）两层失败均为该传输断的下游表现。**影响面**：当前环境无任何 docker_exec 在用节点，实际无人受影响；SRL/XRd 启用前必修。原生 SRLinux 复测待镜像到位后补。

**附带发现（本轮探针产生）**：
- `appliance_install` 只建模板不拉镜像（设计如此）；缺镜像时 `node_create` 吐**裸错**（无 "missing image" 文案、无 status 契约）——错误契约毛边 +1
- `node_update` 平铺 `environment` kwarg 被**静默忽略**，须 `properties` 嵌套才生效——易踩
- 阶段31 记录的"docker 镜像 11 个含 srlinux/xrd"已过时：现 15 个、无 srlinux/xrd
