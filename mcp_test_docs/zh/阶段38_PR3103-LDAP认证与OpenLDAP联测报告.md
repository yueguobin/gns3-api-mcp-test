# GNS3 PR 3103 LDAP 认证与 OpenLDAP 联测报告（阶段 38）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-11-25（当日目录升级 2.6.15 后 TLS 面补测完成）；**2026-11-26 全矩阵复测 13/13 全绿（见 §5）** |
| 被测对象 | gns3/gns3-server **PR #3103**（feat/ldap-auth，本地分支 merge-ldap-3103；VM21 部署构建 dist-info 仍标 3.1.0.dev8，以功能判分支）+ **OpenLDAP-1**（osixia/openldap:**2.6.15**，ldap://ldap.example.org:**3890**，IP=192.168.101.31；首测时为 1.5.0:389，见发现 3/4） |
| 测试范围 | LDAP 认证全矩阵 13 项：组映射/双组重算/撤销回收/升降翻转/JIT fallback/大小写归一/DR fallback/TLS 路径/登录限速/诊断端点/密码掩码/断目录期 token 行为 |
| 测试方式 | controller REST API（curl + admin token）为主，目录侧本机 `ldap*` 命令（openldap2 客户端）直连 389，MCP 只用于 node_stop/node_start，日志经 SSH 取证（grep 需 `-a`，日志含二进制字节） |
| 结果标记 | ✓ 通过 · ⚠️ 通过但有注意点 · ✗ 缺陷 |

## 0. 环境与前置

- **目录侧当日重建**：容器疑似被重建过（数据卷丢失 + eth0 无 IP 双故障），网络侧用户手动修复；目录用 `labs/openldap-gns3-pr-test.ldif`（`-c` 续跑）+ `labs/openldap-acl-users-read.ldif`（ACL 补丁）重建并全验证。15 条目：base + 3 OU + svc-gns3 + 6 用户（alice/bob/carol/dave/erin/frank，统一密码 gns3test）+ 4 组（all-staff/gns3-superadmins/gns3-admins/gns3-testers，groupOfNames）。`uid=Alice` 大写条目依旧建不出（caseIgnore 归一撞 uid=alice），大小写陷阱只能在登录串侧触发。
- **目录侧当日升级 2.6.15（TLS 补测前置）**：用户将节点重建为 osixia/openldap:2.6.15（v2 镜像，破坏性升级）。坑与配套全记录：①镜像监听端口变 **3890/6360**（非 389/636）；②容器 Exited(1) 崩溃循环——GNS3 docker 包装 `init.sh` 用 `su $GNS3_USER` 降权，而 v2 镜像声明 `User=ldap` 且 passwd shell=`/sbin/nologin`（1.5.0 未声明 User+shell=/bin/sh 故无事），见发现 4；③v2 默认 ACL 是属性白名单（`{2}` by users read 但**无 member**），组解析会被 `{3} by * none` 拦——补丁 `labs/openldap26-acl-member-read.ldif`；④TLS 证书自备（CN=IP，SAN 含 IP+DNS，存 `/var/lib/openldap/openldap-data/tls/` 持久卷），VM21 装入系统 CA 库；⑤VM21 加 hosts `ldap.example.org→192.168.101.31`（**ldap3 主机名校验不接受 IP**，见发现 5）；⑥测试树 LDIF 重导入 + conf uri 换 `ldap://ldap.example.org:3890`。
- **GNS3 侧配置**（/opt/gns3/server/gns3_server.conf [LDAP] 段 + API 生效态一致）：uri=ldap://ldap.example.org:3890、bind_dn=svc-gns3 完整 DN、base_dn=**ou=gns3,dc=example,dc=org**（一个 base 同时罩住 ou=people 与 ou=groups，规避 web UI 里 group_search_base=base_dn 的限制）、user_search_filter=`(&(objectClass=person)(uid={username}))`、user_attr_username=uid、fallback_to_local=True。group_mapping 终态 `{"gns3-admins":"Administrators","gns3-testers":"Testers"}`。**终态 start_tls=True + verify_cert=True**（TLS 补测后保留为常态）。
- **热修前置**：阶段内发现 PR 阻断级 bug（见发现 1），VM21 venv 内 ldap.py 已打 `labs/ldap-3103-getinfo-none.patch`（原文件备份 `ldap.py.bak-getinfo`），重启服务后开测。**下次 wheel 重部署会覆盖热修，须重打。**
- 本地 admin 默认凭据 admin/admin 有效（RBAC 开箱默认）。

## 1. 逐项测试结果

| 测试项 | 场景 | 结果 | 关键证据 |
|---|---|---|---|
| 测试1 | bob/carol/erin 登录 → gns3-admins 映射 | ✓ | 三人全 200；`GET /groups/{id}/members` 权威核对 **Administrators=[bob,carol,erin]** 精确；日志 `Assigned user … group 'Administrators'` |
| 测试2 | carol 双组（admins+testers） | ✓ | 配 gns3-testers→Testers 映射后登录，**Administrators ∋ carol ∧ Testers ∋ carol**；且因有映射组不再落 Users（fallback 仅零映射时生效，逻辑正确） |
| 测试3 | dave 登录时 Testers 映射未配 | ✓ | 静默落 default_group Users，无报错、不自动建组；映射配上后（测试2 流程）自然回流 Testers |
| 测试4 | frank（gns3-superadmins）不映射 | ✓ | 落 Users，is_superadmin=False（分支已无 superadmin_groups 字段，超管=GNS3 Administrators 组成员身份） |
| 测试5 | 登录串 "Alice"（大写） | ✓ | HTTP 200 且返回 `username: "alice"`；日志 canonical_username='alice'，last_login 更新在同一账号——casefold 归一无重复账号（对应提交 1b641bb49） |
| 测试6 | 组撤销重算 | ✓ | ldapmodify 删 carol 的 gns3-admins member → 再登录 **Administrators 被剥离**（bob/erin 保留）、Testers 保留、不落 Users；恢复 member → 登录回流。受管组每次登录重算声明完全成立 |
| 测试7 | frank 升降翻转 | ✓ | 加 gns3-superadmins→Administrators 映射登录 → ∈Administrators；删映射再登录 → 仅 Users。完整闭环 |
| 测试8 | DR fallback | ✓ | node_stop 停目录 → **admin 登录 200 仅 0.26s**（本地超管先于目录查询的设计实测成立）→ alice 新登录 401（3.1s，LDAP 连接失败后无本地账号）→ node_start 恢复 → alice 200（55ms） |
| 测试9 | TLS 路径（StartTLS 3890 / LDAPS 6360 / verify_cert 两态 / 负例） | ✓（2.6.15 补测后翻绿） | **StartTLS+verify_cert=True：carol 登录 200**（CA 入系统信任库 + 主机名 URI）；verify_cert=False：200；LDAPS+verify_cert=True：200；负例 LDAPS 用 IP uri+verify_cert=True → 401（校验非摆设，同时实锤 ldap3 的 IP 主机名限制，见发现 5）；TLS 路径错密码 401 ✓。首测在 1.5.0 上为 ⚠️（环境不兼容，见发现 3），升级 2.6.15 后全过 |
| 测试10 | 登录限速器（滑动窗口 5 次/60s） | ✓ | dave 连续错密码：5 次 401 → 第 6 次 **429 too_many_requests** → 限速期正确密码也 429（保护目录账号语义正确）→ 窗口过期后 200 解封 |
| 测试11 | POST /v3/settings/ldap/test | ✓ | 平铺 body（**非 {"LDAP":…} 包裹**，包裹 422）；`{"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":1.72}`；users_found=5 系 canary 搜索 size_limit=5 样本上限（ldap.py:544），非计数错误（树内实际 7 个 uid） |
| 测试12 | GET /v3/settings 密码掩码 | ✓ | bind_password 回显 `'**********'`（10 字符），无泄露 |
| 测试13 | 断目录期已发 token 行为 | ✓ | alice token 在目录停机期访问 `/v3/projects` 照常 200——JWT 本地校验 **fail-open**，已登录会话不受目录故障影响 |

## 2. 发现问题

### 发现 1（✗ 阻断级，PR 代码缺陷，已报 PR）
**纯 OpenLDAP 下所有 LDAP 登录必炸**：`_create_server()` 用 `get_info=ALL` 抓 schema → ldap3 `build_attribute_selection()`（operation/search.py:304）**只要 schema 存在就校验搜索 attributes 列表，不受 check_names 门控**（提交 4e111981c 的防御无效）→ 代码硬编码的 AD 属性（sAMAccountName/userPrincipalName/objectGUID/ipaUniqueID/nsUniqueId）在纯 OpenLDAP schema 全不存在 → 首次用户搜索抛 `LDAPAttributeError: invalid attribute type in attribute list` → 全员 401。
修复：`get_info=NONE`（schema 无其他使用点）。补丁 `labs/ldap-3103-getinfo-none.patch`，已热修 VM21 并实测全矩阵通过。根因报告已发 PR 评论 [#issuecomment-7151325456](https://github.com/GNS3/gns3-server/pull/3103#issuecomment-7151325456)。

### 发现 2（⚠️ 轻微，机制未定）
PUT /v3/settings（LDAP 映射变更）后的数秒窗口内，`GET /v3/access/groups` 偶发 404（`{"message":"Not Found"}`），伴随配置热重载出现、无服务端日志、可自愈、重试即过；no-op PUT 与事后复测均不触发。疑与 reload_and_notify 路由重建竞态相关，建议作者复查。

### 发现 3（✅ 已解除——升级 2.6.15 后 TLS 全通）
首测目录 osixia/openldap:1.5.0（slapd 2.4.57 + OpenSSL 1.1.1d，2019-2021 组件）与 python ssl（OpenSSL 3.5.x，本机 3.13 / VM21 3.14 双侧复现）握手必 `UNEXPECTED_EOF`（openssl CLI 反而能过，行为分裂）。当时 PR 的 TLS **错误路径**反而得到完整验证（verify 拒绝、StartTLS 失败、握手失败三条日志路径清晰）。**当日将节点升级到 osixia/openldap:2.6.15（slapd 2.6.15，2026-09 构建）后：StartTLS/LDAPS/verify_cert 两态/负例全数通过（见测试 9）**。结论：测试 9 的 ⚠️ 是老镜像组件年代问题，非 PR 缺陷；升级路径 1.5.0→2.6.15 属破坏性迁移，配套改造见"环境与前置"。

### 发现 4（GNS3 核心缺陷，与 PR 无关，已本地修复）
GNS3 docker 节点包装层 `init.sh` 以 `su $GNS3_USER` 降权启动镜像入口，`GNS3_USER` 取自镜像声明的 `Config.User`（docker_vm.py:749）。**当镜像声明的用户 shell 为 nologin/false 时容器必崩**（`This account is not available` → exit 1 → 循环）：osixia/openldap 2.6.x 声明 `User=ldap`（shell=/sbin/nologin）即触发，1.5.0 不声明 User 故幸免。修复：init.sh 检测目标 shell 不可用（nologin/false/true 或不可执行）时追加 `su -s /bin/sh`（busybox su 支持 `-s` 已实证）。本地修复分支 `fix/docker-su-nologin-shell`，值得报 GNS3 上游。

### 发现 5（ldap3 库限制，PR 继承，影响 verify_cert=True + IP uri 组合）
Python ≥3.12 移除 `ssl.match_hostname` 后，ldap3 2.9.1 回落到自带 backport（Python 3.4.3 语义），**明文规定 IP 地址不可作为主机名参与证书匹配**（只认 dNSName SAN；有 DNS SAN 时连 CN 都不查）。后果：`uri` 用 IP（如 ldaps://192.168.101.31:6360）+ verify_cert=True **永远验证失败**，无论证书多规范（IP SAN 齐全也不行，实测）。规避：uri 用域名 + hosts/hosts 解析（本测采用 ldap.example.org）。建议 PR 文档注明，或考虑上游 ldap3 修复。

### 观察（非缺陷）
- canary `users_found=5` = size_limit 样本上限（设计行为）。
- PUT /settings 后**必须显式回填 bind_password**：GET 回显掩码 `**********`，若把掩码原样 PUT 回去语义未测（本次全部显式传真值规避）。
- 断目录期 alice 401 耗时 3.1s（LDAP 连接失败耗时 + fallback），对 UI 交互偏长但可接受；connect_timeout 配置可调。

## 3. 终态与残留

- **目录侧（2.6.15）**：15 条目测试树完整；ACL `{2}` 已补 member（labs/openldap26-acl-member-read.ldif）；TLS 证书（CN=IP，SAN 含 IP+DNS，10 年期）在持久卷 `/var/lib/openldap/openldap-data/tls/`；svc-gns3 bind+搜索、carol member 过滤、alice bind 全验证通过。
- **VM21**：venv ldap.py 带 get_info=NONE 热修（备份 .bak-getinfo）；系统 CA 库已装 lab 证书（gns3-lab-ldap.crt）；hosts 加 ldap.example.org→192.168.101.31；conf 终态 uri=ldap://ldap.example.org:3890、**start_tls=True、verify_cert=True**（TLS 常态运行）；服务 active；组映射复核 Administrators=[bob,carol,erin]、Testers=[carol,dave,student-10(历史)]；ldap/test 诊断端点 StartTLS 下 success（latency 24.5ms vs 明文 1.7ms，TLS 开销正常）。
- **OpenLDAP-1 节点**：osixia/openldap:2.6.15 started；监听 3890（明文/StartTLS）+ 6360（LDAPS）；数据完整。
- **GNS3 本体**：用户已建分支 `fix/docker-su-nologin-shell` 修复 init.sh 的 su/nologin 兼容缺陷（发现 4）；**下次 wheel 重部署会覆盖 ldap.py 热修，须重打 labs/ldap-3103-getinfo-none.patch**。

## 4. 结论

PR 3103 的 LDAP 认证核心声明在本 OpenLDAP 环境**全部实测成立（13 项全过，含 TLS 认证面）**：JIT 开户、组映射、双组并存、撤销重算、升降翻转、大小写归一、DR 兜底、限速保护、密码掩码、诊断端点、StartTLS/LDAPS + verify_cert 两态 + 负例。一个阻断级兼容缺陷（发现 1）已定位、修复、验证并上报 PR；TLS 面首测的 ⚠️ 定案为老镜像组件年代问题（发现 3），升级 2.6.15 后翻绿。连带产出：GNS3 docker init.sh 的 su/nologin 兼容缺陷（发现 4，已本地修复，建议报上游）、ldap3 IP-uri 主机名校验限制（发现 5，建议 PR 文档注明）。建议作者：采纳 get_info=NONE 修复、复核发现 2 的重载竞态、注意 verify_cert=True 对 IP uri 不可用（发现 5）。

## 5. 全矩阵复测记录（2026-11-26，gns3server 修复重部署后）

在 2.6.15 终态环境（StartTLS+verify_cert=True 常态、双组映射在位）完整重跑 13 项矩阵，**13/13 全绿**，与首测结论一致：

- P1 免配置项：Alice→alice 归一、bob/carol/erin/dave/frank 全 200、Administrators=[bob,carol,erin] 精确、Testers=[carol,dave,student-10(历史)]、ldap/test success（users_found=5 系 size_limit，latency 14.79ms StartTLS 路径）、bind_password 掩码 ✓。
- P2 目录变更：删 carol member → Administrators 剥离 [bob,erin]、Testers 保留；恢复 member → 回流 [bob,carol,erin] ✓。
- P3 配置翻转（每次 PUT 后等 5s 重载窗口，测毕即恢复终态）：StartTLS+verify_cert=False 200；LDAPS ldap.example.org:6360+verify_cert=True 200；负例 LDAPS IP uri → 401（实锤发现 5）；frank 升（Administrators=[bob,carol,erin,frank]）/降（回 [bob,carol,erin]，frank∈Users）翻转 ✓。
- P4 DR：停目录 → admin 200@0.27s、alice 新登录 401（耗时 10s，连接超时路径）、**旧 token /v3/projects 200@7ms fail-open**；起目录 → alice 200@73ms ✓。
- P5 限速器：dave 5×401 → 第 6 次正确密码 429 → 限速期仍 429 → **t+60s 精确解封 200** ✓。

**新观察**：①LDAP **连接失败**导致的登录失败同样计入限速窗口（复测恢复期 alice 连续撞 429，首测只验证过错密码计数）——目录故障期间对同一用户名的重试会吃限速，语义仍属正确（保护目录/防爆破），但排障时需知晓。②容器重建后目录数据完整（持久卷生效），终态组员核对无漂移。

**复测期间插曲（已解决）**：node_start 触发容器重建，注入的 init.sh 来自本机控制器运行代码——工作树切到 `fix/ldap-sync-rbac-snapshot` 分支后 SU_SHELL_ARG 修复不在其祖先里（修复本体已进上游 **PR #3108**，commit d20b908f7），容器重建即复发 su/nologin 崩溃循环。恢复修复 + 重启 gns3server 后复现消失。**教训：切分支/重部署后跑 docker 节点前，先核对 init.sh 是否带 SU_SHELL_ARG（发现 4 的修复），否则容器重建即崩。**

## 6. 复现操作手册（命令级）

> 2026-11-26 本机整机重启后，以下步骤**全量重跑验证过**（冷启动级复现），输出均为当日实测采集。辅助脚本固化在 `labs/pr3103-retest-scripts/`（README 含顺序与注意事项）；引用的 LDIF/补丁全部在仓库 `labs/` 下。英文版同内容见 EN 报告 §4。

### 6.0 前置

- **GNS3 docker 包装已修**（init.sh 带非 root USER 修复，上游 #3108）。切分支/重部署控制器后、启动 docker 节点前必查：
  ```bash
  grep -c SU_SHELL_ARG ~/myCode/GNS3/gns3-server/gns3server/compute/docker/resources/init.sh \
                       ~/.local/share/GNS3/docker/init.sh   # 两处都须 >=1
  ```
  未修的包装会让 2.6.x 容器每次重建都崩循环（`This account is not available`）。

### 6.1 目录节点搭建（一次性）

**A1 建节点**：GNS3 内置 OpenLDAP appliance v2 模板（template_id `85b0a871-…`），local compute。生效参数（API 实测）：image `osixia/openldap:2.6.15`；environment 四项 `OPENLDAP_BOOTSTRAP_ORGANIZATION=Example Inc.` / `OPENLDAP_BOOTSTRAP_SUFFIX=dc=example,dc=org` / `OPENLDAP_BOOTSTRAP_DATA_ROOT_PASSWORD_HASHED=admin` / `OPENLDAP_BOOTSTRAP_CONFIG_ROOT_PASSWORD_HASHED=config`；extra volumes 三项 `/var/lib/openldap/openldap-data`、`/etc/openldap/slapd.d`、`/var/lib/openldap/openldap-backups`；监听 **3890/6360**（非 389/636）。bootstrap 仅**首次空库启动**生效；产出的凭据：目录管理员 `cn=admin,dc=example,dc=org`/`admin`，配置管理员 `cn=admin,cn=config`/`config`。

**A2 启动节点**（GUI 右键 Start 或 MCP `node_start`），记下容器 IP（本环境 192.168.101.31）。

**A3 导入测试树**（15 条目，`-c` 幂等）：
```bash
ldapadd -c -x -H ldap://192.168.101.31:3890 -D "cn=admin,dc=example,dc=org" -w admin \
        -f labs/openldap-gns3-pr-test.ldif
# 校验：people 下 grep -c "^dn:" -> 7；ou=gns3 下 groupOfNames -> 4
```

**A4 ACL 补丁（必做）**：v2 默认 `{2}` 白名单缺 `member`，组解析搜不到任何组：
```bash
ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,cn=config" -w config \
           -f labs/openldap26-acl-member-read.ldif
# 校验：olcDatabase={1}mdb 的 olcAccess {2} 里必须含 ...,member
```
（1.5.0 上还需 `labs/openldap-acl-users-read.ldif`——默认 ACL 会把 bind_dn 的搜索拦成 `32 No such object`。）

**A5 TLS 材料**：自签证书（CN+SAN 是 ldap3 校验对象）：
```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout server.key -out server.crt -subj "/CN=192.168.101.31" \
  -addext "subjectAltName=DNS:localhost,DNS:ldap.example.org,IP:192.168.101.31"
```
装进**运行中**容器的持久卷并挂到 `cn=config` 全局条目：
```bash
docker exec GNS3.OpenLDAP-1.<project-id> mkdir -p /var/lib/openldap/openldap-data/tls
docker cp server.crt GNS3.OpenLDAP-1.<project-id>:/var/lib/openldap/openldap-data/tls/
docker cp server.key GNS3.OpenLDAP-1.<project-id>:/var/lib/openldap/openldap-data/tls/
docker exec GNS3.OpenLDAP-1.<project-id> sh -c \
  'chown 911:911 /var/lib/openldap/openldap-data/tls/*; chmod 600 /var/lib/openldap/openldap-data/tls/server.key'
ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,cn=config" -w config \
           -f labs/openldap26-tls-config.ldif
```
实坑两枚：olcTLS* 挂 frontend 库条目 → **error 65**；重复 add 已存在属性 → **error 20**（改 replace）。持久性：证书在数据卷、TLS 配置在配置卷，重启/重建节点均不丢（11-26 重启后实测核验：server.crt 1192B、server.key 1704B、属主 911、key 600）。

**A6 控制器侧（VM21）**：
```bash
# 1) 部署 PR #3103 构建（PR head e057ecfa5+），确认修复在部署树里：
grep -n "get_info" <venv>/gns3server/services/ldap.py        # 期望 get_info=NONE
# 2) 域名解析（ldap3 backport 拒绝 IP 主机名，发现5）：
echo "192.168.101.31 ldap.example.org" >> /etc/hosts
# 3) 信任 lab CA（ldap3 verify_cert=True 走系统信任库）：
scp server.crt gns3@192.168.101.21:/tmp/gns3-lab-ldap.crt
ssh gns3@192.168.101.21 'sudo cp /tmp/gns3-lab-ldap.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates'
```
`/opt/gns3/server/gns3_server.conf` 的 `[LDAP]` 段全文（API 核验一致）：enabled=True；uri=ldap://ldap.example.org:3890；bind_dn=uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org；bind_password=svcldap123；base_dn=ou=gns3,dc=example,dc=org；user_search_filter=`(&(objectClass=person)(uid={username}))`；user_attr_username=uid；user_attr_email=mail；user_attr_fullname=cn；group_search_base=ou=gns3,dc=example,dc=org；group_search_filter=`(&(objectClass=groupOfNames)(member={user_dn}))`；group_mapping=`{"gns3-admins":"Administrators","gns3-testers":"Testers"}`；default_group=Users；**start_tls=True；verify_cert=True**；fallback_to_local=True；timeout=10。

重启服务后预检：`curl http://192.168.101.21/v3/version`（→ 3.1.0.dev8）；svc-gns3 bind+搜索 groupOfNames → 4 条。

### 6.2 跑矩阵

全程认证机制：`POST /v3/access/users/authenticate`（JSON）→ Bearer JWT；**settings 端点只认 Bearer**（Basic 被拒）；`PUT /v3/settings` 体形 `{"LDAP": {...}}` 且**必须回传真 bind_password**（GET 回掩码）；每次 PUT 后等 ~5s。

**阶段1 免配置项**（测试1–5、11、12）：`python3 -I labs/pr3103-retest-scripts/01_no_config_tests.py`。实测输出：admin 200；Alice→'alice'；bob/carol/erin/dave/frank 全 200；Administrators=[bob,carol,erin]；Testers=[carol,dave,student-10]；ldap/test success/users_found=5/latency≈14ms；掩码 PASS。

**阶段2 撤销重算**（测试6）：`ldapmodify` 删 carol 的 member（命令见 EN §4 Phase 2 或 labs 脚本 README）→ `02_membership_audit.py` 看到 Administrators=[bob,erin]、Testers 保留；`add: member` 恢复 → 回 [bob,carol,erin]。

**阶段3 TLS 变体 + frank 翻转**（测试9、7；脚本 finally 保证恢复终态）：`python3 -I labs/pr3103-retest-scripts/03_config_flips.py`。实测：verify_cert=False→200；LDAPS 域名→200；LDAPS IP→**401** 负例；frank 升降进出 Administrators。

**阶段4 DR**（测试8、13）：存 alice token（curl 存 /tmp/alice_token.txt）→ GUI/MCP 停 OpenLDAP-1 → 三连 curl：admin 200@0.27s、alice 401@10s、旧 token /v3/projects 200@6ms → 起节点 → `04_dr_recover_wait.py`（本次实测 t+0.1s 即 200；给足 60s 余量）。

**阶段5 限速器**（测试10，放最后——会锁 dave ~60s）：`python3 -I labs/pr3103-retest-scripts/05_rate_limiter.py`。实测：5×401 → 正确密码 429 → 限速期仍 429 → **t+60s 整点解封**。

### 6.3 复跑时的非显然行为

- PUT settings 后重载窗口：`GET /v3/access/groups` 可能 404 数秒（发现2），脚本等 5s 规避。
- **连接失败**的登录也吃限速窗口——目录故障期同一用户名重试会 429；恢复轮询里的 429 是限速器，不代表目录没起来。
- 未装 lab CA 的本机做 StartTLS 探测会报 `certificate verify failed (self-signed certificate)`——预期，本环境只有控制器是 TLS 客户端。
