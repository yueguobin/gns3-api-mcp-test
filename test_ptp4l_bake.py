#!/usr/bin/env python3
"""test_ptp4l_bake.py — 实测 gns3-vm 镜像烘焙的 ptp4l 安装/配置（config/install.sh 的 PTP 段）。

在测试床一台 VM 上完整走一遍（幂等、可反复跑，端态=菜单切到 PTP 的收敛态）:
  1. 快照现状（ptp4l-mgmt / chrony 状态、单元 ExecStart、gmIdentity）
  2. 上传 config/ 的 5 个 PTP 文件，只执行新 install.sh 里的 PTP 段
     （等价于镜像构建/升级路径；若服务本来 active → 触发条件重启分支）
  3. 校验落盘: wrapper / unit / defaults / apparmor local / wrapper 探测网卡
  4. 模拟 console 菜单 "Time sync" 的双向切换:
       → NTP: disable ptp4l-mgmt, enable chrony
       → PTP: disable chrony+timesyncd, enable ptp4l-mgmt（等待 25s 收敛）
  5. pmc 收敛检查（portState / gmIdentity 与切换前一致 / offset）

用法:
  GNS3VM_PASSWORD='xxx' ./test_ptp4l_bake.py [-H 192.168.101.21]
"""

import argparse
import getpass
import os
import sys
import time

from multi_compute_deploy import ssh_connect, ssh_exec

REPO_CONFIG = os.path.expanduser("~/myCode/GNS3/gns3-vm/config")
FILES = ["ptp4l-mgmt.conf", "ptp4l-mgmt-defaults", "ptp4l-mgmt",
         "ptp4l-mgmt.service", "ptp4l-apparmor-local"]

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def ptp_section():
    """从新 install.sh 里切出 PTP 段（含上方 banner，止于 Avahi 注释行）。"""
    lines = open(os.path.join(REPO_CONFIG, "install.sh"), encoding="utf-8").read().splitlines()
    i = next(n for n, l in enumerate(lines) if l.strip() == "## PTP support ##")
    j = next(n for n, l in enumerate(lines) if n > i and l.startswith("# Install Avahi daemon"))
    return "\n".join(lines[i - 1:j])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-H", "--host", default="192.168.101.21")
    ap.add_argument("-u", "--user", default="gns3")
    ap.add_argument("-p", "--password", help="或环境变量 GNS3VM_PASSWORD")
    ap.add_argument("--port", type=int, default=22)
    args = ap.parse_args()
    password = args.password or os.environ.get("GNS3VM_PASSWORD") or getpass.getpass("密码: ")
    pw = password.replace("'", "'\"'\"'")  # 用于远端单引号上下文

    client = ssh_connect(args.host, args.user, password, args.port)

    def sh(cmd, deadline=120):
        _, out, _ = ssh_exec(client, cmd, deadline)
        return out.strip()

    def sudo(cmd, deadline=300):
        """单条 root 命令（cmd 内避免单引号）。"""
        return sh(f"printf '%s\\n' '{pw}' | sudo -S -p '' {cmd}", deadline)

    def pmc(key, ds):
        return sudo(f"pmc -u -b 0 'GET {ds}' 2>/dev/null | awk '/{key}/ {{print $2; exit}}'")

    try:
        print(f"[0] 快照现状 @ {args.host}")
        pre_active = sh("systemctl is-active ptp4l-mgmt 2>/dev/null || true")
        pre_exec = sh("systemctl cat ptp4l-mgmt 2>/dev/null | grep '^ExecStart=' || true")
        pre_gm = pmc("gmIdentity", "TIME_STATUS_NP")
        print(f"  ptp4l-mgmt={pre_active or 'inactive'}  {pre_exec}")
        print(f"  chrony={sh('systemctl is-active chrony 2>/dev/null || true') or 'inactive'}  gm={pre_gm or '?'}")

        print("[1] 上传 5 个 PTP 文件并执行 install.sh 的 PTP 段")
        sh("rm -rf /tmp/config_bake && mkdir -p /tmp/config_bake")
        sftp = client.open_sftp()
        for f in FILES:
            sftp.put(os.path.join(REPO_CONFIG, f), f"/tmp/config_bake/{f}")
        with sftp.file("/tmp/config_bake/ptp_section.sh", "w") as fh:
            fh.write(ptp_section())
        sftp.close()
        out = sudo("bash -c 'cd /tmp/config_bake && bash ptp_section.sh'", 600)
        print("  " + (out.splitlines()[-1] if out.strip() else "(无输出)")[:120])

        print("[2] 校验落盘结果")
        check("wrapper 可执行", sh("test -x /usr/local/bin/ptp4l-mgmt && echo y") == "y")
        exec_line = sh("systemctl cat ptp4l-mgmt | grep '^ExecStart='")
        check("unit ExecStart 指向 wrapper", exec_line == "ExecStart=/usr/local/bin/ptp4l-mgmt", exec_line)
        check("/etc/default/ptp4l-mgmt 就位", "192.168.101." in sh("cat /etc/default/ptp4l-mgmt"))
        check("apparmor local 就位", "capability sys_time," in sudo("cat /etc/apparmor.d/local/usr.sbin.ptp4l"))
        check("conf 就位", "first_step_threshold" in sh("cat /etc/linuxptp/ptp4l-mgmt.conf"))
        iface = sudo("env PTP4L=/bin/true PTP4L_MGMT_WAIT=2 /usr/local/bin/ptp4l-mgmt 2>&1 | head -1")
        check("wrapper 能探测到管理网卡", "running ptp4l on" in iface, iface)
        if pre_active == "active":
            post_active = sh("systemctl is-active ptp4l-mgmt 2>/dev/null || true")
            check("升级路径: 活动服务被条件重启", post_active == "active", post_active)

        print("[3] 菜单切换 → NTP（等价 time_sync() 的命令）")
        sudo("systemctl disable --now ptp4l-mgmt")
        sudo("systemctl enable --now chrony")
        time.sleep(3)
        check("chrony 接管", sh("systemctl is-active chrony") == "active")
        check("ptp4l-mgmt 已停", sh("systemctl is-active ptp4l-mgmt 2>/dev/null || true") != "active")

        print("[4] 菜单切换 → PTP（等待 25s 收敛）")
        sudo("systemctl disable --now chrony systemd-timesyncd")
        sudo("timedatectl set-ntp false")
        sudo("systemctl enable --now ptp4l-mgmt")
        check("ptp4l-mgmt 拉起", sh("systemctl is-active ptp4l-mgmt") == "active")
        print("  等待 BMCA 收敛…")
        time.sleep(25)
        state = pmc("portState", "PORT_DATA_SET")
        gm = pmc("gmIdentity", "TIME_STATUS_NP")
        off = pmc("offsetFromMaster", "CURRENT_DATA_SET")
        check("portState 有效", state in ("MASTER", "SLAVE", "PASSIVE", "UNCALIBRATED"), state)
        check("gmIdentity 与切换前一致", bool(gm) and gm == pre_gm, f"{pre_gm} → {gm}")
        try:
            check("|offsetFromMaster| < 1ms", abs(float(off)) < 1e6, f"{off} ns")
        except (TypeError, ValueError):
            check("|offsetFromMaster| < 1ms", False, f"拿不到 offset: {off!r}")
        last = sh("journalctl -u ptp4l-mgmt -n 3 --no-pager 2>/dev/null | grep 'master offset' | tail -1")
        print(f"  journal: {last[:120]}")
    finally:
        client.close()

    fails = [n for n, ok in results if not ok]
    print("\n" + "=" * 60)
    print(f"结果: {len(results) - len(fails)}/{len(results)} PASS" + (f"，FAIL: {', '.join(fails)}" if fails else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
