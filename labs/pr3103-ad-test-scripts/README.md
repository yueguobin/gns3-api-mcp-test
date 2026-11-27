# PR #3103 Windows AD 侧联测脚本（2026-11-27）

GNS3-AD 节点（Windows Server 2022 Standard Core，192.168.101.32）建域 + 测试树 + LDAPS 证书 + GNS3 侧矩阵的全部脚本，**按实际执行顺序原样固化**（含走弯路的诊断脚本，过程与坑的完整叙述见 `mcp_test_docs/zh/阶段40附录_Windows-AD环境搭建问题排查记录.md`）。

## 连接前提

- 管理通道：WinRM 5985（Server Core 默认启用），NTLM 认证。
- `ps.py` 是所有 PowerShell 脚本的执行器：`python3 -I ps.py <script.ps1> [read_timeout_sec]`。pywinrm 需装在系统 python。
- GNS3 侧脚本（08/09）默认 BASE=`http://192.168.101.21`（VM21 controller，端口 80）。

## 执行顺序与作用

| # | 脚本 | 作用 | 结果 |
|---|---|---|---|
| 0 | `01_precheck.ps1` | 域状态/功能/磁盘/DNS 预检 | WORKGROUP、功能未装 |
| 1 | `04_ad_setup.py` | 装功能 → `Install-ADDSForest`（ad.example.org）→ 重启 → 轮询 → 验证。**注意：其 VERIFY 段的 `Set-ADDefaultDomainPasswordPolicy` 在本环境悬挂**，密码策略最终由 `05_diag.ps1` 的 ADSI 直写完成 | 域建成，功能级别 7 |
| 2 | `05_diag.ps1` | 僵尸 powershell 清理 + Get-ADDomain 服务器端看门狗测试 + **ADSI 直写密码策略**（pwdProperties=0, minPwdLength=1）+ 功能级别 LDAP 直读 | 全部通过 |
| 3 | `06_tree.ps1` | 建 OU=gns3{people,groups}、7 用户（gns3test；svc-gns3=svcldap123）、4 组及成员矩阵 | 成员矩阵精确 |
| 4 | `07_cert.ps1` | 自签证书（SAN=ad.example.org 等 3 个 dNSName，ServerAuth EKU）进 LocalMachine\My，导出 b64 | 证书入库 |
| 5 | `08_tls_setup.py` | 取证书 → VM21 装 CA（/usr/local/share/ca-certificates/ + update-ca-certificates）+ hosts 条目 | VM21 信任完成 |
| 6 | `10_reboot_wait.py` | 重启 DC（第一次，**不解决 52**——当时 Root 自信任还没做） | 重启但 StartTLS 仍 52 |
| 7 | `11_certdiag.ps1` | 证书扩展枚举（暴露 FriendlyName 本地化坑）+ Schannel 事件（36886 每 10s） | 定位证据 |
| 8 | `12_certfix.ps1` | OID 原值核对证书（SAN/EKU/私钥齐全）+ **导入 LocalMachine\Root 自信任** | 补上链信任 |
| 9 | `13_reboot_matrix.sh` | 再重启（LSASS 重扫）→ 轮询 StartTLS 变绿 → openssl 验 LDAPS → **执行 `09_ad_matrix.py` 全矩阵** | StartTLS TLSv1.3，矩阵 16 项全过 |

诊断支线（VM21 侧）：`vm21_diag.sh`（解析/TCP/裸 ldap3/报错出处定位）、`vm21_diag2.sh`（gns3server 日志 + CERT_REQUIRED/CERT_NONE 对照复现）。

## 关键提醒

1. **自签 LDAPS 证书必须同时导入 `LocalMachine\Root`，且之后必须重启 DC**——LSASS 不动态重扫证书库；缺任一步 AD 对 StartTLS 回 LDAP 52（unavailable）。
2. **DC 重启后不要立即调 AD 模块**（ADWS 未就绪会楔死服务端 shell）；先跑看门狗式验证。
3. `09_ad_matrix.py` 的 `finally` 块自动把控制器配置恢复为 OpenLDAP 终态并验证——**重跑安全**。
4. 凭据：域 administrator/Huawei@123（DSRM 同）；测试用户 gns3test；svc-gns3=svcldap123。
