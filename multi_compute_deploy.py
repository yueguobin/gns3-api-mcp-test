#!/usr/bin/env python3
"""multi_compute_deploy.py — 一条命令把 gns3-server(wheel) + ubridge(源码编译) 部署到 GNS3 VM 并重启服务。

用法:
  ./multi_compute_deploy.py                                  # 全交互: 依次提示 用户名 / 密码 / 主机
  ./multi_compute_deploy.py -H "192.168.101.21"              # 只提示输密码
  ./multi_compute_deploy.py -H "192.168.101.20-25,vm1.corp" -u gns3 -p 'xxx'
  ./multi_compute_deploy.py -H ... --ubridge-branch feature/capture-multi   # 指定分支(默认用仓库当前状态)
  ./multi_compute_deploy.py -H ... --no-ai-features   # 只装 server 本体，不装 AI/MCP 依赖
  ./multi_compute_deploy.py -H ... --pip-index https://pypi.org/simple   # ai 依赖直连官方源(默认阿里源)

固定流程（与你手工步骤一一对应）:
  1. 进入 gns3-server 仓库 → pip wheel → /tmp/auto_gw/
  2. 上传 wheel + ai/mcp requirements 到各 VM → 进 venv 执行
     pip install --force-reinstall --no-deps（server 本体）
     pip install -r ai-requirements.txt -r mcp-requirements.txt（ai-features 依赖）
  3. 进入 ubridge 仓库 → 打包源码 → /tmp/ubridge.tar
  4. 上传到各 VM → 解压 → make / make install → which 验证
  5. 重启 gns3 服务并确认 active
"""

import argparse
import concurrent.futures
import getpass
import ipaddress
import logging
import os
import re
import shlex
import socket
import subprocess
import sys
import time

try:
    import paramiko
except ImportError:
    print("缺依赖: pip install paramiko", file=sys.stderr)
    sys.exit(2)
logging.getLogger("paramiko").setLevel(logging.CRITICAL)

DEFAULT_USER = "gns3"
DEFAULT_SERVER_REPO = os.path.expanduser("~/myCode/GNS3/gns3-server")
DEFAULT_UBRIDGE_REPO = os.path.expanduser("~/myCode/GNS3/ubridge")
DEFAULT_VENV = "/home/gns3/.venv/gns3server-venv"
GW_DIR = "/tmp/auto_gw"
UB_TAR = "/tmp/ubridge.tar"
# pyproject.toml: ai-features = {file = ['ai-requirements.txt', 'mcp-requirements.txt']}
AI_REQ_FILES = ("ai-requirements.txt", "mcp-requirements.txt")
# VM 直连 pypi.org 国际链路仅几 KB/s 且中途停滞，langgraph 224KB 索引页拉不完即 "from versions: none"
# （2026-11-07 实测：同 VM 到国内镜像 0.4s 全量拉完，宿主直连官方源正常）；传 '' 可退回官方源
DEFAULT_PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple/"

REMOTE_SCRIPT = r"""
set -u
PW=__PW__
VENV_DEF=__VENV__
WHEEL=__WHEEL__
DO_SERVER=__DO_SERVER__
DO_AI=__DO_AI__
DO_UBRIDGE=__DO_UBRIDGE__
DO_RESTART=__DO_RESTART__
PINDEX=__PINDEX__
SUDO=sudo
[ "$(id -un)" = root ] && SUDO=""
s() { if [ -n "$SUDO" ]; then printf '%s\n' "$PW" | "$SUDO" -S -p '' "$@"; else "$@"; fi; }
step() { printf '###STEP:%s:%s\n' "$1" "$2"; }
info() { printf '###INFO:%s:%s\n' "$1" "$2"; }

VENV="$VENV_DEF"
if [ ! -x "$VENV/bin/pip" ]; then
  BIN=$(systemctl cat gns3 2>/dev/null | sed -n 's/^[[:space:]]*ExecStart=\([^[:space:]]*\).*/\1/p' | head -1)
  case "$BIN" in */bin/gns3server) VENV=${BIN%/bin/gns3server} ;; esac
fi
info venv "$VENV"

SERVER_OK=0
if [ "$DO_SERVER" = 1 ]; then
  if [ ! -x "$VENV/bin/pip" ]; then
    step server FAIL
    info server-reason "pip 不存在: $VENV/bin/pip"
  elif "$VENV/bin/pip" install --force-reinstall --no-deps "/tmp/$WHEEL" >/tmp/deploy-pip.log 2>&1; then
    VER=$("$VENV/bin/pip" show gns3-server 2>/dev/null | sed -n 's/^Version:[[:space:]]*//p')
    info server-version "${VER:-unknown}"
    SERVER_OK=1
    step server OK
  else
    step server FAIL
    info server-log "$(tail -n 5 /tmp/deploy-pip.log 2>/dev/null | tr '\n' ' ')"
  fi
fi

if [ "$SERVER_OK" = 1 ] && [ "$DO_AI" = 1 ]; then
  if [ ! -f /tmp/ai-requirements.txt ] || [ ! -f /tmp/mcp-requirements.txt ]; then
    step ai FAIL
    info ai-log "requirements 未上传: /tmp/ai-requirements.txt /tmp/mcp-requirements.txt"
  else
    AI_IDX=()
    [ -n "$PINDEX" ] && AI_IDX+=(-i "$PINDEX")
    info ai-index "${PINDEX:-官方源}"
    if "$VENV/bin/pip" install -r /tmp/ai-requirements.txt -r /tmp/mcp-requirements.txt "${AI_IDX[@]}" >/tmp/deploy-pip-ai.log 2>&1; then
      if MCVER=$("$VENV/bin/python" -c 'import mcp, netmiko; print(getattr(mcp, "__version__", "unknown"))' 2>/dev/null); then
        info ai-mcp "${MCVER:-unknown}"
        step ai OK
      else
        info ai-mcp "import mcp/netmiko failed"
        step ai FAIL
      fi
    else
      step ai FAIL
      info ai-log "$(tail -n 5 /tmp/deploy-pip-ai.log 2>/dev/null | tr '\n' ' ')"
    fi
  fi
fi

UB=1
if [ "$DO_UBRIDGE" = 1 ]; then
  if ! s apt-get install -y build-essential libpcap-dev >/tmp/deploy-apt.log 2>&1; then
    s apt-get update >>/tmp/deploy-apt.log 2>&1 || true
    s apt-get install -y build-essential libpcap-dev >>/tmp/deploy-apt.log 2>&1 \
      || { step apt FAIL; info apt-log "$(tail -n 3 /tmp/deploy-apt.log | tr '\n' ' ')"; UB=0; }
  fi
  [ "$UB" = 1 ] && step apt OK

  if [ "$UB" = 1 ]; then
    rm -rf /tmp/ubridge-src && mkdir -p /tmp/ubridge-src
    if tar xzf /tmp/ubridge.tar -C /tmp/ubridge-src && make -C /tmp/ubridge-src -j"$(nproc)" >/tmp/deploy-make.log 2>&1; then
      step build OK
    else
      step build FAIL
      info make-log "$(tail -n 5 /tmp/deploy-make.log 2>/dev/null | tr '\n' ' ')"
      UB=0
    fi
  fi
  if [ "$UB" = 1 ]; then
    if s make -C /tmp/ubridge-src install >/tmp/deploy-inst.log 2>&1; then
      step install OK
    else
      step install FAIL
      info inst-log "$(tail -n 5 /tmp/deploy-inst.log 2>/dev/null | tr '\n' ' ')"
      UB=0
    fi
  fi
  if [ "$UB" = 1 ]; then
    A=$(md5sum /tmp/ubridge-src/ubridge 2>/dev/null | awk '{print $1}')
    B=$(md5sum /usr/local/bin/ubridge 2>/dev/null | awk '{print $1}')
    info which "$(type -ap ubridge 2>/dev/null | tr '\n' ' ')"
    info md5 "built=$A installed=$B"
    if [ -n "$A" ] && [ "$A" = "$B" ]; then step verify OK; else step verify FAIL; fi
  fi
fi

if [ "$DO_RESTART" = 1 ]; then
  if s systemctl restart gns3 >/tmp/deploy-restart.log 2>&1; then
    for i in 1 2 3 4; do
      sleep 3
      ST=$(s systemctl is-active gns3 2>/dev/null || true)
      [ "$ST" = active ] && break
    done
    info service "${ST:-unknown}"
    if [ "${ST:-}" = active ]; then
      step restart OK
    else
      step restart FAIL
      s journalctl -u gns3 -n 30 --no-pager >/tmp/deploy-journal.log 2>&1 || true
      info journal "$(tail -n 5 /tmp/deploy-journal.log 2>/dev/null | tr '\n' ' ')"
    fi
  else
    step restart FAIL
    info restart-log "$(tail -n 5 /tmp/deploy-restart.log 2>/dev/null | tr '\n' ' ')"
  fi
fi
info done 1
"""


# ---------------------------------------------------------------- 基础件

def parse_hosts(spec):
    """单 IP / 域名 / 192.168.101.20-30（末段区间）/ CIDR，逗号或空格分隔。"""
    hosts = []
    for token in re.split(r"[,\s]+", spec.strip()):
        if not token:
            continue
        m = re.match(r"^(\d+\.\d+\.\d+\.)(\d+)-(\d+)$", token)
        try:
            if m:
                prefix, lo, hi = m.group(1), int(m.group(2)), int(m.group(3))
                if not (0 <= lo <= 255 and 0 <= hi <= 255):
                    raise ValueError(f"末段越界: {token}")
                for i in range(lo, hi + 1):
                    hosts.append(str(ipaddress.ip_address(f"{prefix}{i}")))
            elif "/" in token:
                hosts += [str(h) for h in ipaddress.ip_network(token, strict=False).hosts()]
            else:
                ipaddress.ip_address(token)
                hosts.append(token)
        except ValueError:
            if re.match(r"^[A-Za-z0-9._-]+$", token):
                hosts.append(token)
            else:
                raise SystemExit(f"无法解析主机: {token}")
    return list(dict.fromkeys(hosts))


def probe_tcp(hosts, port=22, timeout=2.0):
    def one(h):
        try:
            with socket.create_connection((h, port), timeout=timeout):
                return h, True
        except OSError:
            return h, False
    reachable, unreachable = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        for h, ok in ex.map(one, hosts):
            (reachable if ok else unreachable).append(h)
    return reachable, unreachable


def run(cmd, cwd=None):
    print("+ " + cmd + (f"   (cwd={cwd})" if cwd else ""))
    p = subprocess.run(cmd, shell=True, cwd=cwd, check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    if p.returncode != 0:
        print(p.stdout.rstrip(), file=sys.stderr)
        raise SystemExit(f"本地命令失败 rc={p.returncode}: {cmd}")
    return p.stdout or ""


def ssh_connect(host, user, password, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password,
                   look_for_keys=True, allow_agent=True,
                   timeout=8, banner_timeout=20, auth_timeout=20)
    return client


def ssh_exec(client, cmd, deadline=900):
    chan = client.get_transport().open_session(timeout=15)
    chan.settimeout(5.0)
    chan.exec_command(cmd)
    out, err = b"", b""
    end = time.time() + deadline
    while True:
        got = False
        while chan.recv_ready():
            out += chan.recv(65536); got = True
        while chan.recv_stderr_ready():
            err += chan.recv_stderr(65536); got = True
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        if time.time() > end:
            chan.close()
            raise TimeoutError(f"远端执行超时(>{deadline}s)")
        if not got:
            time.sleep(0.05)
    while chan.recv_ready():
        out += chan.recv(65536)
    while chan.recv_stderr_ready():
        err += chan.recv_stderr(65536)
    return chan.recv_exit_status(), out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


# ---------------------------------------------------------------- 本地打包（固定流程 1/3）

def build_local(args):
    info = {}
    do_server = args.only in ("both", "server")
    do_ubridge = args.only in ("both", "ubridge")

    if do_server:
        if args.server_branch:
            cur = run("git rev-parse --abbrev-ref HEAD", cwd=args.server_repo).strip()
            if cur != args.server_branch:
                run(f"git checkout {shlex.quote(args.server_branch)}", cwd=args.server_repo)
        os.makedirs(GW_DIR, exist_ok=True)
        run(f"rm -f {GW_DIR}/*.whl")
        venv_py = os.path.join(args.server_repo, "venv/bin/python")
        if not os.path.isfile(venv_py):
            raise SystemExit(f"找不到 {venv_py}（--server-repo 不对?）")
        run(f"{shlex.quote(venv_py)} -m pip wheel . --no-deps -w {GW_DIR}", cwd=args.server_repo)
        import glob
        wheels = glob.glob(f"{GW_DIR}/*.whl")
        if not wheels:
            raise SystemExit("pip wheel 没产出 .whl")
        info["wheel"] = os.path.basename(wheels[0])
        m = re.match(r"(.+)-(\d[^-]*)-(.+)\.whl$", info["wheel"])
        info["wheel_ver"] = m.group(2) if m else "?"
        info["server_src"] = run("git log -1 --format='%h %s'", cwd=args.server_repo).strip()
        info["server_dirty"] = "工作树有未提交改动" if run("git status --porcelain", cwd=args.server_repo).strip() else "工作树干净"
        if args.ai_features:
            reqs = []
            for name in AI_REQ_FILES:
                path = os.path.join(args.server_repo, name)
                if not os.path.isfile(path):
                    raise SystemExit(f"找不到 {path}（ai-features 依赖清单）")
                reqs.append(path)
            info["ai_reqs"] = reqs
        print(f"  wheel → {GW_DIR}/{info['wheel']}  （{info['server_src']}，{info['server_dirty']}）")
        if args.ai_features:
            print(f"  ai    → {', '.join(AI_REQ_FILES)}  （ai-features 依赖）")

    if do_ubridge:
        if args.ubridge_branch:
            run(f"git archive --format=tar.gz -o {UB_TAR} {shlex.quote(args.ubridge_branch)}", cwd=args.ubridge_repo)
            info["ubridge_src"] = run(f"git log -1 --format='%h %s' {shlex.quote(args.ubridge_branch)}", cwd=args.ubridge_repo).strip()
            info["ubridge_mode"] = f"git archive {args.ubridge_branch}"
        else:
            run(f"tar czf {UB_TAR} --exclude=./.git --exclude='*.o' --exclude=./ubridge -C {shlex.quote(args.ubridge_repo)} .")
            info["ubridge_src"] = run("git log -1 --format='%h %s'", cwd=args.ubridge_repo).strip()
            info["ubridge_mode"] = "当前工作树打包"
        print(f"  ubridge → {UB_TAR}  （{info['ubridge_mode']}，{info['ubridge_src']}）")
    return info


# ---------------------------------------------------------------- 远端安装（固定流程 2/4/5）

def render_remote(args, password, wheel):
    s = REMOTE_SCRIPT
    for ph, val in [
        ("__PW__", shlex.quote(password or "")),
        ("__VENV__", shlex.quote(args.venv)),
        ("__WHEEL__", shlex.quote(wheel or "none.whl")),
        ("__DO_SERVER__", "1" if args.only in ("both", "server") else "0"),
        ("__DO_AI__", "1" if args.only in ("both", "server") and args.ai_features else "0"),
        ("__DO_UBRIDGE__", "1" if args.only in ("both", "ubridge") else "0"),
        ("__DO_RESTART__", "0" if args.no_restart else "1"),
        ("__PINDEX__", shlex.quote(getattr(args, "pip_index", "") or "")),
    ]:
        s = s.replace(ph, val)
    return s


def deploy_host(host, args, password, script, uploads):
    r = {"host": host, "steps": {}, "info": {}, "error": None, "output": ""}
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        try:
            client = ssh_connect(host, args.user, password, args.port)
        except Exception as e:
            r["error"] = f"连接失败: {type(e).__name__}"
            return r
        sftp = client.open_sftp()
        for local in uploads:
            sftp.put(local, "/tmp/" + os.path.basename(local))
        sftp.close()
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


def stage(r, names):
    fails = [n for n in names if r["steps"].get(n) == "FAIL"]
    missing = [n for n in names if n not in r["steps"]]
    if missing:
        return f"FAIL(未执行:{','.join(missing)})"
    if fails:
        return f"FAIL({','.join(fails)})"
    return "OK"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-H", "--hosts", help="主机: IP/域名/末段区间/CIDR，逗号或空格分隔（不给则交互输入）")
    ap.add_argument("-u", "--user", help=f"VM 用户名（默认 {DEFAULT_USER}）")
    ap.add_argument("-p", "--password", help="密码（也支持环境变量 GNS3VM_PASSWORD；不给则交互输入）")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--only", choices=["both", "server", "ubridge"], default="both",
                    help="只部署其中一项（默认两项都做）")
    ap.add_argument("--no-ai-features", dest="ai_features", action="store_false",
                    help="不安装 ai-features 依赖（AI Copilot / MCP，默认安装）")
    ap.add_argument("--pip-index", default=DEFAULT_PIP_INDEX, metavar="URL",
                    help=f"ai 依赖的 pip 源（默认阿里源 {DEFAULT_PIP_INDEX}；直连官方传 https://pypi.org/simple）")
    ap.add_argument("--server-branch", help="gns3-server 打包前 checkout 的分支（默认不动，用当前状态）")
    ap.add_argument("--ubridge-branch", help="ubridge 用 git archive 打该分支（默认不打分支=当前工作树打包）")
    ap.add_argument("--server-repo", default=DEFAULT_SERVER_REPO)
    ap.add_argument("--ubridge-repo", default=DEFAULT_UBRIDGE_REPO)
    ap.add_argument("--venv", default=DEFAULT_VENV, help="VM 上 venv（找不到自动从 gns3.service 反推）")
    ap.add_argument("--no-restart", action="store_true", help="部署后不重启 gns3 服务")
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--build-only", help=argparse.SUPPRESS, action="store_true")  # 调试用
    args = ap.parse_args()

    if args.build_only:
        args.user = args.user or DEFAULT_USER
        password = args.password or os.environ.get("GNS3VM_PASSWORD")
    else:
        args.user = args.user or input(f"VM 用户名 [{DEFAULT_USER}]: ").strip() or DEFAULT_USER
        if not args.hosts:
            args.hosts = input("主机（IP/域名/192.168.101.20-25/CIDR，逗号或空格分隔）: ")
        password = args.password or os.environ.get("GNS3VM_PASSWORD") or getpass.getpass("密码: ")

    hosts = parse_hosts(args.hosts) if args.hosts else []
    if args.build_only:
        reachable, unreachable = [], []
    else:
        reachable, unreachable = probe_tcp(hosts, args.port)
        if unreachable:
            print(f"不可达(剔除): {', '.join(unreachable)}")
        if not reachable:
            print("没有可达主机。", file=sys.stderr)
            sys.exit(1)
    if hosts:
        print(f"目标 {len(hosts)} 台: {', '.join(hosts)}")

    print("\n[1/2] 本地打包")
    info = build_local(args)
    if args.build_only:
        print("（--build-only：未连接任何 VM）")
        return

    uploads = []
    if info.get("wheel"):
        uploads.append(f"{GW_DIR}/{info['wheel']}")
    if args.only in ("both", "server") and args.ai_features:
        uploads.extend(info.get("ai_reqs", []))
    if args.only in ("both", "ubridge"):
        uploads.append(UB_TAR)
    script = render_remote(args, password, info.get("wheel"))

    print(f"\n[2/2] 上传+安装+重启（{len(reachable)} 台并行 {min(args.parallel, len(reachable))}）")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(deploy_host, h, args, password, script, uploads): h for h in reachable}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  {r['host']}: " + (r["error"] or " ".join(f"{k}={v}" for k, v in sorted(r["steps"].items()))))

    print("\n" + "=" * 80)
    print(f"{'主机':<20}{'gns3-server':<24}{'ubridge':<20}{'gns3服务':<10}")
    print("-" * 80)
    all_ok = not unreachable
    for r in sorted(results, key=lambda x: hosts.index(x["host"])):
        h = r["host"]
        if r["error"] and not r["steps"]:
            print(f"{h:<20}{r['error']}")
            all_ok = False
            continue
        if args.only == "ubridge":
            s_col = "skip"
        else:
            s_col = stage(r, ["server"])
            ai_col = stage(r, ["ai"]) if args.ai_features else "skip"
            if s_col == "OK":
                v = r["info"].get("server-version", "?")
                s_col = f"OK {v}" + ("" if v == info.get("wheel_ver") else f" ≠本地{info['wheel_ver']}")
                if ai_col != "skip":
                    s_col += " +AI" if ai_col == "OK" else f" AI:{ai_col}"
            elif ai_col != "skip":
                s_col += f" AI:{ai_col}"
        if args.only == "server":
            u_col = "skip"
        else:
            u_col = stage(r, ["apt", "build", "install"])
            if u_col == "OK":
                u_col = "OK" if r["steps"].get("verify") == "OK" else "OK(校验FAIL)"
        if args.no_restart:
            svc = "skip"
        else:
            svc = r["info"].get("service", r["steps"].get("restart", "FAIL"))
        print(f"{h:<20}{s_col:<24}{u_col:<20}{svc:<10}")
        for k in ("venv", "which", "md5", "server-reason", "server-log", "ai-index", "ai-log", "ai-mcp",
                  "apt-log", "make-log", "inst-log", "journal"):
            if k in r["info"]:
                print(f"{'':<20}· {k}: {r['info'][k][:120]}")
        if r["error"]:
            print(f"{'':<20}! {r['error']}")
        ok = s_col in ("skip",) or (s_col.startswith("OK") and "FAIL" not in s_col)
        ok = ok and (u_col in ("skip",) or (u_col.startswith("OK") and "FAIL" not in u_col))
        ok = ok and (svc in ("skip", "active"))
        all_ok = all_ok and ok and not r["error"]

    logdir = f"{GW_DIR}/logs"
    os.makedirs(logdir, exist_ok=True)
    for r in results:
        with open(os.path.join(logdir, f"{r['host']}.log"), "w", encoding="utf-8") as f:
            f.write(r["output"])
    print("-" * 80)
    print(f"明细日志: {logdir}/")
    print("提醒: ① MTU/链路锚点在链路创建时固化，重启后需删链重连或重开项目才生效；\n"
          "      ② 多 compute 时所有 VM 都要跑本脚本，否则大帧死在对端桥出口。")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
