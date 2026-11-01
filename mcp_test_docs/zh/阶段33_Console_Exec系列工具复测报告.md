# GNS3 MCP Console Exec 系列工具复测报告（阶段 33）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-10-31（深夜） |
| 被测对象 | gns3server **3.1.0.dev8+1983f5737**（server_version 实测值；上一轮阶段 32 为 862b78a4f）。MCP 侧版本不可经工具观测 |
| 复测范围 | console_exec / console_send / console_read / console_close 四工具的传输矩阵、语义契约、错误路径与回归项 |
| 明确排除 | **docker_exec 传输的 console 四工具路径**——用户指正：docker_exec 是 console 类型，正确用法是配合 `netmiko_device_type` 走 `device_config_send` / `device_show_run`（SRL/XRd appliance 即此模式）；console 四工具按设计只服务 Linux shell，会对 NOS 带内拒绝。本轮未使用 docker_exec；device 工具不在本轮范围（阶段 32 已 9 场景全绿） |
| 测试方式 | 仅经 MCP 工具接口；两个既有测试项目 `Console-Ubuntu-Test`（b4ce7670）、`Console-Tools-IOU-Test`（a6282653），测完已全部 stop + close，恢复初始状态 |
| 结果标记 | ✓ 通过 · ⚠️ 注意/未定论 · ✗ 缺陷/未修 |

## 0. 环境与场景

- `Console-Ubuntu-Test`：UbuntuDockerGuest-1（telnet）、-2（ssh）、-4（ssh），三者 `netmiko_device_type=gns3_linux_telnet`；UbuntuCloudGuest-1（qemu，console_type=ssh，default_username/password=ubuntu/ubuntu）。UbuntuDockerGuest-3 为 docker_exec，按指示未使用。
- `Console-Tools-IOU-Test`：R-1/R-2（IOU，模板 tag `device_type:cisco_ios_telnet`）、UbuntuDockerGuest-1（docker telnet，节点 tag `device_type:gns3_linux_telnet`，netmiko 字段为 null）。
- 所有节点本轮启动/停止均经 MCP；节点名/UUID 两种参数形式均可用（本轮以名称调用）。

## 1. 核心 exec 矩阵（三传输）

| # | 场景 | telnet(docker) | ssh(docker) | QEMU(ssh 代理+getty) |
|---|---|---|---|---|
| 1 | 基础 `whoami; tty` | ✓ root/`/dev/pts/0` | ✓ root/`/dev/pts/0` | ✓ ubuntu/`/dev/ttyS0` |
| 2 | exit_code 精确性 | ✓ `sh -c 'exit 7'`→7 | ✓ →7 | ✓ →7 |
| 3 | 错误退出码 | ✓ `nosuchcmd`→127；`false`→1 | ✓ 同左 | ✓ 同左 |
| 4 | 会话上下文（cd+export 跨调用） | ✓ /tmp + 变量 | ✓ /var + 变量 | ✓ /tmp + 变量 |
| 5 | 188 字符回行命令 | ✓ 输出纯净、无 marker 泄露 | — | — |
| 6 | 引号/特殊字符/printf | — | ✓ `'a b' "x=y"`、多行 printf | — |
| 7 | 大输出截断 | ✓ 默认 20000 字符 `truncated=true`；`max_chars=1000` 截在 ~1000 | — | — |
| 8 | 超时契约 `sleep 30`+timeout=5 | — | ✓ status=timeout、exit_code=null、hint 齐全 | ✓ 同左 |
| 9 | 超时后 read 收尸 | — | ✓ `SLEEP_DONE`+`__MCP_DONE_0__` | ✓ 同左 |
| 10 | 超时后会话复用 | — | ✓ 下一发正常 | ✓ 同左 |
| 11 | read 增量语义 | ✓ ping 15 包分两次收（14 行→末行+统计） | — | — |
| 12 | 同节点并发 exec（两调用并行） | ✓ 各自完整、无串扰（串行化） | — | — |

## 2. QEMU getty 自动登录（阶段 32 的 F3 复测）

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 13 | 首次 exec 自动登录 | **✓ 已修** | `whoami`=ubuntu、tty=`/dev/ttyS0`、exit 0；上轮"Login incorrect"不再现 |
| 14 | 登出后 exec（F4） | **✗ 未修** | send `exit`→getty `login:`；exec 干等 20s，命令未送达、无自动重登录 |
| 15 | close 后 exec 重连 | ✓ | console_close→下一次 exec 自动重登录成功（恢复路径有效） |

## 3. send / read / close 语义

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 16 | send 裸文本（无换行） | ✓ | 只回显不执行、命令停在输入行（第一坑行为保持） |
| 17 | send 带 LF | ✓ | `command\n` 正常执行（本轮实测 LF 可替代 CR 触发执行） |
| 18 | 复合发送 | ✓ | `command\n` 执行并回收输出 |
| 19 | send 长命令 + read 轮询 | ✓ | `ping -c 15` 全量 15 包+统计完整回收 |
| 20 | send 于无会话节点 | ✓/⚠️ | 不报错，自动建立会话后写入（QEMU close 后实测）；与 read 的"无会话报错"不对称，可接受但需知晓 |
| 21 | read 无新输出 | ✓ | 返回空 output |
| 22 | read 于无会话 | ✓ | `No open console session...` 干净报错 |
| 23 | close 有会话 | ✓ | `closed: true` |
| 24 | close 无会话（幂等） | ✓ | `closed: false`，不报错 |
| 25 | close 后 exec（telnet/ssh/qemu） | ✓ | 三传输均重连成功 |

## 4. 错误路径与安全守卫

| # | 场景 | 结果 | 备注 |
|---|---|---|---|
| 26 | IOU 节点 exec（NOS） | ✓ | 带内拒绝，指路 device_config_send/device_show_run |
| 27 | 未启动节点 exec | ✓ | `Node 'R-1' is not started (status: stopped). Start it first (node_start).` |
| 28 | 不存在节点 exec/read | ✓ | 干净报错并列出已知节点 |
| 29 | 交互命令守卫 `top` | ✓ | 拒绝 + suggestion `top -b -n 1`；建议形式实测可用 |
| 30 | `tail -f` / `less` | ✓ | 拒绝 + suggestion `tail -n 50 <file>` / `cat <file>` |
| 31 | `python` 家族非交互守卫 | **✗ G1** | 见 §5.1：`-c/-V/-m` 与绝对路径全被误杀，suggestion 自相矛盾 |
| 32 | 完成标记伪造 | **✗ G2** | 见 §5.2：用户输出可冒充 `__MCP_DONE_<n>__` 提前完成并篡改 exit_code |

## 5. 本轮发现

### 5.1 G1（功能缺陷）：python 家族守卫误杀非交互形式

实测矩阵（QEMU 与 docker 节点一致）：

| 命令 | 结果 |
|---|---|
| `python3 -c 'print(1)'` | ✗ rejected，suggestion 却是 `python3 -c '<code>'` |
| `python -c 'print(1)'` | ✗ rejected（suggestion `python -c '<code>'`） |
| `/usr/bin/python3 -c 'print("ABS_PY_OK")'` | ✗ rejected（绝对路径也命中） |
| `python3 -V` / `python3 -m json.tool ...` | ✗ rejected |
| `python3.12 -c 'print(1)'` | ✓ 放行（首 token 精确匹配 `python3`） |
| `timeout 5 python3 -c 'print("QEMU_PY_OK")'` | ✓ 放行并执行成功 |
| `env python3 -c ...` | ✓ 放行（但 gns3/ubuntu:noble 镜像无 python3，→127） |

结论：守卫按"首 token 的 basename 为 python/python3"整条拒绝，未识别 `-c/-V/-m`；其给出的修复建议本身也会被拒。与工具描述"Use non-interactive forms … `-c '<code>'` (not `python`)"直接矛盾。绕法：`timeout N python3 -c ...` / `env python3 ...` / `python3.12 ...`。

### 5.2 G2（健壮性）：用户输出可伪造完成标记

- `echo "__MCP_DONE_7__"; echo AFTER7` → 返回 **exit_code=7**（真实命令 exit 0），`__MCP_DONE_7__` 行被从输出吞掉，AFTER7 仍返回。
- `echo "__MCP_DONE_3__"; sleep 3; echo LATE_AFTER_FAKE` → **立即**返回 status=ok、exit_code=3、output 空；3 秒后 `LATE_AFTER_FAKE` 与真实 `__MCP_DONE_0__` 才能经 console_read 收到。
- 影响：命令输出中恰好出现该标记串时，会提前结束采集并伪造退出码（正常运维输出极少命中，属低概率健壮性问题）。建议标记带不可预测随机串或仅信任最后一次 marker。

### 5.3 F4（上轮遗留）：登出边界仍未修

登出后 exec 不能自动重登录：本轮 20s 超时、命令未送达（getty `login:` 停留在输出里），恢复只能 console_close。与阶段 32 定性一致。

### 5.4 观察项（不下缺陷结论）

- **ttl 参数不可从 shell 侧观测**：ttl=3/5 的会话在 >10s 空闲后变量仍在。但 docker 主 bash（PID 1）与 QEMU 已登录 shell 跨会话本就持久，无法区分"会话未过期"与"会话重建但 shell 未变"，故不下结论。
- **F2（裸 `\r` 转义）本轮未验**：当前调用链只能发送字面 `\r`/`\u0003` 两字符串（`sent` 回执可见），无法注入真实控制字符；`\x03` 中断同样未验。LF 实测可触发执行，可作为实际替代。
- `cat /etc/hostname` 为空是容器内该文件 0 字节（`hostname` 命令正常），非工具问题。

## 6. 统计与优先级

- 通过场景：**27**（含 QEMU 自动登录 F3 修复、close 幂等、并发串行、错误契约、守卫 suggestion 可用等）
- 缺陷/未修：**3** — F4（登出边界，遗留）、G1（python 守卫误杀，新）、G2（marker 伪造，新）
- 注意/未定论：**2** — ttl 不可观测、send 自动开会话与 read 报错的不对称（可接受）
- 优先级建议：**G1（守卫与文档矛盾、影响真实脚本）＞ F4（已知边界，可 close 绕过）＞ G2（低概率健壮性）＞ 文档毛边**
- 回归确认：F3（QEMU getty 自动登录）本版已修复；阶段 32 的 marker 泄露/身份争用/超时契约/exit_code 精确性/上下文保持均无回归。

## 7. 未覆盖 / 下一轮清单

1. docker_exec：按用户指正，验证路径应为 `console_type=docker_exec` + `netmiko_device_type`（如 SRLinux 的 nokia_sros_telnet / XRd 的 cisco_xr_telnet）→ `device_config_send` / `device_show_run`，而非 console 四工具。当前 compute 的 15 个 docker 镜像无 srlinux/xrd；可用 gns3/frr + `GNS3_CONSOLE_CMD=vtysh` 复刻 appliance 机制（阶段 32 §7 方法）验证 device 路径，待复测。
2. 缺判型节点（既无 netmiko_device_type 也无 device_type tag）的拒绝文案——本轮场景所有节点均带判型/tag。
3. `\x03` 中断与裸 `\r` 发送——需能注入真实控制字符的调用链（websocat 对照法）复测。
4. G1 修复后复测 `python3 -c/-V/-m`、绝对路径与 suggestion 一致性；G2 修复后复测伪造 marker 不再提前完成。
5. F4 修复后复测：登出→exec 应自动重登录或快速失败（不再干等）。
6. device 两工具（本轮范围外，阶段 32 全绿基线可作对照）。

## 8. 修复验证（同日晚，server 3.1.0.dev8+0b85f7218，用户报告已修复）

**结论：G1、G2 已修复；F4 仍未修。**

| 项 | 复测结果 |
|---|---|
| **G1 python 守卫** | **✓ 已修**。QEMU 上 `python3 -c 'print("QEMU_PY_OK")'` → 输出 `QEMU_PY_OK`；`python3 -V` → `Python 3.12.7`；`/usr/bin/python3 -c ...` → `ABS_OK`；`echo '{"a":1}' \| python3 -m json.tool` → 正常格式化。docker 镜像无 python3，命令放行后如实返回 127（`PY_RC=127`/`ABS_RC=127`）。裸 `python3` 仍正确拒绝，且文案已修正为 `'python3' without -c/-m or a script opens an interactive REPL...`，suggestion=`python3 -c '<code>' or python3 <script.py>`——与行为一致。 |
| **G2 marker 伪造** | **✓ 已修**。完成标记改为带随机 nonce：`__MCP_DONE_b3555922_0__`（hint 文案同步为 `<nonce>`）。`echo "__MCP_DONE_7__"; echo AFTER7` → exit_code=0、标记行原样保留、AFTER7 返回；`echo "__MCP_DONE_3__"; sleep 3; echo LATE_AFTER_FAKE` → 等待真实完成，输出含标记行与 LATE_AFTER_FAKE，exit 0。不再提前返回/篡改退出码。 |
| **F4 登出边界** | **✗ 未修**。两轮独立复现：QEMU 已登录会话 send `exit` → getty `login:` → exec 30s 超时（输出停在 login 提示符，命令未送达，无自动重登录）；超时后再次 exec 仍 30s 超时（不自愈）。`console_close` 后下一次 exec 自动重登录成功（恢复路径有效）。 |
| 回归项 | ✓ 基础 exec（telnet/ssh/qemu）、超时契约（hint 已用 nonce 格式）、超时后 read 收尸（`TIMEOUT_DONE`+`__MCP_DONE_b3555922_0__`）、close 幂等（二次 `closed:false`）、close→exec 重连均正常。 |

附带观察：`node_stop_all` 再次返回裸错误（无文案），而 `UbuntuDockerGuest-3`（docker_exec 节点）仍为 started；单节点 `node_stop` 成功。与阶段 33 清理时现象一致，疑似 docker_exec 节点拖累批量停止，未深挖（该传输本轮仍未使用）。

### 8.1 F4 复测方法与原始数据

**场景**：UbuntuCloudGuest-1（qemu，console_type=ssh→SSH 代理到串口 ttyS0，console_host=192.168.1.3:5008，netmiko_device_type=gns3_linux_telnet，default_username/password=ubuntu/ubuntu）。被测行为=**已登录会话在 shell 内主动登出后，console_exec 复用缓存会话**的边界。

**方法（每轮固定步骤）**：
1. `console_exec` 建立会话并确认 shell（whoami/tty、exit_code 精确性）——同时作为 F3 前置验证；
2. `console_send` 发送 `exit\n`（模拟人工登出）；
3. `console_read` 确认 getty 回到 `ubuntu-cloud login:`；
4. `console_exec` 发送 `whoami; echo AFTER_RELOGIN`，timeout 取 20/30/60s；
5. `console_read` 观察超时后是否有迟到输出；
6. 再发一次 `console_exec`（验证是否自愈）；
7. `console_close` 后再 `console_exec`（恢复路径对照）。

**判定标准**：修复=第 4 步自动重登录（status=ok、exit_code=0）或快速失败（可行动错误、不耗尽 timeout）；未修=status=timeout、output 停在 login 提示符、exit_code=null。时间为工具自身 timeout 计时返回（未保存独立 wall-clock 时间戳）。

**原始数据（server 1983f5737，阶段 33 首测）**：

| 步 | 调用 | 返回（关键字段） |
|---|---|---|
| 1 | exec `whoami; tty; echo QEMU_EXEC_OK` timeout=90 | status=ok，output 含 `ubuntu@ubuntu-cloud:~$` / `ubuntu` / `/dev/ttyS0` / `QEMU_EXEC_OK`，exit_code=0 |
| 2 | send `exit\n` | status=ok，sent=`exit\n` |
| 3 | read wait=5 | output=`exit\nlogout\n\nUbuntu 24.10 ubuntu-cloud ttyS0\n\nubuntu-cloud login: ` |
| 4 | exec `whoami; echo AFTER_RELOGIN` **timeout=20** | **status=timeout**，output=`Ubuntu 24.10 ubuntu-cloud ttyS0\n\nubuntu-cloud login: `，exit_code=**null** |
| 5 | read wait=3 | output 空 |
| 6 | close | closed=true |
| 7 | exec `whoami; echo AFTER_CLOSE_RELOGIN` timeout=90 | status=ok，output 含 MOTD+`ubuntu@ubuntu-cloud:~$`+`ubuntu`+`AFTER_CLOSE_RELOGIN`，exit_code=0 |

**原始数据（server 0b85f7218，修复验证轮，两轮独立复现）**：

| 步 | 调用 | 返回（关键字段） |
|---|---|---|
| 0 | exec `whoami; echo QEMU_READY` timeout=90（开机中） | status=failed，`Console authentication failed: Could not reach a shell prompt on the Linux console within 20 attempts`（启动期登录等待，非 F4） |
| 1 | 同命令 timeout=120（重试） | status=ok，output 含 `ubuntu@ubuntu-cloud:~$`/`ubuntu`/`QEMU_READY`，exit_code=0 |
| 2 | send `exit\n` → read wait=5 | output=`exit\nlogout\n\nUbuntu 24.10 ubuntu-cloud ttyS0\n\nubuntu-cloud login: ` |
| 3 | exec `whoami; echo AFTER_LOGOUT_RELOGIN` **timeout=60** | **status=timeout**，output=login 提示符同上，exit_code=**null** |
| 4 | read wait=5 | output 空 |
| 5 | close → exec `whoami; echo AFTER_CLOSE_RELOGIN` timeout=60 | status=ok，output 含 MOTD+提示符+`ubuntu`+`AFTER_CLOSE_RELOGIN`，exit_code=0 |
| 6 | 第二轮：send `exit\n` → read | 再次回到 `login:` |
| 7 | exec `whoami; echo SECOND_TRY` **timeout=30** | **status=timeout**，output=login 提示符，exit_code=null |
| 8 | exec `whoami; echo THIRD_TRY` **timeout=30** | **status=timeout**，output 同上（**不自愈**） |
| 9 | close → exec `echo FINAL_RECONNECT` timeout=60 | status=ok，output 含提示符+`FINAL_RECONNECT`，exit_code=0 |

**干扰排除**：① 同节点 F3 自动登录正常（步骤 1/5/9），凭据、getty、登录 dance 均好；② 登出前同一会话 exec 正常，close 后 exec 正常，工具与传输正常；③ send/read 能看到 `logout` 与 `login:`，串口与输出通道正常；④ 唯一变量=shell 已登出而 MCP 缓存会话仍标"就绪"（console host/port 未变，identity 比对不触发）；⑤ 两版 server（1983f5737、0b85f7218）行为一致。输出中无包装命令的回显，命令未到达 shell。

未覆盖：docker_exec（按用户指正，其正确验证路径为 device 两工具 + netmiko_device_type，非 console 四工具）。

### 8.2 F4 复测修订：A/B/C/D 矩阵（11-01，server 0b85f7218）

**修订原因**：§8.1 第 3 步 `console_read` 会排空通道，导致只测到"读中恢复"路径，写前恢复路径未覆盖；且未写明 `console_type=ssh` 的实际驱动。按评审意见重测。

**驱动更正**：`console_type=ssh` 时实际驱动是 **gns3_linux_ssh**（`_console_device_type()` 以 console_type 为准）；`netmiko_device_type=gns3_linux_telnet` 只标记 Linux 家族。F4 修复位于共享基类 LinuxShellBase，两条传输都覆盖，故结论对两传输均适用。

**方法（每步均经 MCP 工具）**：

| 变体 | 步骤 |
|---|---|
| 基线 | 节点启动后 exec `whoami; tty; echo BASELINE`，确认 shell |
| A 写前 | send `exit\n`（真实 LF，`sent` 回执为 `exit\n`）→ **3s/10s 不做任何 read** → exec `whoami && echo AFTER_A` timeout=20 |
| B 读中 | send `exit\n` → `console_read` 直到确认 `ubuntu-cloud login:`（排空）→ exec `whoami && echo AFTER_B` timeout=20 |
| C 自愈 | 变体失败后**不 close**，再 exec `whoami && echo AFTER_C` timeout=20 |
| D 对照 | `console_close` → exec `whoami && echo AFTER_D` timeout=60 |

判定：成功=status ok、exit_code 0、AFTER 标记恰 1 次；失败时记录 output 是否含 `Password:`、命令回显、`__MCP_DONE_` 残留。计时：status=timeout 即窗口耗尽（工具无 duration 字段，SSE 客户端已下线，无独立 wall-clock）。

**原始数据（UbuntuCloudGuest-1，qemu/console_type=ssh→gns3_linux_ssh，getty ttyS0）**：

| 步骤 | 返回（关键字段） |
|---|---|
| 基线 | status=ok，`ubuntu`/`/dev/ttyS0`/`BASELINE`，exit_code=0 |
| A（3s 不读） | **status=timeout**，output=`Ubuntu 24.10 ubuntu-cloud ttyS0\n\nubuntu-cloud login: `，exit_code=null，AFTER_A×0，无 Password: |
| A2（10s 不读） | **status=timeout**，output 同上，exit_code=null，AFTER_A2×0，无 Password: |
| C_A（不 close 重试） | **status=timeout**，output 同上，AFTER_C×0 |
| D_A（close→exec） | status=ok，`ubuntu@ubuntu-cloud:~$`/`ubuntu`/`AFTER_D`，exit_code=0，AFTER_D×1 |
| B（排空后 exec） | **status=timeout**，output=`Ubuntu 24.10 ubuntu-cloud ttyS0\n\nubuntu-cloud login: `，exit_code=null，**无 `Password:`**，无命令回显，AFTER_B×0 |
| C_B（不 close 重试） | **status=timeout**，output 同上，AFTER_C_B×0 |
| D_B（close→exec） | status=ok，`ubuntu@ubuntu-cloud:~$`/`ubuntu`/`AFTER_D_B`，exit_code=0，AFTER_D_B×1 |

**解释**：

1. **写前路径未触发**：logout 后 login: 在服务端缓冲停留 3s/10s，exec 仍超时且无重登。若服务端存在 "Console is at a login prompt; re-authenticating before sending the command" 分支，该分支在本机 getty 的 `login: ` 提示形态（末尾空格、无换行）下未命中，或只在新建会话时生效——需服务端日志确认。
2. **读中路径盲区确认（按评审要求单列）**：B 排空后命令被写入 login 提示，getty 未回 `Password:`（输出仅 banner+login:），而读中路径只认 `Password:`，故不触发重登，20s 超时。这是 "username-only getty 未覆盖"，不应简单记为 "F4 未修"。
3. **C 不自愈，D 正常**（close→exec 重连可自动重登）。
4. 失败场景 AFTER 标记 0 次、成功场景恰 1 次；输出无 `Password:`、无包装命令回显、无 `__MCP_DONE_` 残留 → 无重试重复执行迹象。
5. **快速失败未出现**：全部失败均为 status=timeout（窗口耗尽），没有 status=failed + authentication 文案的快速失败形态。

**结论**：F4 的两条恢复路径在本机 Ubuntu getty 上均未生效；读中路径的具体盲区=username-only getty（已单列）。最终路径断言需服务端日志（"before sending" vs "retrying once"）；MCP 工具无日志读取能力，需用户侧提供日志行。
