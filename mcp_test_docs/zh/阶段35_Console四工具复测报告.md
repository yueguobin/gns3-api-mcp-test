# GNS3 MCP Console 四工具复测报告（阶段 35）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-11-01 |
| 被测对象 | gns3server **3.1.0.dev8+a8e226b18**（server_version 实测；上一轮 6d7ed5219）。MCP 侧版本不可经工具观测；本轮会话工具列表中**无 console_login**（阶段 34 的登录工具问题无法复测） |
| 复测范围 | console_exec / console_send / console_read / console_close 四工具：基础功能、send/read 配合、命令守卫、错误提示、登出后使用、无凭据场景、上轮修复项回归 |
| 明确排除 | docker_exec 传输（既定排除）；IOU 拒收门槛与 close 幂等（用户裁定砍掉，阶段 33 已验证）；并发调用（单 console 串行是设计语义，非合法场景）；`\x03`/裸 `\r` 真控制字符（harness 只能发字面字符串，环境限制同前） |
| 测试方式 | 仅经 MCP 工具接口；项目 `Console-Ubuntu-Test`（b4ce7670），测完已还原（CG-1 凭据 ubuntu/ubuntu、UDG-4 凭据清回空、全部节点 stopped、project closed） |
| 结果标记 | ✓ 通过 · ✗ 未通过 · ⚠ 注意 |

## 0. 架构前提（用户澄清，本轮口径）

- **一个节点只有一条 console**，四个工具在同一条 console 上串行使用，不存在多通道并行；console_type=ssh 只是 GNS3 对这条 console 的传输封装，**不是 sshd 的多通道 SSH**。
- 会话生命周期：**首次连接**（节点启动后第一次连，bash 打出初始提示符）→ **复用**（TTL 内，默认 60 秒）→ **脱落**（close 或空闲超时）→ **再次连接**。本轮最重要的失败（测试19）就发生在"再次连接"这一步。

## 1. 测试项

### 测试01 基础命令执行（telnet / ssh / QEMU 三传输） ✓

`whoami; tty` 分别在 UDG-1（telnet）、UDG-2（ssh）、CG-1（QEMU 串口）执行：telnet/ssh 返回 root + /dev/pts/0，QEMU 返回 ubuntu + /dev/ttyS0 且自动登录成功。

### 测试02 退出码精确性 ✓

`sh -c 'exit 7'` → exit_code=7；`nosuchcmd_xyz` → exit_code=127。

### 测试03 会话上下文跨调用保持 ✓

`cd /var && export CTX_STAGE=35` 后，下一次 exec 能回收 pwd=/var、CTX=35。

### 测试04 长命令输出无标记泄露 ✓

188 字符回行命令输出纯净，无 `__MCP_DONE__` / `__MCP_PROMPT__` 泄露（上上轮修复保持）。

### 测试05 大输出截断 ✓

400 行输出 + max_chars=1000 → truncated=true，输出约 1000 字符封顶。
（备注：本轮自测命令里 `$i_padding` 被 bash 按变量名 `i_padding_padding_padding` 展开成空，属测试命令写法问题，非工具缺陷。）

### 测试06 命令超时契约 ✓

`sleep 30` + timeout=5 → status=timeout、exit_code=null、hint 齐全（nonce 标记格式）。

### 测试07 超时后输出收尾 ✓

console_read 收到 `SLEEP_DONE` + `__MCP_DONE_6ee7269a_0__`，命令真实完成标记可回收。

### 测试08 超时后会话复用 ✓

超时后下一发 exec 正常执行。

### 测试09 send 裸文本只回显不执行 ✓

send `ping -c 15 127.0.0.1`（不带换行）只回显不执行，`sent` 回执一字不差（第一坑行为保持）。

### 测试10 send 换行触发执行并全量回收 ✓

补一个 `\n` 后 ping 15 包 + 统计行全部经 read 收回。

### 测试11 read 增量返回 ✓

多轮 read 只返回新增输出。

### 测试12 交互命令拒绝 ✓

`top` / `tail -f` 被拒并给出建议形式；`top -b -n 1 | head -3` 实测可用。

### 测试13 python 非交互形式放行（回归验证） ✓

QEMU 上 `python3 -c` / `python3 -V` / `python3 -m json.tool` / `/usr/bin/python3 -c` 全部放行并执行成功；裸 `python3` 仍正确拒绝且文案与建议一致（阶段 33 修复保持）。

### 测试14 伪造完成标记无效（回归验证） ✓

`echo "__MCP_DONE_7__"; echo AFTER7` → exit_code=0、标记行原样保留；假标记+sleep 也等真实完成（阶段 33 nonce 修复保持）。

### 测试15 QEMU 自动登录（回归验证） ✓

CG-1 开机后首次 exec 自动登录成功（ubuntu / /dev/ttyS0 / exit 0），阶段 32 的登录损坏不复发。

### 测试16 错误提示（未启动 / 不存在节点） ✓

未启动节点：`Node 'xxx' is not started (status: stopped). Start it first (node_start).`；不存在节点：报错并列出全部已知节点。

### 测试17 登出后再执行命令 ✗ 未通过（第三轮确认未修）

CG-1 已登录会话 send `exit` 登出回到 `login:` 后：

| 步骤 | 结果 |
|---|---|
| 登出后不做任何 read、等 3 秒以上再 exec（20s） | timeout，输出停在 login 提示符，无命令回显 |
| read 排空确认 login: 后再 exec（20s） | timeout，无 `Password:`（用户名提示符形态识别不了），命令未达 getty |
| 失败后不 close 直接重试 ×2 | timeout，不自愈 |
| close → exec（对照） | ✓ 自动重登录成功 ×3 |

与阶段 33/34 行为一致：登出后恢复只有 console_close 一条路。

### 测试18 无凭据时快速失败 ✓ 已修（阶段 34 未修项）

CG-1 清掉 default_password、close、console 停在 `login:` 时 exec：立即返回 `status=failed: Console requires a login but the node has no default_password configured`，不再像阶段 34 那样干等 20 秒。

### 测试19 docker 节点会话关掉或过期后四工具不可用 ✗ 未通过（本轮新发现，最严重）

**现象**：UDG-1（telnet）/UDG-2（ssh）首次连接和 TTL 内复用全部正常；空闲超过 60 秒（TTL 过期）后再调用，exec / send / read 全部立即失败：

```
Console authentication failed: Console requires a login but the node has neither default_username nor default_password configured   （telnet 节点）
Console authentication failed: Console requires a login but the node has no default_password configured                            （ssh 节点）
```

docker 的 console 本来就是现成的 root bash，不需要任何登录。

**鉴别实验**：

| 实验 | 结果 | 说明 |
|---|---|---|
| 串行单发（排除并发因素） | 同样失败 | 与并发无关 |
| console_send / console_read | 同样失败 | 三工具共用会话建立路径，全灭 |
| console_close 后重试 | 仍失败 | close 救不回 |
| UDG-4 全新启动后首次 exec | ✓ 正常 | 首次连接路径是好的 |
| UDG-4 活会话 close 后立即 exec | 同样失败 | **只要不是首次连接就失败**，不用等 TTL 过期 |
| 给 UDG-4 设账号密码后再连 | `Login failed: 192.168.1.3` | 带凭据也不通（对不需要登录的 bash 盲做登录） |
| UDG-1 停掉再启动后 exec | ✓ 恢复 | 恢复手段=重启节点（console 全新首次连接） |
| 对照 CG-1（QEMU）close → exec | ✓ 自动重登录 | "再次连接"路径在真 login 提示符+有凭据时正常 |

**定性与影响**：

- 再次连接同一条 console 时，会话建立逻辑把"安静的、不再打印提示符的 bash"误判为"需要登录"：无凭据 docker 节点直接失败，有凭据的盲做登录也失败。
- **docker 节点（这四个工具的主要使用对象）变成一次性**：一次会话脱落（close 或空闲超过 60 秒）后工具全废，只能重启节点。命令之间间隔超过 60 秒的正常使用节奏必然踩中。
- **对照基线**：阶段 33（server 1983f5737 / 0b85f7218）close → exec 三传输重连均成功——本轮为回归。
- QEMU/串口登录场景不受影响。

### 测试20 失败会话的凭据快照不更新 ⚠ 新发现（边缘）

测试18 失败后，node_update 把 default_password 恢复为 ubuntu，再 exec 仍报"无凭据"；console_close 一次即愈（新会话重新读节点凭据，自动登录成功）。失败会话缓存不重读凭据，close 可兜底。

## 2. 统计与优先级

- 通过 **17** 项（测试01–16 + 测试18，含上轮修复回归全保持）；未通过 **2** 项：测试19（docker 会话脱落不可用，新回归，最严重）、测试17（登出后不可用，第三轮确认）；注意 **1** 项：测试20。
- 修复建议优先级：**测试19（阻断 docker 节点日常用法）＞ 测试17（登出边界，close 可绕）＞ 测试20（边缘）**。
- 测试19 修复后复测点：① docker 节点 exec → close → exec（阶段 33 原场景）② docker 节点两次调用之间空转超过 ttl 后 exec ③ 有凭据 docker 节点再次连接 ④ QEMU 场景不应回归。

## 3. 未覆盖

- console_login（阶段 34 的登录工具确认逻辑等问题）：本会话工具列表未暴露该工具。
- IOU 拒收门槛、close 幂等：用户裁定砍掉（阶段 33 已验证通过）。
- `\x03` / 裸 `\r` 真控制字符：harness 限制，同阶段 33。
- 附带观察：节点的 default_username / default_password 为只写字段（node_update 回显可见、node_get 报 Unknown fields），排障时只能靠 update 回读。

## 4. 现场清理

UDG-4 凭据已清回空、CG-1 凭据保持 ubuntu/ubuntu、四个节点全部 stopped、项目已 close。
