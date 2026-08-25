# GNS3 MCP Node 模块修复复测报告（阶段 22）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-08-25 |
| 被测对象 | gns3server **3.1.0a5**（修复构建，覆盖分支：`fix/node-suspend-unsupported-405`、`fix/mcp-batch-order-and-delete-status`、`fix/mcp-node-file-get-newline`；重启后 `/mcp` 重连会话） |
| 复测范围 | 阶段 21 报出的 **N-1（suspend 假成功）/ N-2（批量乱序 + delete status 口径）/ P2-2（node_file_get 差 1 字节）** 专项 + Node 模块 20 工具全量回归 |
| 测试方式 | 仅经 MCP 工具接口；临时项目 `mcp-node-retest-0825`（VPCS×3 + IOU L3 + Alpine docker + 以太交换机，3 链路），测完已删，终态 `project_list` count=0 |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 1. 修复项逐一验证

### 1.1 N-1 suspend 假成功 → 已修（诚实 405）

| 场景 | 修复前（阶段 21） | 修复后（本次） |
|---|---|---|
| `node_suspend` VPCS | 返回成功，状态仍 started（假成功） | **405 "Suspend is not supported for VPCS nodes"**，状态保持 started ✓ |
| `node_suspend` IOU | 同上 | **405 "Suspend is not supported for IOU nodes"** ✓ |
| `node_suspend` docker（Alpine） | suspended ✓ | suspended ✓（行为不变） |
| `node_suspend_all` 干净状态 | 成功消息，仅 docker 翻转 | **"All nodes suspended"**，VPCS/IOU 的 405 被容忍（best-effort），仅 Alpine 翻转 ✓ |
| 恢复挂起（`node_start`） | — | suspended docker → started（start 自动 unpause）✓ |

405 为裸文本风格报错（同 closed 态 project_lock 的已知遗留风格），语义清晰可断言：**"报不支持" 即为正确行为**。

### 1.2 N-2① 批量乱序 → 已修（按提交序返回）

| 接口 | 提交顺序 | 返回顺序 | 结果 |
|---|---|---|---|
| node_create 批量 4 节点 | IOU → Alpine → ethsw → VPCS | R-1 → AlpineLinux-1 → Switch1 → PC1 | **一致 ✓**（阶段 21 同场景为乱序） |
| link_create 批量 3 链路 | PC1-Sw → R1-Sw → Alpine-Sw | 同提交序 | **一致 ✓** |
| node_start 批量 2 节点 | PC2 → PC1 | 同提交序 | **一致 ✓** |
| node_delete 批量 6 节点 | PC1→PC2→PC3→R-1→Alpine→Switch1 | 同提交序 | **一致 ✓** |

### 1.3 N-2② delete status 口径 → 已修（统一 "success"）

批量删除 6 节点逐项 `status:"success"` + `message:"Node … deleted"`，与 create/start 口径一致。阶段 21 的 `"deleted"` 不再出现。

### 1.4 P2-2 node_file_get 差 1 字节 → 已修（字节保真）

| 测试文件 | 磁盘字节 | returned_bytes | 结果 |
|---|---|---|---|
| LF + 尾换行（`hello 世界\nline2\n`，含 CJK） | 19 | **19** | ✓（旧 bug 场景 18≠19，已对齐；尾 `\n` 在 content 中真实保留） |
| 无尾换行（`no newline at end`） | 17 | **17** | ✓（不凭空补换行） |
| 分页 offset=1/limit=1 | — | 6（`line2\n`） | ✓（keepends 在分页路径同样生效，不丢行尾） |
| VPCS `save` 落盘 startup.vpc | 31 | **31** | ✓（`set pcname PC1\nip 10.99.0.1 24\n` 逐字节回读） |
| 字面转义文本（`\r` 被字面化的探针文件） | 7 | **7** | ✓（非文本字节序列原样往返） |

**CRLF 分支未能实测**（见 W-1）：MCP 工具参数无法注入真实 CR 字节，环境内也无现成 CRLF 文件（本版 VPCS `save` 落 LF）。修复声明为 keepends + 原样拼接，LF 分支行为佐证其机制，但 CRLF 逐字节保真建议在服务器侧用 REST 直发验证。

## 2. 新发现问题

| 编号 | 级别 | 问题 | 影响工具 |
|---|---|---|---|
| **N-3（阶段 22 新发现）** | 低 | `node_suspend_all` 对**已处于 suspended 的 docker 节点**再次调用时，compute 层 409 "container … is already paused" 直接上抛中断整个调用——非幂等，且 best-effort 容忍只覆盖 405 未覆盖 409。干净状态（无已挂起节点）下 suspend_all 正常 | node_suspend_all |
| **W-1（观察项，非服务器缺陷）** | 信息 | `node_file_write` 经 MCP 传参无法写入真实 CR：参数中 `\r` 以字面反斜杠文本落盘（探针 `a\rb\nc` → 7 字节字面文本）；`\n` 正常（真实换行）。因此 CRLF round-trip 无法从 MCP 侧构造验证。归因在调用方参数编码层，服务器 write 对真实 CR 的行为未知 | node_file_write（测试方法限制） |

## 3. 逐工具回归结果（20/20）

| # | 工具 | 测试场景 | 结果 | 备注 |
|---|---|---|---|---|
| 1 | node_list | 状态矩阵查询 ×5 + fields 过滤 | ✓ | |
| 2 | node_create 单个 | VPCS → PC2 | ✓ | 默认命名生效 |
| 3 | node_create 批量 | 4 节点混合类型 | ✓ | **返回顺序=提交序（N-2① 已修）** |
| 4 | node_get | R-1 全量 + Alpine + 假 UUID | ✓ | IOU 16 端口表/properties/command_line 完整；404 清晰 |
| 5 | node_update | PC1 坐标 + console_auto_start | ✓ | 即时生效；返回全量详情（已知行为） |
| 6 | node_duplicate | stopped→PC3 / running→409 | ✓ | 默认名、tags/console_auto_start 继承、新 console 5006 |
| 7 | node_start 单个 | PC3 / Alpine（suspended 恢复） | ✓ | docker start 自动 unpause |
| 8 | node_start 批量 | [PC2, PC1] | ✓ | 顺序一致，逐项 success |
| 9 | node_start_all | 全量 | ✓ | 5/5 started |
| 10 | node_suspend 单个 | VPCS / IOU / docker | ✓ | **VPCS、IOU 诚实 405；docker 翻 suspended（N-1 已修）** |
| 11 | node_suspend_all | 干净状态 / 含已挂起节点 | ⚠️ | 干净状态 ✓（best-effort 容忍 405）；**含已挂起 docker 时 409 上抛中断（N-3）** |
| 12 | node_stop 单个 | PC2 | ✓ | |
| 13 | node_stop_all | 含 suspended Alpine | ✓ | suspended→stopped 直接可停；Switch1 保持 started（always-running） |
| 14 | node_console | PC1 | ✓ | ws_url + 10 分钟 JWT + websocat 命令 + token_sha256_prefix |
| 15 | node_links | Switch1（3 条）/ PC1（1 条） | ✓ | suspend/markers/filters 字段齐全 |
| 16 | node_isolate | PC1 | ✓ | 链路 suspend:true 实测翻转 |
| 17 | node_unisolate | PC1 | ✓ | suspend 复位 false |
| 18 | node_file_list | Alpine / PC1 目录 | ✓ | 含 file_type 探测（佐证磁盘字节数） |
| 19 | node_file_write | LF/CJK、无尾换行、CR 探针 ×5 | ✓ | UTF-8 无损；**真实 CR 无法注入（W-1）** |
| 20 | node_file_get | §1.4 全部场景 + 分页 | ✓ | **字节保真（P2-2 已修）**；删除后复读 404 |
| — | node_file_delete | 4 个测试文件 | ✓ | 删除后 404 含完整路径 |
| — | node_delete 批量 | 6 节点 + 假 UUID | ✓ | **逐项 "success"（N-2② 已修）**；链路随节点自动清理；404 清晰 |

## 4. 电源生命周期状态矩阵（修复后）

| 节点类型 | start 后 | suspend 后 | suspend 报错 | stop 后 |
|---|---|---|---|---|
| VPCS | started | 不可挂起 | **405（诚实）** | stopped ✓ |
| IOU L3 | started | 不可挂起 | **405（诚实）** | stopped ✓ |
| docker（Alpine） | started（suspended 再 start → started，自动 unpause） | **suspended ✓** | — | stopped ✓（可从 suspended 直接停） |
| ethernet_switch | started（天生） | 不适用 | — | 不可停（always-running，符合设计） |

- 恢复统一走 `node_start`（未加 `node_resume`，与上游决策一致：start 即万能恢复，避免平行路径）。
- 挂起语义对 MCP 完全可观测：**要么状态翻转（docker/qemu 系），要么明确 405**。

## 5. 统计

- 实测工具：**20 / 20**（与阶段 21 同口径；"22" 系上轮口误，服务器侧确认 20 个，无遗漏新工具）
- 通过：19 · 通过带注意点：1（node_suspend_all，因 N-3 边界）
- 修复验证：**N-1 ✓ / N-2① ✓ / N-2② ✓ / P2-2 ✓（LF 全场景；CRLF 分支受测试手段限制未覆盖）**
- 新发现：N-3（suspend_all 非幂等，409 already-paused 上抛）；W-1（MCP 参数无法注入 CR，观察项）
- 测试痕迹：6 节点 + 3 链路 + 5 个测试文件全部清理，项目已删，终态 `project_list` count=0
