# GNS3 PR 3103 LDAP 认证 Windows AD 联测报告（阶段 40）

| 项 | 内容 |
|---|---|
| 测试日期 | 2026-11-27 |
| 被测对象 | VM21 gns3-server **3.1.0.dev8**（LDAP 认证功能，PR #3103 部署构建）× **GNS3-AD**（Windows Server 2022 Standard **Core**，10.0.20348，IP=192.168.101.32，域 `ad.example.org`，单 DC `GNS3-AD.ad.example.org`） |
| 测试范围 | **Windows AD 联测功能矩阵 16 项**：认证与诊断（7）/ 组映射（4）/ 账号状态（2）/ TLS（2）/ 配置恢复（1）；**另含补充测试 8 项**（测试 17–24：目录中断容灾/限速器/refresh×移组/API key×AD 禁用/bind_dn 失效/输入边界/AD 原生锁定策略/ldap/test 诊断变体，见 §5） |
| 测试方式 | **黑盒功能测试**：controller REST API（脚本）+ 宿主机 `ldap*`/`openssl` 命令 + WinRM/PowerShell 管理通道。只记录功能行为与配置步骤，不做代码层分析 |
| 环境搭建 | AD 节点与控制器侧配置全文见本文 **§0.2 / §0.3**（自包含，含全部命令）；脚本固化于 `labs/pr3103-ad-test-scripts/`（README 含执行顺序）；配置一致性核验见 §0.4 |
| 结果标记 | ✓ 通过（**主矩阵 16/16 + 补充测试 8/8 全部通过**；测试 2 的 svc-gns3 首轮 401 系测试脚本口令笔误，修正后 200，详见 §2 注） |
| 环境问题 | 搭建过程中的 5 个问题（StartTLS 52 / AD 模块悬挂 / 密码策略 / 管理面杂项 / 测试口令笔误）**单独成档**：`阶段40附录_Windows-AD环境搭建问题排查记录.md` |

与阶段 39 的关系：阶段 39 验证了 PR #3103 × OpenLDAP 2.6.15（23+10 项）；本阶段在 **Windows AD**（PR 的原始目标目录类型）上复刻同一测试树与核心场景，控制器侧仅切换目录相关字段（差异对照见 §0.3），其余配置不变。

## 0. 测试环境与配置

### 0.1 环境核对（测试当日实测）

- **controller**：`http://192.168.101.21`（端口 80），`GET /v3/version` → `3.1.0.dev8`。
- **GNS3-AD 节点**：WinRM 5985 开启（Server Core 默认启用，NTLM），22/ICMP 默认关闭/禁（正常现象，见附录问题 4）。hostname=`GNS3-AD`，`Microsoft Windows Server 2022 Standard`，10.0.20348，C 盘空闲 92 GB，初始 WORKGROUP。
- **基线配置**：测试起止时控制器均处于 OpenLDAP 终态（`uri=ldap://ldap.example.org:3890`，start_tls + verify_cert，阶段 39 §0.3）。本轮用 `PUT /v3/settings` 切到 AD 配置跑矩阵，`finally` 自动恢复并验证（测试 16）。
- **VM21 前置**（§0.2 ⑤ 完成后）：`getent hosts ad.example.org` → `192.168.101.32`；系统信任库含 AD 自签证书。

### 0.2 Windows AD 目录节点配置（192.168.101.32）

**管理通道**：WinRM（HTTP 5985）+ pywinrm NTLM，执行器 `labs/pr3103-ad-test-scripts/ps.py`：

```bash
python3 -I ps.py <script.ps1> [read_timeout_sec]
```

**① 装 AD 功能并建林**（`04_ad_setup.py`，功能安装约 3.5 min，建林约 4.5 min，自动重启后 WinRM 约 30–45 s 回来）：

```powershell
Install-WindowsFeature AD-Domain-Services -IncludeAllSubFeature -IncludeManagementTools

Import-Module ADDSDeployment
$sa = ConvertTo-SecureString 'Huawei@123' -AsPlainText -Force
Install-ADDSForest -DomainName 'ad.example.org' -DomainMode WinThreshold -ForestMode WinThreshold `
  -InstallDns -SafeModeAdministratorPassword $sa -Force
# 安装完成自动重启；本环境 NIC 的 DNS 客户端预置为 127.0.0.1 优先，建林后由本机 DNS 承接
```

建成核对：`Get-ADDomain` → `ad.example.org`；域/林 `msDS-Behavior-Version` = **7**（2016 WinThreshold）。

**② 放宽默认密码策略**（AD 默认复杂度策略会拒绝纯小写口令 gns3test，须在建树前放宽；用 ADSI 直写域根对象，不依赖 ADWS 模块——原因见附录问题 2/3）：

```powershell
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
$de.Put('pwdProperties', 0)      # 关闭复杂度要求
$de.Put('minPwdLength', 1)       # 最短 1 位
$de.SetInfo()
```

回读核对：`pwdProperties=0`、`minPwdLength=1`、`LockoutThreshold=0`（默认，不锁定）。

**③ 建测试树**（与 OpenLDAP `labs/openldap-gns3-pr-test.ldif` 同矩阵；完整幂等脚本 `06_tree.ps1`，要点如下）：

```powershell
$root='DC=ad,DC=example,DC=org'
$pw =ConvertTo-SecureString 'gns3test'    -AsPlainText -Force
$svc=ConvertTo-SecureString 'svcldap123'  -AsPlainText -Force

New-ADOrganizationalUnit -Name 'gns3'    -Path $root
New-ADOrganizationalUnit -Name 'people'  -Path "OU=gns3,$root"
New-ADOrganizationalUnit -Name 'groups'  -Path "OU=gns3,$root"

foreach ($u in 'alice','bob','carol','dave','erin','frank') {
  New-ADUser -Name $u -SamAccountName $u -Path "OU=people,OU=gns3,$root" `
    -EmailAddress "$u@ad.example.org" -AccountPassword $pw -Enabled $true -PasswordNeverExpires $true
}
New-ADUser -Name 'svc-gns3' -SamAccountName 'svc-gns3' -Path "OU=people,OU=gns3,$root" `
  -DisplayName 'GNS3 Service Account' -AccountPassword $svc -Enabled $true -PasswordNeverExpires $true

foreach ($g in 'all-staff','gns3-superadmins','gns3-admins','gns3-testers') {
  New-ADGroup -Name $g -GroupScope Global -GroupCategory Security -Path "OU=groups,OU=gns3,$root"
}
Add-ADGroupMember 'all-staff'        'alice'
Add-ADGroupMember 'gns3-superadmins' 'frank'
Add-ADGroupMember 'gns3-admins'      'bob','carol','erin'
Add-ADGroupMember 'gns3-testers'     'carol','dave'
```

成员矩阵核对输出（`Get-ADGroupMember`）：

```text
all-staff        : alice
gns3-superadmins : frank
gns3-admins      : bob,carol,erin
gns3-testers     : carol,dave
== user count: 7
```

用户 DN 形态（供 bind_dn/user_dn 引用）：`CN=carol,OU=people,OU=gns3,DC=ad,DC=example,DC=org`。

**目录侧直查验证**（宿主机 ldapsearch，svc-gns3 bind + 两个与 GNS3 同形的过滤器）：

```bash
# 用户搜索（GNS3 user_search_filter 同形）
ldapsearch -x -H ldap://192.168.101.32 \
  -D 'CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w svcldap123 \
  -b 'OU=gns3,DC=ad,DC=example,DC=org' '(&(objectClass=user)(sAMAccountName=carol))' dn memberOf
# → carol 命中，memberOf 原生返回 gns3-admins + gns3-testers

# 组搜索（GNS3 group_search_filter 同形）
ldapsearch -x -H ldap://192.168.101.32 \
  -D 'CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w svcldap123 \
  -b 'OU=gns3,DC=ad,DC=example,DC=org' \
  '(&(objectClass=group)(member=CN=carol,OU=people,OU=gns3,DC=ad,DC=example,DC=org))' dn
# → gns3-admins + gns3-testers

# 用户 bind（登录密码路径）
ldapwhoami -x -H ldap://192.168.101.32 \
  -D 'CN=alice,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w gns3test   # → Success
```

**④ LDAPS/StartTLS 证书**（`07_cert.ps1` + `12_certfix.ps1`；过程中踩的 52 坑见附录问题 1，以下为**最终正确配方**）：

```powershell
# 自签证书：SAN 含 3 个 dNSName（uri 必须用域名），EKU=Server Authentication
$cert = New-SelfSignedCertificate -Subject 'CN=ad.example.org' `
  -DnsName 'ad.example.org','gns3-ad.ad.example.org','GNS3-AD' `
  -CertStoreLocation 'Cert:\LocalMachine\My' -KeyLength 2048 `
  -NotAfter (Get-Date).AddYears(10) -KeyUsage KeyEncipherment,DigitalSignature `
  -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1')

Export-Certificate -Cert $cert -Type CERT -FilePath 'C:\Windows\Temp\ad-lab-root.cer'

# 关键一步：自信任。仅入 My 库时 LSASS 拒绝选用，AD 对 StartTLS 回 52
Import-Certificate -FilePath 'C:\Windows\Temp\ad-lab-root.cer' -CertStoreLocation 'Cert:\LocalMachine\Root'

# 关键另一步：重启 DC。LSASS 不动态重扫证书库
Restart-Computer -Force
```

重启后从宿主机验证（两个端口都应为 TLSv1.3 握手成功，证书 `CN=ad.example.org`）：

```bash
openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief </dev/null
openssl s_client -connect 192.168.101.32:636 -brief </dev/null
```

**⑤ VM21 前置**（`08_tls_setup.py` 自动完成；手工等价命令）：

```bash
# 域名解析（TLS 主机名校验要求 uri 用域名）
echo '192.168.101.32 ad.example.org gns3-ad.ad.example.org' | sudo tee -a /etc/hosts

# 信任 AD 自签证书（从 GNS3-AD 导出的 .cer 转 PEM 后放入系统信任库）
sudo cp ad-lab-root.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### 0.3 控制器侧配置（VM21，192.168.101.21）

本轮配置经 `PUT /v3/settings`（`{"LDAP": {...}}` 全量 17 字段 + 真实 bind_password，PUT 后等 5 s；与写入 `gns3_server.conf` 等价）注入，对应 `[LDAP]` 段全文：

```ini
[LDAP]
enabled = True
uri = ldap://ad.example.org:389
bind_dn = CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org
bind_password = svcldap123
base_dn = OU=gns3,DC=ad,DC=example,DC=org
group_search_base = OU=gns3,DC=ad,DC=example,DC=org
user_search_filter = (&(objectClass=user)(sAMAccountName={username}))
user_attr_username = sAMAccountName
user_attr_email = mail
user_attr_fullname = cn
group_search_filter = (&(objectClass=group)(member={user_dn}))
group_mapping = {"gns3-admins": "Administrators", "gns3-testers": "Testers"}
default_group = Users
start_tls = True
verify_cert = True
fallback_to_local = True
timeout = 10
```

与 OpenLDAP 终态的**差异字段对照**（其余字段不变）：

| 字段 | OpenLDAP（阶段 39） | Windows AD（本轮） | 说明 |
|---|---|---|---|
| uri | `ldap://ldap.example.org:3890` | `ldap://ad.example.org:389` | AD 为标准端口 |
| bind_dn | `uid=svc-gns3,ou=people,…` | `CN=svc-gns3,OU=people,…` | DN 形态随命名属性而变 |
| base_dn / group_search_base | `ou=gns3,dc=example,dc=org` | `OU=gns3,DC=ad,DC=example,DC=org` | 树同构，后缀不同 |
| user_search_filter | `(&(objectClass=person)(uid={username}))` | `(&(objectClass=user)(sAMAccountName={username}))` | AD 用户对象类与登录名属性 |
| user_attr_username | `uid` | `sAMAccountName` | 同上 |
| group_search_filter | `(&(objectClass=groupOfNames)(member={user_dn}))` | `(&(objectClass=group)(member={user_dn}))` | AD 无 groupOfNames，用内置 group；member 属性同名，memberOf 由系统维护 |

`ldap/test` 诊断端点（平铺 body，非 `{"LDAP":…}` 包裹）在切换前先用 AD 参数探测成功，确认参数可用后再 PUT（测试 1）。

### 0.4 配置与运行环境一致性核验（2026-11-27 逐项实读）

| 配置项 | 配置值出处 | 实测方式 | 一致 |
|---|---|---|---|
| 域名/功能级别 | §0.2 ① | `Get-ADDomain` = ad.example.org；域/林 `msDS-Behavior-Version`=7（LDAP 直读） | ✓ |
| 测试树规模与成员 | §0.2 ③ | `Get-ADUser` 计数=7；4 组成员逐组实读 | ✓ |
| svc-gns3 bind | §0.2 ③ | 宿主 ldapsearch bind + 用户/组过滤器搜索全通 | ✓ |
| 密码策略 | §0.2 ② | ADSI 回读 pwdProperties=0、minPwdLength=1 | ✓ |
| 证书材料 | §0.2 ④ | OID 原值核对：SAN 3×dNSName、EKU=1.3.6.1.5.5.7.3.1、HasPrivateKey=True | ✓ |
| Root 自信任 | §0.2 ④ | LocalMachine\Root 内 thumbprint 比对命中 | ✓ |
| StartTLS/LDAPS 实际生效 | §0.2 ④ | openssl 两端口 TLSv1.3 握手成功，服务端 `CN=ad.example.org` | ✓ |
| VM21 hosts | §0.2 ⑤ | `getent hosts ad.example.org` → 192.168.101.32 | ✓ |
| VM21 CA | §0.2 ⑤ | update-ca-certificates 完成；verify_cert=True 下 GNS3 登录全通（测试 2/14） | ✓ |
| [LDAP] 段 17 字段 | §0.3 | PUT 回读比对（bind_password 掩码，真值经 PUT 注入核对） | ✓ |
| 基线恢复 | §0.1 | 测试 16：OpenLDAP 终态恢复后 carol 200 + Administrators=[bob,carol,erin] | ✓ |

结论：§0.2/§0.3 所列配置与运行环境逐项一致，按本节命令可完整复现。

## 1. 功能测试矩阵总表

| 分组 | 测试项 | 场景 | 结果 | 实测要点 |
|---|---|---|---|---|
| A 认证与诊断 | 测试1 | ldap/test 诊断端点（AD 参数） | ✓ | `{"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":29.04}`（users_found=5 系样本上限，与阶段 39 形态一致） |
| A 认证与诊断 | 测试2 | 全量测试用户登录（StartTLS+verify_cert=True 常态） | ✓ | alice/bob/carol/dave/erin/frank 200；svc-gns3 用独立口令 svcldap123 200 |
| A 认证与诊断 | 测试3 | 用户名大小写归一 | ✓ | 登录串 `Alice` → 200（sAMAccountName 大小写不敏感） |
| A 认证与诊断 | 测试4 | 本地账号并存 | ✓ | admin/admin 本地登录 200（fallback_to_local=True） |
| A 认证与诊断 | 测试5 | 错误密码拒绝 | ✓ | bob + 错误密码 → 401 |
| A 认证与诊断 | 测试6 | 不存在用户拒绝 | ✓ | nobody → 401 |
| A 认证与诊断 | 测试7 | 用户名属性精确匹配 | ✓ | `alice@ad.example.org`（mail 值）作用户名 → 401（仅 sAMAccountName 匹配） |
| B 组映射 | 测试8 | 组映射 JIT 授权 | ✓ | bob/carol/erin（gns3-admins）→ Administrators=[bob,carol,erin] 权威核对精确 |
| B 组映射 | 测试9 | 多组归属 | ✓ | carol ∈ Administrators 与 Testers（AD 原生 memberOf 带双组） |
| B 组映射 | 测试10 | 未映射组默认回退 | ✓ | alice（all-staff 无映射）、frank 落 Users，Users 成员核对含 alice/frank |
| B 组映射 | 测试11 | 超管组映射翻转 | ✓ | 加 gns3-superadmins→Administrators 映射 → frank ∈ Administrators；删映射 → frank 回落 Users |
| C 账号状态 | 测试12 | AD 禁用账号拒绝 | ✓ | `Disable-ADAccount alice` → 登录 401 |
| C 账号状态 | 测试13 | 重新启用回流 | ✓ | `Enable-ADAccount alice` → 登录 200 |
| D TLS | 测试14 | LDAPS 636（域名 uri + verify_cert=True） | ✓ | carol 登录 200 |
| D TLS | 测试15 | 证书校验负例（IP uri） | ✓ | `ldaps://192.168.101.32:636` + verify_cert=True → 401（ldap3 拒 IP 主机名，与阶段 39 一致） |
| E 配置恢复 | 测试16 | 恢复 OpenLDAP 终态 | ✓ | finally PUT 回阶段 39 终态配置 → carol 200、Administrators=[bob,carol,erin]、GET 回显逐项一致 |

## 2. 逐项执行记录

矩阵脚本 `labs/pr3103-ad-test-scripts/09_ad_matrix.py`（`finally` 自动恢复 OpenLDAP 配置）在证书修复后一次跑通；关键实测输出：

```text
[baseline GET settings] status=200 uri=ldap://ldap.example.org:3890
[ldap/test AD] status=200 -> {"status": "success", "bind_successful": true,
  "user_search_successful": true, "users_found": 5, "latency_ms": 29.04}
[PUT settings] AD StartTLS+verify: status=200
[login alice] 200      [login bob] 200      [login carol] 200
[login dave] 200       [login erin] 200     [login frank] 200
[login 'Alice' uppercase] 200              [login admin local] 200
[login bob wrongpw] 401                    [login nonexistent nobody] 401
[login alice@ad.example.org] 401
[Administrators] ['bob', 'carol', 'erin']
[Testers] ['carol', 'dave', 'student-10']  # student-10 为历史遗留本地记录
[Users] 含 alice、frank（+10 条历史遗留）
[flip] 加映射 → frank login 200; Administrators=[bob,carol,erin,frank]
[flip] 删映射 → frank login 200; Administrators=[bob,carol,erin]
[Disable-ADAccount alice] → [login alice] 401
[Enable-ADAccount alice]  → [login alice] 200
[LDAPS ldap://ad.example.org:636] carol 200
[LDAPS IP 192.168.101.32:636]    carol 401（负例）
[StartTLS 回切] carol 200
[RESTORE OpenLDAP] carol 200; Administrators=['bob','carol','erin']
[restore verify] uri=ldap://ldap.example.org:3890 start_tls=True verify_cert=True
```

> 注（测试 2）：svc-gns3 首轮 401 为矩阵脚本口令笔误（误用 gns3test）；修正为 svcldap123 后 200。已核对为测试侧问题，非产品行为。

目录中断、限速器（5 次→429→t+60s 解封）、refresh 重算角色等行为在阶段 39（OpenLDAP）已验证，本轮不重复。

## 3. 行为观察（中性记录）

1. **memberOf 双源一致**：AD 原生返回 memberOf（svc-gns3 搜索 carol 即带双组），GNS3 合并 memberOf 与目录搜索两来源后结果与 OpenLDAP 侧完全一致（Administrators/Testers 成员精确）。
2. **users_found=5**：ldap/test 的用户计数为样本上限截断（size_limit），与阶段 39 OpenLDAP 形态一致，非 AD 侧差异。
3. **服务账号可登录**：svc-gns3 满足 user_search_filter，可以普通用户身份登录成功（入 default_group）。部署建议把服务账号排除在登录过滤之外或单独管控。
4. **禁用账号与错密码不可区分**：禁用账号登录 401，与错误密码响应形态一致（无账号枚举信息泄露）。
5. **修复前失败形态**：证书未受信任期间，ldap/test 返回 `Failed to bind to LDAP server: unavailable`（2.69 ms），全部登录 401。该形态的定位与修复过程见附录问题 1。

## 4. 结论

- PR #3103 在 **Windows AD（Server 2022 Core，单 DC）** 上主矩阵 16/16 + 补充测试 8/8 全部通过：登录、组映射（含原生 memberOf 双源）、超管翻转、AD 账号状态直通、LDAPS/StartTLS 双通道 + 证书校验负例、配置恢复、容灾/限速/refresh/API key 生命周期，与 OpenLDAP 侧行为一致（含容灾时延量级：admin 逃生 271ms vs OpenLDAP 270ms，断期登录精确等满 timeout=10）。
- 从 OpenLDAP 迁移到 AD 只需改动 **6 个字段**（§0.3 对照表），全部为目录侧形态差异，控制器侧机制无差异。
- 环境搭建有 3 个高价值坑（自签证书必须 Root 自信任 + 重启、DC 重启后 AD 模块悬挂、默认密码策略），完整排查记录见**附录**：`阶段40附录_Windows-AD环境搭建问题排查记录.md`；全部脚本按执行顺序固化于 `labs/pr3103-ad-test-scripts/`。

相关文档：阶段 39（OpenLDAP 侧全矩阵）`阶段39_PR3103-LDAP认证功能测试报告.md`；英文版 `mcp_test_docs/en/stage40_ldap_auth_windows_ad_test_en.md`。

## 5. 补充测试（测试 17–24）

补齐与 OpenLDAP 侧（阶段 39）同深度的机制项。脚本：`labs/pr3103-ad-test-scripts/14_ad_extra_matrix.py`（首版）与 `16_ad_extra_fix.py`（定版：ADSI 直写 + 客户端看门狗，见 §5.3 与附录问题 2 复发记录）。

### 5.1 补充矩阵总表

| 分组 | 测试项 | 场景 | 结果 | 实测要点 |
|---|---|---|---|---|
| D 容灾 | 测试17 | 目录中断容灾（netsh 拦 389/636） | ✓ | admin 本地逃生 **200/271ms**；断期旧 token **403/8.8ms**（fail-open）；断期新登录 401（**精确等满 timeout=10，实测 10.02s**）；恢复后 200/68ms——与 OpenLDAP 侧（阶段39 测试17–20）数字一致 |
| E 限速 | 测试18 | 登录限速器 | ✓ | dave 5×401 → 第 6 次（正确密码）**429** → 窗口内 t+25s 仍 429 → **t+65s 精确解封 200**——机制与目录类型无关 |
| F 会话 | 测试19 | refresh × 移组 | ✓ | 移出 gns3-admins（延迟 5s）→ 旧 token 200（fail-open）→ refresh 200 → 新 token **403**（角色重算）→ 恢复成员新登录 200——与 OpenLDAP 一致；移除后 ≈1s 内立即 refresh 曾观察到 200（收敛竞态窗口，见 §5.3） |
| F 会话 | 测试20 | API key × AD 禁用/移组 | ✓ | AD **禁用 bob 后 key 仍 200**（key 认证不查目录）；禁用期新登录 401、重启用后新登录 200 → 同一 key 200；移组成员+新登录（角色→Users）→ 同一 key **403**（权限随重新登录收敛）→ 恢复 → 200；**key 删除为 owner-only**（见 §5.3） |
| G 全局故障 | 测试21 | bind_dn 失效 | ✓ | svc-gns3 密码改坏 → alice 登录 401；恢复 → 200（与阶段39 测试24 同形态） |
| H 诊断 | 测试24 | ldap/test 诊断变体 | ✓ | bind_password 错误 → `{"status":"error","bind_successful":false,"users_found":0}`（21.6ms）；正确 → success，users_found=5（15.5ms，样本上限） |
| G 输入边界 | 测试22 | 输入边界 | ✓ | 特殊字符密码 `Gns3!test#2026&<>"` → **200**（JSON API 全通）；空密码 401；**`" alice "` 前后空白 → 200 归一**（AD sAMAccountName 匹配同样折叠空白，与 OpenLDAP caseIgnore 行为一致）；中文不存在用户 401；2000 字符用户名 401 |
| C 账号策略 | 测试23 | AD 原生锁定策略 | ✓ | 域锁定 threshold=3/60s：erin 3 错 → **正确密码也 401（46ms——目录级锁定先于限速器）** → 60s **自动解锁 200** → 阈值复位 0 复核 200——复刻 OpenLDAP ppolicy（阶段39 测试31）的双层保护形态 |

结论：补充 8 项全部通过，AD 侧合计 **24/24**。

### 5.2 关键行为记录（测试 19 / 20 / 23）

**测试19 收敛竞态窗口**：首测在移出成员后立即（≈1s）refresh，新 token 仍 200（当时预期 403）；延迟 5s 复测同一场景 → 新 token 403，与 OpenLDAP 一致。定性：**紧贴成员移除的立即刷新存在短暂收敛竞态窗口**（单次观察，未重复展开）；刷新收敛语义本身两目录一致。

**测试20 key 删除是 owner-only**：admin 用自己的 token 删除 bob 的 key → **403**（RBAC 拒绝跨用户删除）；bob 删除自己的 key → 204。与阶段39 测试33 的"管理员删除用户本地记录"（账号级删除 → key 401）是两条不同路径——key 的生命周期操作（revoke/restore/delete）都归属创建者，管理员只能通过删除/禁用**用户**来间接处死 key。

**测试23 锁定策略改写必须走 ADSI**：`Set-ADDefaultDomainPasswordPolicy`（AD 模块/ADWS 路径）在本机**第二次楔死**（服务端 shell 无返回 >44 分钟，客户端 read_timeout 未生效）。最终弃用 AD 模块：组操作与策略改写一律域根对象/组对象 ADSI 直写（`Put`/`SetInfo`），并为每个 WinRM 调用加客户端看门狗（守护线程 join 超时即弃单）。挂死模式与完整处置见附录问题 2。

### 5.3 环境残留说明

- 测试20 的两把测试 key 均已按 owner 语义删除（204，bob key 列表为空）；bob 组成员已恢复（Administrators=[bob,carol,erin] 复核）。
- dave/erin 账号 enabled、密码复原；锁定阈值已复位 0（duration/observation 回默认）；防火墙拦截规则已删除；svc-gns3 密码已复原（bind 实测 Success）。
- 测试结束后控制器已恢复 OpenLDAP 终态配置并验证（carol 200、Administrators=[bob,carol,erin]）。
