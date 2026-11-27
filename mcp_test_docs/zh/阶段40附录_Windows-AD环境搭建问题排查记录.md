# Windows AD 环境搭建问题排查记录（阶段 40 附录）

| 项 | 内容 |
|---|---|
| 记录日期 | 2026-11-27 |
| 环境 | GNS3-AD：Windows Server 2022 Standard **Core**（10.0.20348），192.168.101.32，单 DC 域 `ad.example.org`；管理通道 WinRM 5985 + pywinrm（NTLM） |
| 性质 | **环境搭建问题**，与 gns3-server / PR #3103 无关。记录现象、排查路径、根因与修复，供复现者参考 |
| 关联 | 主报告：`阶段40_PR3103-LDAP认证Windows-AD联测报告.md`；脚本：`labs/pr3103-ad-test-scripts/`（按执行顺序固化，含诊断脚本） |

---

## 问题 1：AD 对 StartTLS 返回 LDAP 52（unavailable）——自签证书未被 LSASS 采纳

**这是本轮耗时最长的坑**，集中了三轮排查。

### 现象

- 证书（自签，SAN/EKU/私钥齐全）已进入 `LocalMachine\My`，636/389 端口监听正常；
- GNS3 `ldap/test` 秒回失败：`{"status":"error","bind_successful":false,...,"message":"Failed to bind to LDAP server: unavailable","latency_ms":2.69}`，全部登录 401；
- 手工裸 ldap3 连 `CERT_REQUIRED` 与 `CERT_NONE` **两种校验态都失败**：`LDAPStartTLSError: startTLS failed - unavailable`——说明不是证书校验问题，是握手前就被服务端拒绝。

### 排查路径（逐步收窄）

| 步骤 | 命令 | 结果 | 结论 |
|---|---|---|---|
| ① VM21 网络 | `getent hosts ad.example.org`；`bash -c 'cat < /dev/null > /dev/tcp/ad.example.org/389'` | 解析 ✓、TCP ✓ | 排除解析/路由/防火墙 |
| ② 裸 ldap3 两态 | VM21 上以 gns3server 同 venv 复现（`ldap3.Tls(validate=...)`） | CERT_REQUIRED、CERT_NONE 均 `startTLS failed - unavailable` | 排除证书校验层 |
| ③ openssl 直探 | `openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief` | **`STARTTLS failed, LDAP Result Code: 52`** | 铁证：服务端对 StartTLS 扩展请求直接回 52（unavailable） |
| ④ Schannel 事件 | `Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Schannel'}` | **事件 36886 每 10 秒一条**（“安全包中无可用凭据”，时间与探测完全对齐） | LSASS 认为没有可用的服务器证书 |
| ⑤ 证书扩展核对 | 按 OID 原值枚举（见问题 4 的本地化坑） | SAN=3×dNSName、EKU=1.3.6.1.5.5.7.3.1、HasPrivateKey=True | 证书本身无缺陷 |

### 根因

**自签证书只进了 `LocalMachine\My`，没有受信任的根链。** LSASS 为服务器认证挑选证书时要求证书链能构建到受信任根；自签证书若不同时位于受信任存储中，链构建失败 → 不被选为服务器凭据（事件 36886）→ LDAP 服务对 StartTLS/LDAPS 握手回 52（unavailable）。

### 修复（两步缺一不可）

```powershell
# ① 自信任：把证书同时导入受信任根存储
Import-Certificate -FilePath 'C:\Windows\Temp\ad-lab-root.cer' -CertStoreLocation 'Cert:\LocalMachine\Root'

# ② 重启 DC：LSASS 不动态重扫证书库
Restart-Computer -Force
```

### 修复后验证

- `openssl s_client -starttls ldap` → `CONNECTION ESTABLISHED`、`Protocol version: TLSv1.3`、`depth=0 CN=ad.example.org`；
- LDAPS 636 同样 TLSv1.3；
- GNS3 矩阵（ldap/test → 16 项登录/映射/TLS）一次全过（主报告 §2）。

### 经验要点

1. GNS3 侧报 `Failed to bind: unavailable` + 毫秒级返回，且 CERT_NONE 仍失败 → 直接怀疑服务端 TLS 未就绪，用 `openssl s_client -starttls ldap` 一锤定音（Result Code 52）。
2. AD 上自签 LDAPS 证书配方 = **My（含私钥）+ Root（自信任）+ 重启**，三要素缺一不可；网上常见“只进 My 即可”的说法在本环境不成立。
3. 诊断证书扩展时用 **OID 原值**（2.5.29.17/2.5.29.37），不要匹配 FriendlyName（见问题 4）。

---

## 问题 2：DC 重启后 AD PowerShell 模块调用无限悬挂

### 现象

- `Install-ADDSForest` 完成重启后约 1 分钟，WinRM 即恢复可连（轻量命令秒回，服务 NTDS/kdc/DNS/ADWS 全 Running）；
- 但随后的验证脚本（`Get-ADDomain` → `Set-ADDefaultDomainPasswordPolicy`）**悬挂 27 分钟无返回**；
- 后续新开的探查调用也极慢/悬挂（>120 s），形成“越探越挂”的观感。

### 排查

- `Get-Service` 轻量查询秒回 → WinRM/PowerShell 本体正常；
- 服务器端清点 powershell 进程，发现**重启后立刻发起的那次调用残留的僵尸 shell**（PID 1692，10:41:26 启动）——客户端超时被掐后，服务端命令仍在无限运行。

### 根因

DC 刚重启、**ADWS 尚未就绪时**发起的 AD 模块调用（`Get-ADDomain` 等）会无限等待，永不超时；该悬挂会话在服务端常驻，并拖累后续调用。

### 对策

1. **服务器端看门狗**包住任何 AD 模块调用（超时可控，永不挂死连接）：

```powershell
$job = Start-Job { Import-Module ActiveDirectory; (Get-ADDomain).DNSRoot }
if (Wait-Job $job -Timeout 120) { Receive-Job $job } else { "still hangs"; Stop-Job $job }
```

2. **清理僵尸 shell**（排除当前会话）：

```powershell
Get-Process powershell | Where-Object {
  $_.Id -ne $PID -and $_.StartTime -and ((Get-Date) - $_.StartTime).TotalMinutes -gt 15
} | Stop-Process -Force
```

3. 流程上：重启后先等 NTDS/kdc/ADWS 稳定（本环境实测约 2–3 分钟），再用看门狗探测，通过后才放开正常调用。

本环境看门狗实测：清理僵尸后 `Get-ADDomain` 立即返回 `ad.example.org`。

> **复发记录（同日补充测试阶段）**：`Set-ADDefaultDomainPasswordPolicy` 再次楔死——服务端 shell 无返回 >44 分钟，且 pywinrm 客户端 `read_timeout` 在本机未生效（调用无限阻塞）。最终处置：**AD PowerShell 模块全部弃用**——组操作与策略改写一律 ADSI 直写（域根/组对象 `Put`+`SetInfo`，本机 LDAP 路径全天零挂死），并为每个 WinRM 调用加**客户端看门狗**（守护线程 join 超时即弃单，见 `labs/pr3103-ad-test-scripts/16_ad_extra_fix.py`）。经验：在这类低配单核 DC 上，能走 ADSI 的就不要走 AD 模块。

---

## 问题 3：默认密码策略拒绝测试口令

### 现象/预判

AD 域默认密码策略为**复杂度开启 + 最短 7 位**，测试口令 `gns3test`（纯小写）必然被拒；`svcldap123` 亦不满足。为保持与 OpenLDAP 侧同口令可比，建树前先放宽策略。

### 处理

两种等价方式，**推荐 ADSI 直写**（不依赖 ADWS，规避问题 2 的悬挂面）：

```powershell
# 方式 A：ADSI 直写域根对象（本轮采用）
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
$de.Put('pwdProperties', 0)     # 关闭复杂度
$de.Put('minPwdLength', 1)
$de.SetInfo()

# 方式 B：AD 模块（依赖 ADWS，功能等价）
Set-ADDefaultDomainPasswordPolicy -ComplexityEnabled:$false -MinPasswordLength 1
```

回读核对：`pwdProperties=0`、`minPwdLength=1`、`LockoutThreshold=0`（默认不锁定，负例测试不受影响）。

> 仅限实验室环境；生产域禁止关闭复杂度。

---

## 问题 4：管理面与环境杂项

| 项 | 现象 | 说明/处理 |
|---|---|---|
| Server Core 无 SSH | 22 端口未安装/未开启 | 管理通道 = **WinRM 5985**（Server Core 默认启用，NTLM）。如需 SSH 可经 WinRM 装 `OpenSSH.Server` capability，本轮未装 |
| ping 不通 | ICMP 回显 100% 丢 | Windows 防火墙默认禁回显，**不代表失联**；以端口探测为准 |
| pywinrm 安装 | 系统 python PEP 668 拦 `--user` | 装入系统 python（本轮由用户完成）；脚本统一 `python3 -I` 执行 |
| PowerShell 慢 | 功能安装 3.5 min、建林 4.5 min、部分调用数十秒 | 1 vCPU VM 上正常量级；长任务用后台脚本 + 日志，勿在前台裸等 |
| 中文系统的 FriendlyName | 证书扩展按英文名匹配（如 `Subject Alternative Name`）全部落空，报 null | .NET 的 `Oid.FriendlyName` 随系统语言本地化；**一律改用 `Oid.Value`（OID 原串）匹配** |
| ldap/test 报文语义 | `Failed to bind to LDAP server: unavailable` | `unavailable` 是 ldap3 结果描述经控制器转述（对应 LDAP 52），不代表“网络不可达”——本轮实测网络层全通 |

---

## 问题 5：测试脚本口令笔误（测试侧，非环境）

矩阵脚本把 svc-gns3 的登录口令误写成 `gns3test`（实际为 `svcldap123`），首轮矩阵 svc-gns3 登录 401。修正后 200。已在主报告 §2 注明，记录于此防止后续误读为产品行为。
