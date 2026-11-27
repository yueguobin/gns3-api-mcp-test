# LDAP 联测问题排查汇总：OpenLDAP × Windows AD（跨阶段附录）

| 项 | 内容 |
|---|---|
| 记录范围 | 阶段 38–40 全部联测（2026-11-24 ~ 11-27）中 **目录侧/环境侧** 的问题汇总与对照；gns3-server 代码层问题不在本文范围（见各阶段报告与 PR 评论） |
| 性质 | 两类目录（OpenLDAP 2.6.15 容器 / Windows AD 2022 Core 单机）联调中遇到的问题**性质高度同类**——TLS 信任链、属性可见性、服务挂死、账号锁定策略——集中一处对照记录，供复现与排障 |
| 关联 | OpenLDAP 细节：阶段38（§6 复现手册）/ 阶段39 报告；AD 细节：`阶段40附录_Windows-AD环境搭建问题排查记录.md`；脚本：`labs/pr3103-retest-scripts/`、`labs/pr3103-ad-test-scripts/` |

---

## 1. OpenLDAP 侧问题清单（阶段 38–39）

| # | 问题 | 现象 | 根因 | 修复/规避 |
|---|---|---|---|---|
| 1 | 容器崩溃循环（v2 镜像） | openldap 2.6.15 容器 Exited(1) 循环 "This account is not available" | GNS3 docker 包装 init.sh `su $GNS3_USER` 降权，而 v2 镜像声明 `User=ldap` 且 shell=`/sbin/nologin` | 上游修复 PR #3108：shell 为 nologin 时兜底 `su -s /bin/sh`；**切分支/重部署后跑 docker 节点前先 `grep SU_SHELL_ARG init.sh`**（复发过一次） |
| 2 | 容器重建丢数据+失联 | 重建后目录数据只剩 base 条目、eth0 无 IPv4 | 非持久卷 + GNS3 注入的 init.sh 网络模板全注释（不配网） | 三卷持久化（data/slapd.d/backups）+ 复现手册一键重导 LDIF/ACL/TLS；网络侧 udhcpc 依赖 |
| 3 | 默认 ACL 全禁读 | svc-gns3 能 bind 但搜索全 32 No such object | 默认 `{1}mdb` 第 2 条 `by * none` | 1.5.0：改 `by users read`；2.6.15：属性白名单制（见 #4） |
| 4 | 组解析被 ACL 拦 | 组映射成员缺失 | 2.6.15 v2 默认 `{2}` 属性白名单**无 member**，`{(objectClass=groupOfNames)(member=…)}` 被 `{3} by * none` 拦 | `labs/openldap26-acl-member-read.ldif`：{2} attrs 追加 member |
| 5 | 过滤器属性不可见 | filter 加 description 条件后，**带了标记的用户也 401** | filter 引用的属性必须能被 bind_dn 读到——{2} 白名单没有 description → 按"属性不存在"匹配失败 | `labs/openldap26-acl-description-read.ldif`：{2} attrs 追加 description（阶段39 测试34 双向实证） |
| 6 | TLS 主机名校验 | `verify_cert=True` + IP 形式 uri 必挂 | ldap3 2.9.1 在 py≥3.12 的 match_hostname **只认 dNSName SAN**（有 DNS SAN 时 CN 也不查），IP 永不匹配 | uri 一律用域名 + 证书 SAN 含 DNS 名；IP uri 做负例（证明校验生效） |
| 7 | TLS 证书放置 | olcTLS* 写 frontend 库条目报 error 65 | TLS 属性挂在 **cn=config 全局条目**，不在库条目 | 证书入持久卷（属主 911/600）+ `docker cp` + olcTLS* 三属性挂全局；VM21 装 CA + hosts |
| 8 | ppolicy 配置连环坑 | 策略条目建不出/olcPPolicyDefault 写不进/模块删不掉 | pwdPolicy 是辅助类必须配 organizationalRole 结构类；olcPPolicyDefault 需**活跃 overlay**（属性动态注册）；olcModuleLoad 运行时不可删（rc=80 惰性残留） | 镜像自带 cn={4}ppolicy schema 免导入；模块+overlay+策略条目+pwdPolicySubentry 四步配方（阶段39 测试31） |
| 9 | 半宕超时形态 | `docker pause` 后登录挂起 | 应用僵死但端口通 | 配置 timeout=10 兜住：精确等满 10.02s 返 401，unpause 秒恢复 |
| 10 | uid 大小写 caseIgnore | 大写 uid=Alice 条目建不出（Already exists） | caseIgnore 匹配归一 | 大小写场景由登录串触发，目录侧无法准备两个 DN |

## 2. Windows AD 侧问题清单（阶段 40）

| # | 问题 | 现象 | 根因 | 修复/规避 |
|---|---|---|---|---|
| 1 | StartTLS 全拒（**耗时最长的坑**） | GNS3 报 `Failed to bind: unavailable`（2.69ms）；CERT_NONE 也挂；openssl 实证 `STARTTLS failed, LDAP Result Code: 52` | 自签证书只进 My 库、链构不成 → LSASS 拒选为服务器凭据（Schannel 36886 每 10s 一条） | **证书同时导入 LocalMachine\Root（自信任）+ 重启 DC**（LSASS 不动态重扫）；诊断扩展用 OID 原值（中文系统 FriendlyName 本地化） |
| 2 | AD 模块挂死（**复发两次**） | `Get-ADDomain`/`Set-ADDefaultDomainPasswordPolicy` 服务端 shell 无返回（>27min / >44min），拖垮后续调用；pywinrm `read_timeout` 本机不生效 | DC 重启后 ADWS 未就绪即调用会楔死并常驻；低配单核 DC 上 AD 模块整体不可靠 | **彻底弃用 AD 模块**：组操作/策略改写一律 ADSI 直写（`Put`+`SetInfo`）+ 每个 WinRM 调用客户端看门狗（守护线程超时弃单，`16_ad_extra_fix.py`） |
| 3 | 默认密码策略 | 复杂度策略拒绝测试口令 gns3test | 域默认复杂度开 + 最短 7 位 | ADSI 直写 `pwdProperties=0, minPwdLength=1`（不用 Set-ADDefaultDomainPasswordPolicy，避开 #2） |
| 4 | 管理面杂项 | ping 不通 / 无 SSH / PS 慢 | 防火墙默认禁 ICMP；Core 不带 OpenSSH；1 vCPU | WinRM 5985（默认开）为主通道；端口探测代替 ping；长任务后台+日志 |
| 5 | 测试脚本口令笔误 | svc-gns3 登录 401 | 测试侧误用 gns3test（实际 svcldap123） | 修正后 200；记录防误读为产品行为 |

## 3. 同类问题对照（两目录 × 同一维度）

| 维度 | OpenLDAP | Windows AD | 共性结论 |
|---|---|---|---|
| **TLS 信任链** | 自签 CA 装入 VM21 系统信任库 + uri 用域名（SAN dNSName） | 自签证书 Root 自信任 + 重启 DC（LSASS 重扫） | 自签证书的信任是**两端共同的最大坑**；配方都是"证书入库 + 信任到根 + 重载/重启"三件套，缺一不可 |
| **属性可见性** | 白名单制：{2} attrs 决定 bind_dn 能读什么（member/description 两个坑） | 默认允许：认证用户全可读（无此坑） | 权限模型相反。给 PR 写 filter 时，OpenLDAP 要先确认白名单，AD 开箱即用 |
| **账号锁定** | ppolicy overlay + subentry（配方四步，坑多） | 域锁定策略（ADSI 直写三属性即可） | 行为形态完全一致：**目录级锁定先于 GNS3 限速器触发**（正确密码也 401）+ 到期自动解锁 |
| **密码策略** | 目录接受任意口令（含明文/特殊字符/中文） | 默认复杂度拒绝，须先放宽 | 联测前先把策略调到与测试口令兼容，否则建用户就失败 |
| **服务挂死** | docker pause 半宕 → GNS3 timeout=10 兜住 | ADWS 楔死 → WinRM/客户端无限挂 | 前者是被测系统的健壮性表现（positive），后者是环境管理面问题（negative）——同是"挂"，性质相反 |
| **环境杂项** | v2 镜像端口 3890/6360、su-nologin、caseIgnore | 无 SSH/禁 ICMP/中文本地化/PS 慢 | 每种环境都有一筐与 LDAP 本体无关的杂项，排障时先列环境清单再查协议层 |

## 4. 共性经验（可复用规则）

1. **先探协议层，再看应用层**：目录不通时，`ldapsearch`/`openssl s_client` 两条命令即可把问题切到网络/TLS/目录三层之一（本轮 AD 52 破案、OpenLDAP 32 拦截都是这么定位的）。
2. **自签证书三件套**：入库（含私钥）→ 信任到根 → 重载服务。任何一环缺失，症状都是"握手层拒绝"而非"校验失败"。
3. **权限模型的默认方向决定排障路径**：OpenLDAP 默认拒绝（缺白名单=查无此属性），AD 默认允许（问题集中在证书选择与模块挂死）。
4. **不可靠通道一律加看门狗**：pywinrm 的 read_timeout 在本机不生效——所有远程调用套守护线程超时弃单，宁可丢一次调用不可丢整个会话。
5. **测试口令先过策略**：目录侧密码策略（复杂度/长度/锁定）是联测第一道隐形闸门，建树之前先对齐。
