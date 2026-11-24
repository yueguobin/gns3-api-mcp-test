# GNS3 MCP node_console_exec 工具模块复测报告（阶段 36）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-11-03 |
| 被测对象 | gns3vm21（192.168.101.21）gns3server **3.1.0.dev8**（server_version 实测；该接口本轮只返回 version，无 build hash）。controller + vm22/vm23/vm24 远程 compute |
| 测试范围 | `node_console_exec`：docker / VPCS / qemu / IOU / dynamips 多类型；名称与 UUID 定位；本地与远程 compute；多行命令与 0.3s pacing；真实 Ctrl-C；空 command；超时窗口；50 行输出漏斗（grep / regrep / full / curl 下载）；错误路径（未启动 / 无 console / VNC / 不存在）；会话状态跨调用保持；UTF-8；批量 stop 观察 |
| 未覆盖（环境限制） | ① QEMU 串口 getty 登录（用户名+密码同一次调用）：本机 qemu 模板只有 FRR 系（自动登录 vtysh）和 IOSv，无 Debian/getty 模板；② console_type=ssh：本机无 ssh console 实例（docker 全为 telnet）；③ websocat 缺失错误路径（不改服务器组件）；④ 真正并发的同节点双调用（MCP 客户端把同批调用串行执行，未形成并发）；⑤ 64 KiB 字节上限（只验证了 400 行上限） |
| 测试方式 | 仅经 MCP 工具接口；项目 `ConsoleExec-Test`（d6be617a-01db-450f-80ac-75b5df6ea21e），13 节点；测完除 stateless 的 Switch1/Cloud1 外全部 stopped，项目保留 |
| 结果标记 | ✓ 通过 · ✗ 未通过 · ⚠ 注意/限制 |

## 1. 结论

**模块整体可用**：docker、VPCS、qemu（FRR / FRR-Qemu / IOSv）、IOU、dynamips，本地与远程 compute 都能通过 `node_console_exec` 正常执行命令；多行、Ctrl-C、空 command、会话状态跨调用保持、50 行漏斗（grep / regrep / full / curl 下载）、四类错误提示均按文档工作。

**发现 1 个小缺陷**：节点刚启动、console 尚未就绪时，工具返回的是一串 telnet 协商乱码（`��\u0018`），而不是工具描述承诺的 `no console output within Ns ...` 提示。新建 IOU2 启动后立即调用必现（实测 2 次），IOU1 启动期同样出现。原因是 `console_exec.py` 只用 `if not stdout` 判断静默，而 telnet 连接必然先收到 IAC/协商字节，`stdout` 永远非空，静默分支实际不可达（源码 `gns3server/agent/mcp/console_exec.py:394`）。

**2 个使用限制**：① timeout=1 在本机 docker 上连续两次都只回协商字节，命令没有送达；timeout=2 起正常。timeout=0 会被源码静默钳到 1s（`max(1, ...)`），不报参数错误。② Dynamips 节点每次新建连接会回放启动以来的全部 console 历史，>50 行时返回的 10 行样例全是启动 banner，命令输出在尾部，需配合 `grep` / `regrep` / `full` 查看。

## 2. 测试项

### 测试01 docker 节点基本命令 ✓
UbuntuDockerGuest-1 执行 `echo` / `id -un` / `pwd` / `uname -sr`：4 行全部执行，返回 root、/root、Linux 7.0.0-38-generic。

### 测试02 会话状态跨调用保持 ✓
调用 1：`cd /tmp; export CE_VAR=persist-02; sleep 120 &`；调用 2：`pwd`、`echo $CE_VAR`、`jobs -l`、`ps -p 365`。得到 /tmp、persist-02、后台 sleep 仍在运行——cwd、环境变量、后台进程三项均跨调用保持。

### 测试03 空 command 发送单个 Enter ✓
`command=""` 返回新的 shell 提示符，未执行任何命令。

### 测试04 多行命令逐行执行 ✓
8 行 `echo CE-LINE-N` 在同一次调用中全部执行，顺序正确，无丢行。

### 测试05 长输出摘要（>50 行）✓
`seq 1 100` 返回 105 行，工具只回前 10 行并给出 regrep / full / grep / curl 四条检索提示，附一次性下载 URL。

### 测试06 grep 过滤 + regrep 缓存 ✓
`echo CE-REGRUN-$RANDOM` + `seq 1 100`，grep 只回匹配行；随后 `regrep=true` 同一 grep 返回**同一个** 16581，证明读的是缓存、没有重跑。

### 测试07 regrep + full 返回缓存尾部 ✓
同一缓存 `full=true` 返回 `last 110 of 110 lines`，内容含 1..100 完整序列。

### 测试08 真实 Ctrl-C 与字面 `\x03` ✓
`sleep 30` 启动后，独立一行发真实 `\u0003`（JSON 控制字符）：返回 `^C` 与提示符，进程被中断。发字面四字符 `\x03` 时未被翻译，bash 报 `command not found`——与工具描述一致。

### 测试09 超时窗口占满、无提前返回 ✓
`for i in $(seq 1 12); do echo CE-W$i-$(date +%s); sleep 0.5; done`，timeout=5：收到 8 拍（时间戳跨 1793639904–1793639907），说明输出持续收集到窗口结束，命令在断连后继续运行。

### 测试10 docker 长行输出完整、回显换行正常 ✓
`printf 'Y%.0s' {1..200}` 的 200 字符输出单行完整；长命令的回显在终端第 80 列（提示符 31 字符 + 命令约 50 字符）插入 `\r` 换行，属 readline 正常行编辑行为，命令执行不受影响。

### 测试11 timeout 边界 ⚠
timeout=0 被源码钳到 1s，只回协商字节；timeout=1 在 docker 上连续两次（冷、热 console 各一次）都只回 `��\u0018`，命令未送达；timeout=2 立即正常。1s 下限低于本机 docker 的连接+回显延迟。

### 测试12 VPCS 节点 ✓
`show ip` 正常；`ip 10.9.9.9/24` 触发重复地址检查，4s 窗口内只回 `Checking for duplicate address...`，随后 `show ip` 确认地址已生效——VPCS 命令可用，但 `ip` 类命令要留足时间。

### 测试13 FRRDocker vtysh 落点 ✓
FRRDocker-1 直接落在 vtysh，`show version` 返回 FRRouting 10.3，提示符 `FRRDocker-1#`。

### 测试14 FRRDocker 配置模式跨调用保持 ✓
调用 1 `configure terminal` 进入 `(config)#`；调用 2 `interface lo`、`description ...` 在 `(config-if)#` 直接生效——配置模式跨调用保持。已用 `no description` + 两次 `exit` 还原。

### 测试15 远程 compute 代理 ✓
UbuntuDockerGuest-2 放在 vm22（compute 9ff3997f…），`hostname` / `echo` / `ip -br addr` 均正常，证明 controller → 远程 compute 的 WebSocket 代理路径可用。

### 测试16 FRR qemu 串口 console ✓
FRR-1（qemu 串口）连上即 `frr#`（模板自动登录 vtysh），`show version` 返回 FRRouting 8.2.2。

### 测试17 qemu 串口长行完整性（11-03 修复回归）✓
`show version` 的 `configured with:` 行约 900 字符，单行完整、`\r\n` 规范；随后在 shell 里用 `printf '%200s\n' | tr ' ' 'Y'` 输出 200 字符行，同样单行完整——11-03 的断碎修复在本场成立。

### 测试18 FRR-Qemu（Alpine）节点 ✓
FRR-Qemu-1 同样落 vtysh，`show version` 返回 FRRouting 8.2.2；与 FRR-1 行为一致。

### 测试19 Cisco IOSv（qemu）✓
CiscoIOSv-1 的 `show version | include Version` 与 `show ip interface brief` 均正常返回，提示符 `Router#`。

### 测试20 IOU 节点 ✓
IOU1 启动初期命令被吞（只回协商字节）；连续调用空 command 唤醒后 `show version | include IOS` 返回 IOS-XE 17.15.1，`IOU1#` 正常。

### 测试21 Dynamips Cisco 7200 ⚠
R1 启动期同样只回协商字节；唤醒后 `show version` 可执行，但每次新连接都会回放自启动以来的全部 console 历史（85→89 行），>50 行时 10 行样例全是 banner；需 `grep` / `regrep=true full=true` 才能看到命令输出（如 `R1#show version | include Version` 在缓存尾部）。

### 测试22 无 console 节点 ✓
Switch1 与 Cloud1（console_type=none / null）均返回 `node 'X' has no console`。

### 测试23 未启动节点 + regrep 离线 ✓
停止 UbuntuDockerGuest-1 后调用返回 `node '...' is stopped — start it before using the console`；同一节点 `regrep=true` 仍能读到停止前的缓存（`CE-T1B`），符合源码 `validate_console=False` 的设计。

### 测试24 不存在的节点/项目 ✓
不存在节点返回 `Node 'NO-SUCH-NODE' not found. Known nodes: ...`；不存在项目返回 `Project 'NO-SUCH-PROJECT' not found. Known projects: ...`，均列出已知名字。

### 测试25 特殊字符 / UTF-8 / 引号 / Tab ✓
`echo '中文测试-Ω-✓-end'`、`printf 'tab\there\n'`、双引号/单引号混合嵌套均正确执行，输出编码完好（回显里的中文以 bash 转义形式显示，属终端回显，不影响结果）。

### 测试26 同节点两次调用（并发观察）⚠
同一批发出两次调用，各自返回自己的输出、无串扰；但从结果看客户端把两次调用串行执行，**没有真正形成并发**，同节点并发写同一 console 的行为本轮未验证。

### 测试27 regrep 无缓存提示 ✓
新建 PC2（从未执行命令）直接 `regrep=true`，返回 `no captured output for node 'PC2' yet — run a command first...`。

### 测试28 VNC console 拒绝 ✓
把 CiscoIOSv-2 的 console_type 改为 vnc 并启动后调用，返回 `node 'CiscoIOSv-2' has a VNC console (pixel stream) — there is no text command channel`，与文档一致。

### 测试29 qemu 串口 shell 状态保持与终端事实 ✓
FRR-1 上 `exit` 从 vtysh 落到 `/bin/ash` shell（`frr:~#`），后续调用直接在该 shell 执行，证明登录/落点状态跨调用保持；`tty` 为 `/dev/ttyS0`，`stty -a` 报 `Not a tty`（Alpine 串口 console 环境事实），但 200 字符输出行完整。已发 `vtysh` 送回原落点。

### 测试30 400 行上限 ✓
`seq 1 500` 返回 505 行；`regrep=true full=true` 返回 `last 400 of 505 lines (line cap 400)`，尾部包含 500。

### 测试31 UUID 形式定位符 ✓
项目 UUID + 节点 UUID 调用 `echo CE-UUID-LOCATOR-OK` 正常执行，名称与 UUID 两种定位方式均可用。

### 测试32 完整窗口二测 ✓
另一次 `for ... sleep 0.5` 打卡（timeout=5）收到 8 拍，与测试09 一致，排除偶发。

### 测试33 批量 stop 与状态巡检 ⚠
`node_stop_all` 返回 `All nodes stopped`；随后巡检：docker / qemu / iou / dynamips / vpcs 全部 stopped，Switch1/Cloud1 保持 started（stateless 节点的正常表现）。旧记录中"批量 stop 后 4 节点自发 running"本轮**未复现**。

### 测试34 完整捕获下载 ✓
用测试05 提示的 curl URL 下载 `console-capture.txt`：HTTP 200、2566 字节、502 行，首行为 `seq 1 500`，尾部到 500，下载路径可用。

### 测试35 grep 命中 >50 行时的提示 ✓
`seq 1 100` + `grep='^[0-9]+$'` 命中 100 行：返回前 10 行样例，提示中正确省略了"grep 会重跑命令"这一条（因为过滤已生效），其余提示正常。

### 测试36 regrep 不执行传入的 command ✓
`regrep=true` 时附带 `command="touch /tmp/ce-regrep-should-not-run"`，随后真实执行 `ls`：文件不存在（RC=2）——regrep 确实只读缓存，不产生副作用。

## 3. 发现与建议

### F1（缺陷，低）静默 console 的错误提示被 telnet 协商字节掩盖
- **现象**：新建 IOU2 启动后立即 `node_console_exec`，返回只有 `��\u0018`，没有任何文字说明；等 console 就绪后必须先发空 command（Enter）唤醒，命令才能执行。IOU1 启动期同样出现。
- **根因**（源码定位）：`gns3server/agent/mcp/console_exec.py:394` 用 `if not stdout` 判定会话静默，而 telnet console 连接必定先回 IAC/协商字节（`\xff\xfb\x18` 等），`stdout` 恒非空，`_session_error()` 的 "no console output within Ns — the console may still be booting or silent" 分支实际不可达。
- **建议**：判断前先剥离 telnet 协商/控制字节，或改为"可打印字符为零才算静默"；否则至少在这种输出后面追加一句提示。

### F2（限制）timeout 下限与参数校验
- timeout=1 在本机 docker 上连续两次都只回协商字节（连接+回显耗时超过 1s），timeout=2 起正常；timeout=0 被源码 `max(1, ...)` 静默钳到 1s，不报参数错误。schema 声明 1–300，但 1s 实际不可用。
- 建议：文档把可用下限写成 2–3s，或对 <2s 的 timeout 直接报错并给出建议值。

### F3（节点行为，需在工具文档中说明）Dynamips console 历史回放
- Dynamips 每次新建连接回放自启动以来的全部 console 输出（不是本工具引入的）。>50 行时 10 行样例全是启动 banner，命令输出落在尾部，容易误判"命令没执行"。
- 建议：工具描述里对 dynamips（以及任何回放历史的 console）提示优先用 `grep=` / `regrep=true full=true`。

### F4（环境限制，未测项）
- QEMU 串口 getty 登录（用户名+密码同一次调用）本机无 getty 模板可测；FRR 模板自动登录 vtysh，只能验证"落点/登录态跨调用保持"。
- console_type=ssh 无实例；websocat 缺失路径不可测；真正并发的同节点双调用未形成（客户端串行）。

### F5（正常行为，非缺陷）
- 长命令回显在 80 列处插入 `\r` 换行（提示符 + 命令超过 80 列，readline 行编辑），命令执行与输出均不受影响；qemu 串口输出长行完整，11-03 修复回归通过。
- `\u001b[6n` 光标位置查询等 ANSI/控制字节会出现在原始输出里，工具文档已声明"raw console bytes ... may show up as stray bytes"。
