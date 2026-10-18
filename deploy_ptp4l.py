#!/usr/bin/env python3
"""deploy_ptp4l.py — 给 GNS3VM（Ubuntu 系）批量部署 ptp4l：4 台之间自组 PTP 对时（软件时间戳）。

用法:
  ./deploy_ptp4l.py                                  # 全交互: 依次提示 用户名 / 主机 / 密码
  ./deploy_ptp4l.py -H "192.168.101.21-24" -u gns3 -p 'xxx'
  ./deploy_ptp4l.py --verify-only -p 'xxx'          # 只读收敛状态，可反复跑（同样可交互输入）

对每台 VM 做的事:
  1. 探测管理口（带 192.168.101.x 地址的接口）
  2. apt 安装 linuxptg（linuxptp，已装跳过；失败留 /tmp/ptp4l-apt.log）
  3. 停用抢时钟的服务: systemd-timesyncd / chrony / ntp（存在才动）+ timedatectl set-ntp false
  4. AppArmor 解封: disable --now apparmor + 卸载 linuxptp 的 ptp4l/phc2sys profile
     （Ubuntu 自带 profile 剥夺 CAP_SYS_TIME，ptp4l 拨钟 adjtimex 全部 EPERM）
  5. 写 /etc/linuxptp/ptp4l-mgmt.conf + systemd 单元 ptp4l-mgmt.service
  6. enable --now，等 25s 后 pmc 读 portState / offsetFromMaster / gmIdentity

4 台跑同一配置，BMCA 自动选主（同优先级比 clockIdentity）；从钟的 offsetFromMaster
即"相对主钟偏差"，全体 |offset| 的最大值就是两两钟差的上界。重复执行=覆盖重启，幂等。
"""

import argparse
import concurrent.futures
import getpass
import os
import shlex
import sys
import time

from multi_compute_deploy import parse_hosts, probe_tcp, ssh_connect, ssh_exec

DEFAULT_USER = "gns3"
DEFAULT_HOSTS = "192.168.101.21-24"
MGMT_NET = "192.168.101."

PTP4L_CONF = """\
# GNS3VM 管理网 PTP（virbr2，4 台互同步，BMCA 自动选主）
[global]
time_stamping        software
# 首次校正 >1ms 直接跳变对齐（4 台初始互差 ~12ms → 启动即对齐，不慢慢爬）
first_step_threshold 0.001
# 之后只有 >1s 的偏移才再跳变，微偏交给 PI 伺服 slew 微调
step_threshold       1.0
# （实测教训：logSyncInterval -2 + moving_median 滤波反而更差——4/s 把桥/vCPU
#   抖动噪声灌进默认 PI，rms ~100µs 还震荡；1/s 默认稳在 ±100µs 内，勿再加料）
# 每秒一行 master offset 进 journal（summary_interval >0 会变成 rms/max 统计行）
summary_interval     0
"""

INSTALL_REMOTE = r"""
set -u
PW=__PW__
step() { printf '###STEP:%s:%s\n' "$1" "$2"; }
info() { printf '###INFO:%s:%s\n' "$1" "$2"; }
s() { if [ -n "$SUDO" ]; then printf '%s\n' "$PW" | "$SUDO" -S -p '' "$@"; else "$@"; fi; }
SUDO=sudo
[ "$(id -un)" = root ] && SUDO=""

info date-before "$(date +%s.%N)"

# 1. 探测管理口
IFACE=$(ip -4 -o addr show | awk -v net="__MGMT__" '$4 ~ ("^" net) {print $2}' | head -1)
if [ -z "$IFACE" ]; then step detect FAIL; info reason "没有 __MGMT__x 地址"; exit 1; fi
step detect OK
info iface "$IFACE"

# 2. 安装 linuxptp
if command -v ptp4l >/dev/null 2>&1; then
  step apt OK
  info apt-reason "已安装，跳过"
else
  if s apt-get install -y linuxptp >/tmp/ptp4l-apt.log 2>&1; then
    step apt OK
  else
    s apt-get update >>/tmp/ptp4l-apt.log 2>&1 || true
    if s apt-get install -y linuxptp >>/tmp/ptp4l-apt.log 2>&1; then
      step apt OK
    else
      step apt FAIL
      info apt-log "$(tail -n 3 /tmp/ptp4l-apt.log | tr '\n' ' ')"
      exit 1
    fi
  fi
fi
PTP4L=$(command -v ptp4l)
info ptp4l-version "$($PTP4L -v 2>&1 | head -1)"

# 3. 停用抢时钟的服务（存在才动）
for svc in systemd-timesyncd chrony chronyd ntp; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1 && \
     systemctl cat "$svc" >/dev/null 2>&1; then
    s systemctl disable --now "$svc" >/dev/null 2>&1 && info timesync-off "$svc"
  fi
done
s timedatectl set-ntp false >/dev/null 2>&1 || true
step timesync OK

# 4. AppArmor 解封: Ubuntu 的 linuxptp profile 剥夺 CAP_SYS_TIME，ptp4l 调 adjtimex
#    全部 EPERM（且被 confinement 的 ptp4l 连 UDS 上 pmc 的请求都不应答）。
#    disable --now 只防开机加载；内核里已加载的必须显式 apparmor_parser -R 卸载。
s systemctl disable --now apparmor >/dev/null 2>&1
s mkdir -p /etc/apparmor.d/disable
for pf in usr.sbin.ptp4l usr.sbin.phc2sys; do
  if [ -f /etc/apparmor.d/$pf ]; then
    s ln -sf /etc/apparmor.d/$pf /etc/apparmor.d/disable/$pf
    s apparmor_parser -R /etc/apparmor.d/$pf >/dev/null 2>&1
    info apparmor-off "$pf"
  fi
done
step apparmor OK

# 5. 写配置 + systemd 单元
cat > /tmp/ptp4l-mgmt.conf <<'PTPEOF'
__CONF__
PTPEOF
s mkdir -p /etc/linuxptp
s install -m 0644 /tmp/ptp4l-mgmt.conf /etc/linuxptp/ptp4l-mgmt.conf

cat > /tmp/ptp4l-mgmt.service <<'UNITEOF'
[Unit]
Description=ptp4l (PTP) on __IFACE__ (GNS3VM management network)
After=network-online.target
Wants=network-online.target
Conflicts=systemd-timesyncd.service chrony.service chronyd.service ntp.service

[Service]
ExecStart=__PTP4L__ -f /etc/linuxptp/ptp4l-mgmt.conf -i __IFACE__ -m
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNITEOF
sed -i "s/__IFACE__/$IFACE/g; s#__PTP4L__#$PTP4L#g" /tmp/ptp4l-mgmt.service
s install -m 0644 /tmp/ptp4l-mgmt.service /etc/systemd/system/ptp4l-mgmt.service
step conf OK

# 6. 起服务
s systemctl daemon-reload
s systemctl enable ptp4l-mgmt >/dev/null 2>&1
s systemctl restart ptp4l-mgmt
sleep 25
ACT=$(systemctl is-active ptp4l-mgmt 2>/dev/null)
info service "${ACT:-unknown}"
info confine "$(s cat /proc/$(pgrep -x ptp4l | head -1)/attr/current 2>/dev/null)"
if [ "$ACT" = active ]; then
  step start OK
else
  step start FAIL
  info journal "$(s journalctl -u ptp4l-mgmt -n 8 --no-pager 2>/dev/null | tr '\n' ' ')"
fi

if [ "$ACT" = active ] && command -v pmc >/dev/null 2>&1; then
  info portstate "$(s pmc -u -b 0 'GET PORT_DATA_SET' 2>/dev/null | awk '/portState/ {print $2; exit}')"
  info offset "$(s pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | awk '/offsetFromMaster/ {print $2; exit}')"
  info delay "$(s pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | awk '/meanPathDelay/ {print $2; exit}')"
  info gm "$(s pmc -u -b 0 'GET TIME_STATUS_NP' 2>/dev/null | awk '/gmIdentity/ {print $2; exit}')"
fi
info done 1
"""

VERIFY_REMOTE = r"""
set -u
step() { printf '###STEP:%s:%s\n' "$1" "$2"; }
info() { printf '###INFO:%s:%s\n' "$1" "$2"; }
s() { if [ -n "$SUDO" ]; then printf '%s\n' "$PW" | "$SUDO" -S -p '' "$@"; else "$@"; fi; }
PW=__PW__
SUDO=sudo
[ "$(id -un)" = root ] && SUDO=""

info date "$(date +%s.%N)"
ACT=$(systemctl is-active ptp4l-mgmt 2>/dev/null)
info service "${ACT:-inactive}"
if [ "$ACT" != active ]; then
  info journal "$(s journalctl -u ptp4l-mgmt -n 8 --no-pager 2>/dev/null | tr '\n' ' ')"
  info done 1
  exit 0
fi
step check OK
if command -v pmc >/dev/null 2>&1; then
  info portstate "$(s pmc -u -b 0 'GET PORT_DATA_SET' 2>/dev/null | awk '/portState/ {print $2; exit}')"
  info offset "$(s pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | awk '/offsetFromMaster/ {print $2; exit}')"
  info delay "$(s pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | awk '/meanPathDelay/ {print $2; exit}')"
  info gm "$(s pmc -u -b 0 'GET TIME_STATUS_NP' 2>/dev/null | awk '/gmIdentity/ {print $2; exit}')"
  info stepsrem "$(s pmc -u -b 0 'GET CURRENT_DATA_SET' 2>/dev/null | awk '/stepsRemoved/ {print $2; exit}')"
fi
info lastline "$(s journalctl -u ptp4l-mgmt -n 6 --no-pager 2>/dev/null | grep 'master offset' | tail -1)"
info done 1
"""


def render(script, password):
    return (script
            .replace("__PW__", shlex.quote(password))
            .replace("__MGMT__", MGMT_NET)
            .replace("__CONF__", PTP4L_CONF.rstrip("\n")))


def run_host(host, args, password, script):
    r = {"host": host, "steps": {}, "info": {}, "error": None, "output": ""}
    try:
        client = ssh_connect(host, args.user, password, args.port)
    except Exception as e:
        r["error"] = f"连接失败: {type(e).__name__}"
        return r
    try:
        import base64
        b64 = base64.b64encode(script.encode()).decode()
        rc, out, err = ssh_exec(client, f"echo {b64} | base64 -d | bash")
        r["output"] = out + ("\n[stderr]\n" + err if err.strip() else "")
        for line in (out + "\n" + err).splitlines():
            if line.startswith("###STEP:"):
                _, name, st = line.split(":", 2)
                r["steps"][name] = st
            elif line.startswith("###INFO:"):
                _, k, v = line.split(":", 2)
                r["info"][k] = v
        if "done" not in r["info"]:
            r["error"] = r["error"] or f"脚本未跑完(rc={rc})"
    finally:
        client.close()
    return r


def snap_dates(hosts, args, password, tag):
    """4 台并行取 date +%s.%N，看两两互差（含 SSH 往返抖动，只作粗检）。"""
    def one(h):
        try:
            c = ssh_connect(h, args.user, password, args.port)
            try:
                _, out, _ = ssh_exec(c, "date +%s.%N", deadline=20)
                return h, float(out.strip())
            finally:
                c.close()
        except Exception:
            return h, None
    got = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(hosts)) as ex:
        for h, t in ex.map(one, hosts):
            got[h] = t
    vals = [t for t in got.values() if t]
    if len(vals) >= 2:
        spread = (max(vals) - min(vals)) * 1000
        print(f"[{tag}] 并行 date 快照: max−min = {spread:.1f} ms（含 SSH 抖动，仅粗检）")
    else:
        print(f"[{tag}] date 快照失败: {got}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-H", "--hosts", help="主机: IP/域名/末段区间/CIDR，逗号或空格分隔（不给则交互输入）")
    ap.add_argument("-u", "--user", help=f"VM 用户名（默认 {DEFAULT_USER}）")
    ap.add_argument("-p", "--password", help="密码（也支持环境变量 GNS3VM_PASSWORD；不给则交互输入）")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--verify-only", action="store_true", help="只读收敛状态，不改任何配置")
    ap.add_argument("--parallel", type=int, default=8)
    args = ap.parse_args()

    args.user = args.user or input(f"VM 用户名 [{DEFAULT_USER}]: ").strip() or DEFAULT_USER
    if not args.hosts:
        args.hosts = input(f"主机（IP/域名/{DEFAULT_HOSTS}/CIDR，逗号或空格分隔）: ")
    password = args.password or os.environ.get("GNS3VM_PASSWORD") or getpass.getpass("密码: ")

    hosts = parse_hosts(args.hosts)
    reachable, unreachable = probe_tcp(hosts, args.port)
    if unreachable:
        print(f"不可达(剔除): {', '.join(unreachable)}")
    if not reachable:
        print("没有可达主机。", file=sys.stderr)
        sys.exit(1)
    print(f"目标 {len(reachable)} 台: {', '.join(reachable)}")

    script = render(VERIFY_REMOTE if args.verify_only else INSTALL_REMOTE, password)
    mode = "verify-only" if args.verify_only else "install+start+初检"
    print(f"\n[{mode}]（{len(reachable)} 台并行）")
    snap_dates(reachable, args, password, "前" if not args.verify_only else "快照")
    t0 = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(run_host, h, args, password, script): h for h in reachable}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            results.append(r)
            if r["error"] and not r["steps"]:
                print(f"  {r['host']}: {r['error']}")
            else:
                print(f"  {r['host']}: " + " ".join(f"{k}={v}" for k, v in sorted(r["steps"].items())))
    print(f"（远端脚本耗时 {time.time() - t0:.0f}s，含 25s 收敛等待）" if not args.verify_only else "")

    print("\n" + "=" * 100)
    print(f"{'主机':<18}{'服务':<10}{'portState':<12}{'offset(ns)':<14}{'delay(ns)':<12}{'gmIdentity'}")
    print("-" * 100)
    all_ok = not unreachable
    gms, max_off = set(), 0.0
    for r in sorted(results, key=lambda x: hosts.index(x["host"])):
        h, inf = r["host"], r["info"]
        if r["error"] and not r["steps"]:
            print(f"{h:<18}{r['error']}")
            all_ok = False
            continue
        for k in ("iface", "apt-reason", "apt-log", "ptp4l-version", "timesync-off", "reason", "journal"):
            if k in inf:
                print(f"{h:<18}· {k}: {inf[k][:150]}")
        if "date-before" in inf:
            print(f"{h:<18}· date-before: {inf['date-before']}")
        state = inf.get("portstate", "-")
        off = inf.get("offset", "-")
        try:
            max_off = max(max_off, abs(float(off)))
        except ValueError:
            # 主钟自身即基准，offset 为空是正常的；其他情况才算拿不到
            if state != "MASTER":
                all_ok = False
        if "gm" in inf and inf["gm"]:
            gms.add(inf["gm"])
        print(f"{h:<18}{inf.get('service', '?'):<10}{state:<12}{off:<14}{inf.get('delay', '-'):<12}{inf.get('gm', '-')}")
        if r["error"]:
            print(f"{h:<18}! {r['error']}")
            all_ok = False
        if inf.get("service") != "active":
            all_ok = False
        if "lastline" in inf:
            print(f"{h:<18}· {inf['lastline'][:150]}")

    print("-" * 100)
    if gms:
        print(f"gmIdentity 一致性: {'OK（全部锁到同一主钟 ' + list(gms)[0] + '）' if len(gms) == 1 else '不一致: ' + ', '.join(sorted(gms))}")
        all_ok = all_ok and len(gms) == 1
    if max_off:
        print(f"两两钟差上界（max|offsetFromMaster|）≈ {max_off:.0f} ns = {max_off/1000:.1f} µs")
    logdir = "/tmp/auto_gw/logs-ptp4l"
    os.makedirs(logdir, exist_ok=True)
    for r in results:
        with open(os.path.join(logdir, f"{r['host']}.log"), "w", encoding="utf-8") as f:
            f.write(r["output"])
    print(f"明细日志: {logdir}/")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
