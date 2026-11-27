#!/usr/bin/env python3
"""One-shot AD forest bootstrap on GNS3-AD: feature -> forest -> reboot -> poll -> verify.

Runs in background. Progress goes to /tmp/ad-scripts/ad_setup.log.
Success signal: WinRM back after reboot + Get-ADDomain works.
"""
import time
import sys

sys.path.insert(0, '/tmp/ad-scripts')
from ps import sess  # noqa: E402

LOG = '/tmp/ad-scripts/ad_setup.log'


def log(m):
    with open(LOG, 'a') as f:
        f.write(f'[{time.strftime("%H:%M:%S")}] {m}\n')


def run_ps(code, read_to, label):
    log(f'--- {label} start')
    s = sess(read_to)
    try:
        r = s.run_ps(code)
        out = r.std_out.decode('utf-8', 'replace')
        err = r.std_err.decode('utf-8', 'replace')
        log(f'--- {label} rc={r.status_code}')
        log(out[-5000:])
        if err.strip():
            log(f'--- {label} stderr(tail): {err[-1500:]}')
        return r.status_code
    except Exception as e:
        log(f'--- {label} EXC: {type(e).__name__}: {e}')
        return None


FEATURE = r'''
$ErrorActionPreference = 'Stop'
$nic = (Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object -First 1).Name
"DNS client on $nic already: $((Get-DnsClientServerAddress -InterfaceAlias $nic -AddressFamily IPv4).ServerAddresses -join ',')"
Install-WindowsFeature AD-Domain-Services -IncludeAllSubFeature -IncludeManagementTools | Out-String
"FEATURE_OK"
'''

FOREST = r'''
$ErrorActionPreference = 'Stop'
Import-Module ADDSDeployment
$sa = ConvertTo-SecureString 'Huawei@123' -AsPlainText -Force
$result = Install-ADDSForest -DomainName 'ad.example.org' -DomainMode WinThreshold -ForestMode WinThreshold -InstallDns -SafeModeAdministratorPassword $sa -NoRebootOnCompletion:$false -Force
$result | Out-String
"FOREST_INSTALL_OK"
'''

VERIFY = r'''
$ErrorActionPreference = 'Continue'
"== domain:"; (Get-ADDomain).DNSRoot; "mode: $((Get-ADDomain).DomainMode)"
"== forest mode: $((Get-ADForest).ForestMode)"
"== DC name: $((Get-ADDomainController -Discover).HostName)"
"== services:"
Get-Service NTDS,Netlogon,kdc,DNS | Format-Table Name,Status -AutoSize | Out-String
"== relax password policy (align with OpenLDAP lab passwords):"
Set-ADDefaultDomainPasswordPolicy -ComplexityEnabled:$false -MinPasswordLength 1
Get-ADDefaultDomainPasswordPolicy | Format-List ComplexityEnabled,MinPasswordLength,LockoutThreshold,MaxPasswordAge | Out-String
"== password policy OK"
'''


def main():
    rc = run_ps(FEATURE, 900, 'feature-install')
    if rc != 0:
        log('FEATURE INSTALL FAILED - abort')
        return 1

    rc = run_ps(FOREST, 900, 'forest-install')
    if rc == 0 and False:
        pass  # reboot starts; connection may drop either way

    log('polling for WinRM back after reboot...')
    up = False
    for i in range(48):  # 48 x 15s = 12 min ceiling
        time.sleep(15)
        try:
            s = sess(30)
            r = s.run_ps('"pong $env:COMPUTERNAME"')
            if r.status_code == 0:
                log(f'WinRM back after ~{(i + 1) * 15}s')
                up = True
                break
            log(f'poll {i}: rc={r.status_code}')
        except Exception as e:
            log(f'poll {i}: {type(e).__name__}')
    if not up:
        log('FATAL: WinRM never came back within 12 min')
        return 1

    time.sleep(45)  # let NTDS/kdc/DNS settle
    rc = run_ps(VERIFY, 300, 'post-reboot-verify')
    log('SETUP DONE' if rc == 0 else 'VERIFY HAD ISSUES - inspect log')
    return 0


sys.exit(main())
