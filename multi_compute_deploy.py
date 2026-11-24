#!/usr/bin/env python3
"""multi_compute_deploy.py — 一条命令把 gns3-server(wheel) + ubridge(源码编译) 部署到 GNS3 VM 并重启服务。

用法:
  ./multi_compute_deploy.py                                  # 全交互: 依次提示 用户名 / 密码 / 主机
  ./multi_compute_deploy.py -H "192.168.101.21"              # 只提示输密码
  ./multi_compute_deploy.py -H "192.168.101.20-25,vm1.corp" -u gns3 -p 'xxx'
  ./multi_compute_deploy.py -H ... --ubridge-branch feature/capture-multi   # 指定分支(默认用仓库当前状态)
  ./multi_compute_deploy.py -H ... --server-pr 3103        # checkout GitHub PR 构建测试(完事自动切回原分支)
  ./multi_compute_deploy.py -H ... --server-venv ~/.venvs/gns3build  # 指定本地打包用 python(默认 <repo>/venv|/.venv)
  ./multi_compute_deploy.py -H ... --no-ai-features   # 只装 server 本体，不装 AI/MCP 依赖
  ./multi_compute_deploy.py -H ... --no-server-deps   # 不补装 requirements.txt 基础依赖
  ./multi_compute_deploy.py -H ... --pip-index https://pypi.org/simple   # ai 依赖直连官方源(默认阿里源)
  ./multi_compute_deploy.py -H ... --db-backups 5       # 备份保留份数（默认 10；0=部署时不备份数据库）
  ./multi_compute_deploy.py -H ... --list-backups       # 只列出各 VM 的数据库备份（不部署）
  ./multi_compute_deploy.py -H ... --restore-db         # 恢复最新数据库备份（停服→留安全网→拷回→起服）
  ./multi_compute_deploy.py -H ... --restore-db 2       # 恢复第 2 新的备份
  ./multi_compute_deploy.py -H ... --restore-db gns3_controller-20261124-153045-1f20fc6

固定流程（与你手工步骤一一对应）:
  1. 进入 gns3-server 仓库（--server-pr N 先 gh pr checkout N；--server-branch 先切分支）
     → 清 build/（陈旧 build/lib 会把已删/他分支文件混进 wheel，VM21-24 事故根因）
     → pip wheel → 核包（wheel 实际内容必须 ⊆ 当前源码树，幽灵文件/迁移缺失即中止）→ /tmp/auto_gw/
     （--server-pr 构建完自动切回原分支，不留工作树悬在 PR 上）
  2. 上传 wheel + requirements 到各 VM → 装包前在线备份控制器 DB（sqlite backup API，不停服）
     → /var/backups/gns3-db/gns3_controller-<时间戳>-<git短hash>.db + 同名 .manifest
     （manifest 记录 alembic rev/md5/size/git；同一代码同一 DB 状态不重复备份；保留最近 N 份）
     DB 定位与 gns3server 同规则：实际加载的 gns3_server.conf 同目录/gns3_controller.db；
     unit 里设了 GNS3_DATABASE_URI 则优先；conf 找不到才按默认位置兜底
  3. 进 venv 执行
     pip install --force-reinstall --no-deps（server 本体，不带依赖）
     pip install -r requirements.txt（基础依赖补装：已满足项跳过，新增项落地）
     pip install -r ai-requirements.txt -r mcp-requirements.txt（ai-features 依赖）
  4. 进入 ubridge 仓库 → 打包源码 → /tmp/ubridge.tar
  5. 上传到各 VM → 解压 → make / make install → which 验证
  6. 重启 gns3 服务并做真健康检查（45s 窗口：NRestarts=0 + 端口监听 + is-active；
     Restart=on-failure 下崩溃循环大多时间显示 active，只看 is-active 是假绿灯——VM21-24 事故教训）
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
# pyproject.toml: dependencies = {file = "requirements.txt"}（wheel --no-deps 不带依赖，部署时补装缺失项）
SERVER_REQ_FILE = "requirements.txt"
# pyproject.toml: ai-features = {file = ['ai-requirements.txt', 'mcp-requirements.txt']}
AI_REQ_FILES = ("ai-requirements.txt", "mcp-requirements.txt")
# VM 直连 pypi.org 国际链路仅几 KB/s 且中途停滞，langgraph 224KB 索引页拉不完即 "from versions: none"
# （2026-11-07 实测：同 VM 到国内镜像 0.4s 全量拉完，宿主直连官方源正常）；传 '' 可退回官方源
DEFAULT_PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
# 控制器 DB 备份目录/保留份数（每次装 server 前在线备份一份；0=禁用）
DB_BACKUP_DIR = "/var/backups/gns3-db"
DEFAULT_DB_BACKUPS = 10

# ---------------------------------------------------------------- 远端公共段（部署/恢复/列表共用）：
# 密码 sudo、venv 定位、控制器 DB 定位与当前 alembic rev 读取
COMMON_SH = r"""
set -u
PW=__PW__
VENV_DEF=__VENV__
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

# ---- 控制器 DB 定位（与 gns3server 同规则：实际加载的 gns3_server.conf 同目录/gns3_controller.db；
#      unit 里 GNS3_DATABASE_URI 优先；conf 找不到才按默认位置兜底）----
DBFILE=""
DBREV=""
if [ "$RESOLVE_DB" = 1 ]; then
  SRV_USER=$(systemctl show gns3 -p User --value 2>/dev/null)
  SUHOME=$(getent passwd "${SRV_USER:-gns3}" 2>/dev/null | cut -d: -f6)
  [ -n "$SUHOME" ] || SUHOME="$HOME"
  URI=""
  URI=$({ systemctl show gns3 -p Environment 2>/dev/null; systemctl cat gns3 2>/dev/null; } \
        | grep -oi 'GNS3_DATABASE_URI=[^ "]*' | head -1 | cut -d= -f2-)
  if [ -z "$URI" ]; then
    EF=$(systemctl cat gns3 2>/dev/null | sed -n 's/^[[:space:]]*EnvironmentFile=-\{0,1\}//p' | head -3)
    for f in $EF; do
      [ -f "$f" ] || continue
      URI=$(grep -i '^GNS3_DATABASE_URI=' "$f" 2>/dev/null | head -1 | cut -d= -f2-)
      [ -n "$URI" ] && break
    done
  fi
  URI=${URI#sqlite+aiosqlite://}; URI=${URI#sqlite://}; URI=${URI#sqlite:}
  if [ -n "$URI" ] && [ -f "$URI" ]; then
    DBFILE="$URI"
    info db-src "unit GNS3_DATABASE_URI"
  else
    VER=$("$VENV/bin/pip" show gns3-server 2>/dev/null | sed -n 's/^Version:[[:space:]]*\([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p')
    CONF=""
    for c in \
      "$SUHOME/.config/GNS3/${VER:-none}/gns3_server.conf" \
      "$SUHOME/.config/GNS3.conf" \
      /etc/gns3/gns3_server.conf \
      /etc/xdg/GNS3/gns3_server.conf \
      /etc/xdg/GNS3.conf; do
      [ -f "$c" ] && CONF="$c" && break
    done
    if [ -n "$CONF" ] && [ -f "$(dirname "$CONF")/gns3_controller.db" ]; then
      DBFILE="$(dirname "$CONF")/gns3_controller.db"
      info db-src "conf 同目录: $CONF"
    else
      for d in "$SUHOME"/.config/GNS3/*/ "$SUHOME/.config/GNS3/" /etc/gns3/; do
        [ -f "${d}gns3_controller.db" ] && DBFILE="${d}gns3_controller.db" && break
      done
      [ -n "$DBFILE" ] && info db-src "默认位置兜底"
    fi
  fi
  info db-path "${DBFILE:-not-found}"
  if [ -n "$DBFILE" ]; then
    DBREV=$(python3 - "$DBFILE" 2>/dev/null <<'PYREV' || true
import sqlite3, sys
try:
    con = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True, timeout=10)
    row = con.execute("select version_num from alembic_version").fetchone()
    if row:
        print(row[0])
    con.close()
except Exception:
    pass
PYREV
)
    [ -n "$DBREV" ] || DBREV=none
    info db-rev "$DBREV"
  fi
fi
"""

# ---- 服务真健康检查（VM21-24 事故教训4：Restart=on-failure 下崩溃循环大多时间显示 active，
#      只轮询 is-active 是假绿灯）——45s 窗口内要求 NRestarts=0 + 端口监听 + is-active 三者同时成立。
#      依赖 COMMON_SH 的 s()/$CONF。----
HEALTH_SH = r"""
HPORT=$(awk -F= '/^[[:space:]]*port[[:space:]]*=/{gsub(/[[:space:]]/, "", $2); print $2; exit}' "$CONF" 2>/dev/null)
if [ -n "$HPORT" ]; then
  PORT_OK() { s ss -ltn 2>/dev/null | grep -qE "[:.]$HPORT([[:space:]]|\$)"; }
else
  HPORT="(conf 无 port, 按 gns3server 进程监听)"
  PORT_OK() { s ss -ltnp 2>/dev/null | grep -q gns3server; }
fi
svc_health() {
  ST=""; NR="0"; LISTEN=""
  for i in $(seq 1 15); do
    sleep 3
    ST=$(s systemctl is-active gns3 2>/dev/null || true)
    NR=$(s systemctl show gns3 -p NRestarts --value 2>/dev/null)
    [ -n "$NR" ] || NR=0
    if PORT_OK; then LISTEN=1; else LISTEN=""; fi
    if [ "$ST" = active ] && [ -n "$LISTEN" ] && [ "$NR" -eq 0 ] 2>/dev/null; then
      break
    fi
  done
  info service "${ST:-unknown}"
  info health "port=$HPORT listen=${LISTEN:-no} nrestarts=$NR active=${ST:-unknown}"
  if [ "$ST" = active ] && [ -n "$LISTEN" ] && [ "$NR" -eq 0 ] 2>/dev/null; then
    step health OK
  else
    step health FAIL
    if [ "$NR" -gt 0 ] 2>/dev/null; then
      info health-reason "NRestarts=$NR → 崩溃循环（systemd 每 10s 自动拉起，is-active 显示 active 是假象）"
    elif [ -z "$LISTEN" ]; then
      info health-reason "端口未监听（server 没 bind 起来；MCP ECONNREFUSED 是果不是因）"
    fi
    s journalctl -u gns3 -n 30 --no-pager >/tmp/deploy-journal.log 2>&1 || true
    info journal "$(tail -n 5 /tmp/deploy-journal.log 2>/dev/null | tr '\n' ' ')"
  fi
}
"""

REMOTE_SCRIPT = r"""
DO_SERVER=__DO_SERVER__
RESOLVE_DB="$DO_SERVER"
DO_SDEPS=__DO_SDEPS__
DO_AI=__DO_AI__
DO_UBRIDGE=__DO_UBRIDGE__
DO_RESTART=__DO_RESTART__
PINDEX=__PINDEX__
DB_KEEP=__DBKEEP__
BKDIR=__BKDIR__
SRCHASH=__SRCHASH__
REVLIST=__REVLIST__
""" + COMMON_SH + HEALTH_SH + r"""
WHEEL=__WHEEL__

# ---- 装包前备份数据库（sqlite backup API 在线备份，不停服）----
if [ "$DO_SERVER" = 1 ]; then
  if [ "$DB_KEEP" -le 0 ] || [ -z "$DBFILE" ]; then
    step dbbackup SKIP
    [ "$DB_KEEP" -gt 0 ] && info db-skip "DB 未找到，跳过备份"
  else
    SKIPDUP=$(s ls -1t "$BKDIR"/*.manifest 2>/dev/null | head -1)
    if [ -n "$SKIPDUP" ] && s grep -q "^hash=$SRCHASH$" "$SKIPDUP" 2>/dev/null \
       && s grep -q "^rev=$DBREV$" "$SKIPDUP" 2>/dev/null; then
      step dbbackup SKIP
      info db-skip "同代码同 DB 状态已有备份: $(basename "$SKIPDUP")"
    elif s mkdir -p "$BKDIR" && s chown "$(id -un):$(id -gn)" "$BKDIR" 2>/dev/null; then
      TS=$(date +%Y%m%d-%H%M%S)
      BASE="gns3_controller-$TS-$SRCHASH"
      BK="$BKDIR/$BASE.db"
      if python3 - "$DBFILE" "$BK" <<'PYBK' 2>/tmp/deploy-dbbk.err
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=15)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
src.close()
PYBK
      then
        MD5=$(md5sum "$BK" 2>/dev/null | awk '{print $1}')
        SZ=$(stat -c %s "$BK" 2>/dev/null)
        if [ -n "$MD5" ] && [ -n "$SZ" ]; then
          {
            echo "ts=$TS"
            echo "src=$DBFILE"
            echo "rev=$DBREV"
            echo "hash=$SRCHASH"
            echo "git=__SRCSRC__"
            echo "wheel=__WHEELNAME__"
            echo "md5=$MD5"
            echo "size=$SZ"
          } > "$BKDIR/$BASE.manifest"
          chmod 600 "$BK" "$BKDIR/$BASE.manifest"
          i=0
          for m in $(ls -1t "$BKDIR"/*.manifest 2>/dev/null); do
            i=$((i+1))
            if [ "$i" -gt "$DB_KEEP" ]; then rm -f "$m" "${m%.manifest}.db"; fi
          done
          step dbbackup OK
          info db-file "$BASE.db"
          case ",$REVLIST," in
            *",$DBREV,"*) ;;
            *)
              if [ -n "$REVLIST" ] && [ "$DBREV" != "none" ]; then
                info downgrade-warning "当前 DB rev($DBREV) 不在本次部署代码的迁移链内 → 降级部署，重启后 gns3 将无法启动；先 --restore-db 回滚数据库再部署"
              fi ;;
          esac
        else
          step dbbackup FAIL
          info dbbackup-log "备份文件未生成/无法读取: $BK"
        fi
      else
        step dbbackup FAIL
        info dbbackup-log "$(tail -n 3 /tmp/deploy-dbbk.err 2>/dev/null | tr '\n' ' ')"
      fi
    else
      step dbbackup FAIL
      info dbbackup-log "无法创建备份目录 $BKDIR"
    fi
  fi
fi

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

if [ "$SERVER_OK" = 1 ] && [ "$DO_SDEPS" = 1 ]; then
  if [ ! -f /tmp/requirements.txt ]; then
    step sdeps FAIL
    info sdeps-log "requirements 未上传: /tmp/requirements.txt"
  else
    SD_IDX=()
    [ -n "$PINDEX" ] && SD_IDX+=(-i "$PINDEX")
    info sdeps-index "${PINDEX:-官方源}"
    # 普通安装语义：已满足项跳过(不联网)，仅新增/缺失项走源下载
    if "$VENV/bin/pip" install -r /tmp/requirements.txt "${SD_IDX[@]}" >/tmp/deploy-pip-sdeps.log 2>&1; then
      step sdeps OK
    else
      step sdeps FAIL
      info sdeps-log "$(tail -n 5 /tmp/deploy-pip-sdeps.log 2>/dev/null | tr '\n' ' ')"
    fi
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
    step restart OK
    svc_health
  else
    step restart FAIL
    info restart-log "$(tail -n 5 /tmp/deploy-restart.log 2>/dev/null | tr '\n' ' ')"
  fi
fi
info done 1
"""

# ---- --list-backups：只读，列出备份清单 ----
LIST_SCRIPT = r"""
RESOLVE_DB=1
BKDIR=__BKDIR__
""" + COMMON_SH + r"""
N=0
for m in $(s ls -1t "$BKDIR"/*.manifest 2>/dev/null); do
  N=$((N+1))
  DBF="${m%.manifest}.db"
  echo "###BK:begin"
  echo "###BK:name=$(basename "$DBF")"
  echo "###BK:size=$(s stat -c %s "$DBF" 2>/dev/null || echo '?')"
  s cat "$m" 2>/dev/null | sed 's/^/###BK:/'
  echo "###BK:end"
done
[ "$N" -gt 0 ] || echo "###BK:none=1"
info done 1
"""

# ---- --restore-db：停服 → 当前库先留安全网 → 拷回备份 → 起服 ----
RESTORE_SCRIPT = r"""
RESOLVE_DB=1
DO_RESTART=__DO_RESTART__
WHICH=__WHICH__
BKDIR=__BKDIR__
DB_KEEP=__DBKEEP__
""" + COMMON_SH + HEALTH_SH + r"""
if [ -z "$DBFILE" ]; then
  step restore FAIL
  info restore-log "未定位到控制器 DB，中止"
  info done 1
  exit 0
fi

# 1) 选备份：latest / 序号N(1=最新) / 备份文件名
case "$WHICH" in
  latest) SEL=$(s ls -1t "$BKDIR"/*.manifest 2>/dev/null | head -1) ;;
  ''|*[!0-9]*)
    case "$WHICH" in
      *.manifest) SEL="$BKDIR/$WHICH" ;;
      *.db)       SEL="${BKDIR}/${WHICH%.db}.manifest" ;;
      *)          SEL="$BKDIR/$WHICH.manifest" ;;
    esac ;;
  *) SEL=$(s ls -1t "$BKDIR"/*.manifest 2>/dev/null | sed -n "${WHICH}p") ;;
esac
if [ -z "$SEL" ] || ! s test -f "$SEL" || ! s test -f "${SEL%.manifest}.db"; then
  step restore FAIL
  info restore-log "找不到备份($WHICH): ${SEL:-无}；先 --list-backups 查看清单"
  info done 1
  exit 0
fi
BKDB="${SEL%.manifest}.db"
step restore-pick OK
info restore-file "$(basename "$BKDB")"
info restore-manifest "$(s grep -v '^md5=' "$SEL" 2>/dev/null | tr '\n' ' ')"

# 2) 停服（必须：替换正在被写的主库文件）
if s systemctl stop gns3; then
  step stop OK
else
  step stop FAIL
  info restore-log "systemctl stop gns3 失败，中止"
  info done 1
  exit 0
fi

# 3) 恢复前把当前库也留一份（安全网；服务已停，直接 cp 三件套）
PRE="gns3_controller-$(date +%Y%m%d-%H%M%S)-pre-restore"
s mkdir -p "$BKDIR"
s cp -a "$DBFILE" "$BKDIR/$PRE.db"
for suf in -wal -shm; do
  s test -f "$DBFILE$suf" && s cp -a "$DBFILE$suf" "$BKDIR/$PRE.db$suf"
done
printf 'ts=pre-restore\nsrc=%s\nrev=%s\nhash=pre-restore\nnote=--restore-db 恢复前的当前库安全网\n' \
  "$DBFILE" "$DBREV" | s tee "$BKDIR/$PRE.manifest" >/dev/null
if [ "$DB_KEEP" -gt 0 ]; then
  i=0
  for m in $(s ls -1t "$BKDIR"/*.manifest 2>/dev/null); do
    i=$((i+1))
    if [ "$i" -gt "$DB_KEEP" ]; then s rm -f "$m" "${m%.manifest}.db"; fi
  done
fi

# 4) 拷回（清掉残留 -wal/-shm，保属主/权限）
OWNER=$(s stat -c %U:%G "$(dirname "$DBFILE")")
MODE=$(s stat -c %a "$DBFILE")
if s cp -f "$BKDB" "$DBFILE" && s rm -f "$DBFILE-wal" "$DBFILE-shm" \
   && s chown "$OWNER" "$DBFILE" && s chmod "${MODE:-600}" "$DBFILE"; then
  step restore OK
else
  step restore FAIL
  info restore-log "拷回失败（$BKDB → $DBFILE）"
  info done 1
  exit 0
fi

# 5) 起服 + 复核（真健康检查：NRestarts=0 + 端口监听 + is-active）
if [ "$DO_RESTART" = 1 ]; then
  s systemctl start gns3 || true
  svc_health
  NR=$(python3 - "$DBFILE" 2>/dev/null <<'PYREV' || true
import sqlite3, sys
try:
    con = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True, timeout=10)
    row = con.execute("select version_num from alembic_version").fetchone()
    if row:
        print(row[0])
    con.close()
except Exception:
    pass
PYREV
)
  info db-rev-now "${NR:-unknown}"
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


# ---------------------------------------------------------------- 本地打包（固定流程 1/4）

def verify_wheel(repo, wheel_path):
    """核包：wheel 实际内容必须 ⊆ 当前源码树（ghost 文件 = 陈旧 build/lib 混入，VM21-24 事故根因）；
    迁移目录里的 .py 缺失也拦（会导致 DB 已有 rev 在新代码里找不到）。违规即中止，不发这个包。"""
    import zipfile
    with zipfile.ZipFile(wheel_path) as z:
        wheel_files = set(z.namelist())
    src_files = set()
    for root, dirs, files in os.walk(os.path.join(repo, "gns3server")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            src_files.add(os.path.relpath(os.path.join(root, f), repo))
    wheel_only = sorted(f for f in wheel_files if ".dist-info/" not in f and f not in src_files)
    mig_prefix = os.path.join("gns3server", "db_migrations", "versions") + os.sep
    mig_missing = sorted(
        f for f in src_files
        if f.startswith(mig_prefix) and f.endswith(".py") and f not in wheel_files
    )
    if wheel_only or mig_missing:
        for f in wheel_only[:10]:
            print(f"  幽灵文件(wheel 有/源码无): {f}", file=sys.stderr)
        for f in mig_missing[:10]:
            print(f"  迁移文件缺失(wheel 无/源码有): {f}", file=sys.stderr)
        raise SystemExit(
            f"核包失败: wheel-only {len(wheel_only)} 个 / 迁移缺失 {len(mig_missing)} 个 —— 不要部署这个包"
        )
    print(f"  核包 → wheel-only 0 / 迁移缺失 0（wheel 共 {len(wheel_files)} 文件）")


def checkout_pr(repo, pr):
    """--server-pr：checkout 指定 GitHub PR（gh 优先，自动处理 fork PR 的 remote；
    无 gh 退 git fetch pull/N/head），返回原分支供构建后切回。要求工作树干净——
    否则脏改动会被 checkout 带进 PR 构建（幽灵文件事故的变体）。"""
    if run("git status --porcelain", cwd=repo).strip():
        raise SystemExit("--server-pr 要求工作树干净（先 commit/stash），否则脏改动会被带进 PR 构建")
    orig = run("git rev-parse --abbrev-ref HEAD", cwd=repo).strip()
    import shutil
    if shutil.which("gh"):
        run(f"gh pr checkout {pr}", cwd=repo)
    else:
        remotes = run("git remote", cwd=repo).split()
        rem = "upstream" if "upstream" in remotes else ("origin" if "origin" in remotes else "")
        if not rem:
            raise SystemExit("无 gh 且仓库没有任何 remote，无法取 PR")
        run(f"git fetch {rem} pull/{pr}/head", cwd=repo)
        run("git checkout --detach FETCH_HEAD", cwd=repo)
    return orig


def resolve_build_python(repo, explicit):
    """本地打包用的 python：--server-venv 显式指定（venv 目录或解释器路径）优先；
    不给则依次找 <repo>/venv、<repo>/.venv；都没有退回系统 python3
    （pip wheel 走 PEP517 隔离构建不依赖 venv 内容，迁移链读取缺 alembic 时自动跳过降级预警）。"""
    import shutil
    cands = []
    if explicit:
        if os.path.isdir(explicit):
            cands += [os.path.join(explicit, "bin", "python"), os.path.join(explicit, "bin", "python3")]
        else:
            cands.append(explicit)
    else:
        cands = [os.path.join(repo, d, "bin", "python") for d in ("venv", ".venv")]
    for c in cands:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    if explicit:
        raise SystemExit(f"--server-venv 指定的解释器/venv 不存在: {explicit}")
    py3 = shutil.which("python3")
    if not py3:
        raise SystemExit("找不到打包用 python：repo 里无 venv/.venv 且系统无 python3；用 --server-venv 指定")
    print(f"  （repo 里没找到 venv/.venv，退回系统 python3: {py3}；若缺 alembic，迁移链读取与降级预警自动跳过）")
    return py3


def _build_server(args, info):
    """server 本体出包（清 build → pip wheel → 核包 → 读迁移链 → 收集依赖清单）。
    --server-pr 时调用方已 checkout PR，本函数全程跑在 PR 树上，结束后由调用方切回。"""
    os.makedirs(GW_DIR, exist_ok=True)
    run(f"rm -f {GW_DIR}/*.whl")
    venv_py = resolve_build_python(args.server_repo, getattr(args, "server_venv", None))
    # 出包前必清 build/：setuptools 复用 build 缓存，陈旧 build/lib 会把已删/他分支文件打进 wheel
    # （VM21-24 崩溃循环事故根因；git status 干净 ≠ 包干净）
    run("rm -rf build", cwd=args.server_repo)
    run(f"{shlex.quote(venv_py)} -m pip wheel . --no-deps -w {GW_DIR}", cwd=args.server_repo)
    import glob
    wheels = glob.glob(f"{GW_DIR}/*.whl")
    if not wheels:
        raise SystemExit("pip wheel 没产出 .whl")
    verify_wheel(args.server_repo, wheels[0])
    info["wheel"] = os.path.basename(wheels[0])
    m = re.match(r"(.+)-(\d[^-]*)-(.+)\.whl$", info["wheel"])
    info["wheel_ver"] = m.group(2) if m else "?"
    info["server_src"] = run("git log -1 --format='%h %s'", cwd=args.server_repo).strip()
    info["server_dirty"] = "工作树有未提交改动" if run("git status --porcelain", cwd=args.server_repo).strip() else "工作树干净"
    head, revs = alembic_revs(args.server_repo, venv_py)
    info["alembic_head"] = head
    info["alembic_revs"] = revs
    print(f"  alembic → head={head or '未知'}（{len(revs)} 个迁移版本）")
    if getattr(args, "server_pr", None):
        print(f"  PR #{args.server_pr} → {info['server_src']}")
    if args.server_deps:
        req = os.path.join(args.server_repo, SERVER_REQ_FILE)
        if not os.path.isfile(req):
            raise SystemExit(f"找不到 {req}（gns3-server 基础依赖清单）")
        info["server_req"] = req
    if args.ai_features:
        reqs = []
        for name in AI_REQ_FILES:
            path = os.path.join(args.server_repo, name)
            if not os.path.isfile(path):
                raise SystemExit(f"找不到 {path}（ai-features 依赖清单）")
            reqs.append(path)
        info["ai_reqs"] = reqs
    print(f"  wheel → {GW_DIR}/{info['wheel']}  （{info['server_src']}，{info['server_dirty']}）")
    if args.server_deps:
        print(f"  reqs  → {SERVER_REQ_FILE}  （server 基础依赖，部署时补装缺失项）")
    if args.ai_features:
        print(f"  ai    → {', '.join(AI_REQ_FILES)}  （ai-features 依赖）")


def build_local(args):
    info = {}
    do_server = args.only in ("both", "server")
    do_ubridge = args.only in ("both", "ubridge")

    if do_server:
        if getattr(args, "server_pr", None) and args.server_branch:
            raise SystemExit("--server-pr 与 --server-branch 互斥，一次只测一个")
        prev_ref = None
        if getattr(args, "server_pr", None):
            prev_ref = checkout_pr(args.server_repo, args.server_pr)
            info["server_pr"] = args.server_pr
        elif args.server_branch:
            cur = run("git rev-parse --abbrev-ref HEAD", cwd=args.server_repo).strip()
            if cur != args.server_branch:
                run(f"git checkout {shlex.quote(args.server_branch)}", cwd=args.server_repo)
        try:
            _build_server(args, info)
        finally:
            if prev_ref:
                run(f"git checkout {shlex.quote(prev_ref)}", cwd=args.server_repo)
                print(f"  已切回原分支 {prev_ref}（PR 构建完不留工作树）")

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


# ---------------------------------------------------------------- 远端安装（固定流程 2/3.5/4/5）

def render_script(script, mapping):
    for ph, val in mapping.items():
        script = script.replace(ph, val)
    return script


def render_remote(args, password, wheel, info):
    src = info.get("server_src", "")
    mapping = {
        "__PW__": shlex.quote(password or ""),
        "__VENV__": shlex.quote(args.venv),
        "__WHEEL__": shlex.quote(wheel or "none.whl"),
        "__DO_SERVER__": "1" if args.only in ("both", "server") else "0",
        "__DO_SDEPS__": "1" if args.only in ("both", "server") and args.server_deps else "0",
        "__DO_AI__": "1" if args.only in ("both", "server") and args.ai_features else "0",
        "__DO_UBRIDGE__": "1" if args.only in ("both", "ubridge") else "0",
        "__DO_RESTART__": "0" if args.no_restart else "1",
        "__PINDEX__": shlex.quote(getattr(args, "pip_index", "") or ""),
        "__DBKEEP__": str(max(0, getattr(args, "db_backups", DEFAULT_DB_BACKUPS))),
        "__BKDIR__": shlex.quote(DB_BACKUP_DIR),
        "__SRCHASH__": src.split()[0] if src else "unknown",
        "__SRCSRC__": shlex.quote(src or "unknown"),
        "__WHEELNAME__": shlex.quote(os.path.basename(wheel) if wheel else "unknown"),
        "__REVLIST__": ",".join(info.get("alembic_revs", [])),
    }
    return render_script(REMOTE_SCRIPT, mapping)


def render_aux(script, args, password, extra=None):
    mapping = {
        "__PW__": shlex.quote(password or ""),
        "__VENV__": shlex.quote(args.venv),
        "__BKDIR__": shlex.quote(DB_BACKUP_DIR),
        "__DBKEEP__": str(max(0, getattr(args, "db_backups", DEFAULT_DB_BACKUPS))),
        "__DO_RESTART__": "0" if args.no_restart else "1",
    }
    mapping.update(extra or {})
    return render_script(script, mapping)


def alembic_revs(repo, venv_py):
    """读取本地仓库的迁移链（head + 全部 revision），用于降级预警。读不到就跳过，不阻塞部署。"""
    mig = os.path.join(repo, "gns3server", "db_migrations")
    code = (
        "from alembic.script import ScriptDirectory\n"
        f"sd = ScriptDirectory({mig!r})\n"
        "try:\n"
        "    print(sd.get_current_head() or '')\n"
        "except Exception:\n"
        "    print('')\n"
        "print(' '.join(r.revision for r in sd.walk_revisions()))\n"
    )
    try:
        out = run(f"{shlex.quote(venv_py)} -c {shlex.quote(code)}").strip().splitlines()
    except SystemExit as e:
        print(f"  （迁移链读取失败，降级预警不可用: {e}）")
        return "", []
    head = out[0].strip() if out and out[0].strip() else ""
    revs = out[1].split() if len(out) > 1 else []
    return head, revs


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


def hsize(v):
    try:
        n = int(str(v))
    except (TypeError, ValueError):
        return str(v) if v else "?"
    for unit in ("", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "" else f"{n:.1f}{unit}"
        n /= 1024.0


def parse_list_output(out):
    blocks, cur = [], None
    for line in out.splitlines():
        if not line.startswith("###BK:"):
            continue
        kv = line[6:]
        if kv == "begin":
            cur = {}
        elif kv == "end":
            if cur:
                blocks.append(cur)
            cur = None
        elif cur is not None:
            k, _, v = kv.partition("=")
            cur[k] = v
    return blocks


def summarize_list(results, hosts):
    print("\n" + "=" * 80)
    all_ok = True
    for r in sorted(results, key=lambda x: hosts.index(x["host"])):
        if r["error"]:
            print(f"  {r['host']}: {r['error']}")
            all_ok = False
            continue
        print(f"  {r['host']}  DB: {r['info'].get('db-path', '?')}  当前 rev: {r['info'].get('db-rev', '?')}")
        blocks = parse_list_output(r["output"])
        if not blocks:
            print("    （无备份）")
            continue
        for i, b in enumerate(blocks, 1):
            note = " [安全网]" if b.get("hash") == "pre-restore" else ""
            print(f"    #{i} {b.get('name', '?')}  {hsize(b.get('size'))}  rev={b.get('rev', '?')}"
                  f"  {b.get('git', b.get('hash', ''))}{note}")
    sys.exit(0 if all_ok else 1)


def summarize_restore(results, hosts, args):
    print("\n" + "=" * 80)
    print(f"{'主机':<20}{'恢复':<34}{'gns3服务':<10}")
    print("-" * 80)
    all_ok = True
    for r in sorted(results, key=lambda x: hosts.index(x["host"])):
        h = r["host"]
        if r["error"] and not r["steps"]:
            print(f"{h:<20}{r['error']}")
            all_ok = False
            continue
        col = stage(r, ["restore-pick", "stop", "restore"])
        if args.no_restart:
            svc = "skip"
        else:
            svc = r["info"].get("service", r["steps"].get("start", "FAIL"))
            if r["steps"].get("health") == "FAIL":
                svc = "FAIL(健康检查)"
        print(f"{h:<20}{col:<34}{svc:<10}")
        for k in ("restore-file", "restore-manifest", "service", "db-rev-now", "db-path", "db-rev",
                  "restore-log", "health", "health-reason", "journal"):
            if k in r["info"]:
                print(f"{'':<20}· {k}: {r['info'][k][:140]}")
        ok = col == "OK" and svc in ("skip", "active")
        all_ok = all_ok and ok and not r["error"]
    sys.exit(0 if all_ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-H", "--hosts", help="主机: IP/域名/末段区间/CIDR，逗号或空格分隔（不给则交互输入）")
    ap.add_argument("-u", "--user", help=f"VM 用户名（默认 {DEFAULT_USER}）")
    ap.add_argument("-p", "--password", help="密码（也支持环境变量 GNS3VM_PASSWORD；不给则交互输入）")
    ap.add_argument("--port", type=int, default=22, help="SSH 端口（默认 22）")
    ap.add_argument("--only", choices=["both", "server", "ubridge"], default="both",
                    help="只部署其中一项（默认两项都做）")
    ap.add_argument("--no-ai-features", dest="ai_features", action="store_false",
                    help="不安装 ai-features 依赖（AI Copilot / MCP，默认安装）")
    ap.add_argument("--no-server-deps", dest="server_deps", action="store_false",
                    help="不补装 gns3-server requirements.txt 基础依赖（默认安装；wheel --no-deps 不带依赖，新增依赖须靠此步落地）")
    ap.add_argument("--pip-index", default=DEFAULT_PIP_INDEX, metavar="URL",
                    help=f"ai 依赖的 pip 源（默认阿里源 {DEFAULT_PIP_INDEX}；直连官方传 https://pypi.org/simple）")
    ap.add_argument("--server-branch", help="gns3-server 打包前 checkout 的分支（默认不动，用当前状态）")
    ap.add_argument("--server-pr", type=int, metavar="N",
                    help="部署前 checkout 该 GitHub PR 构建（gh 优先，退 git fetch pull/N/head；要求工作树干净；"
                         "构建完自动切回原分支；与 --server-branch 互斥）")
    ap.add_argument("--ubridge-branch", help="ubridge 用 git archive 打该分支（默认不打分支=当前工作树打包）")
    ap.add_argument("--server-repo", default=DEFAULT_SERVER_REPO,
                    help=f"gns3-server 本地仓库（默认 {DEFAULT_SERVER_REPO}）")
    ap.add_argument("--server-venv", default=None, metavar="PATH",
                    help="本地打包用的 python（venv 目录或解释器路径；默认依次找 <repo>/venv、<repo>/.venv，"
                         "都没有退回系统 python3；注意与 --venv 区分，后者是 VM 上的运行 venv）")
    ap.add_argument("--ubridge-repo", default=DEFAULT_UBRIDGE_REPO,
                    help=f"ubridge 本地仓库（默认 {DEFAULT_UBRIDGE_REPO}）")
    ap.add_argument("--venv", default=DEFAULT_VENV, help="VM 上 venv（找不到自动从 gns3.service 反推）")
    ap.add_argument("--no-restart", action="store_true", help="部署后不重启 gns3 服务")
    ap.add_argument("--db-backups", type=int, default=DEFAULT_DB_BACKUPS, metavar="N",
                    help=f"装包前数据库备份的保留份数（默认 {DEFAULT_DB_BACKUPS}；0=部署时不备份数据库）")
    ap.add_argument("--list-backups", action="store_true", help="只列出各 VM 的数据库备份清单（不部署）")
    ap.add_argument("--restore-db", nargs="?", const="latest", metavar="WHICH",
                    help="恢复数据库备份后退出（不部署）：latest=最新 / 序号N(1=最新) / 备份文件名")
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

    mode = "list" if args.list_backups else ("restore" if args.restore_db else "deploy")
    info = {}
    uploads = []
    if mode == "list":
        script = render_aux(LIST_SCRIPT, args, password)
        print(f"\n[1/1] 列出数据库备份（{len(reachable)} 台并行 {min(args.parallel, len(reachable))}）")
    elif mode == "restore":
        script = render_aux(RESTORE_SCRIPT, args, password, {"__WHICH__": shlex.quote(str(args.restore_db))})
        print(f"\n[1/1] 恢复数据库备份(选择={args.restore_db}，{len(reachable)} 台并行 {min(args.parallel, len(reachable))})")
    else:
        print("\n[1/2] 本地打包")
        info = build_local(args)
        if args.build_only:
            print("（--build-only：未连接任何 VM）")
            return
        if info.get("wheel"):
            uploads.append(f"{GW_DIR}/{info['wheel']}")
        if args.only in ("both", "server") and args.server_deps and info.get("server_req"):
            uploads.append(info["server_req"])
        if args.only in ("both", "server") and args.ai_features:
            uploads.extend(info.get("ai_reqs", []))
        if args.only in ("both", "ubridge"):
            uploads.append(UB_TAR)
        script = render_remote(args, password, info.get("wheel"), info)
        print(f"\n[2/2] 上传+安装+重启（{len(reachable)} 台并行 {min(args.parallel, len(reachable))}）")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(deploy_host, h, args, password, script, uploads): h for h in reachable}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  {r['host']}: " + (r["error"] or " ".join(f"{k}={v}" for k, v in sorted(r["steps"].items()))))

    if mode == "list":
        summarize_list(results, hosts)
    if mode == "restore":
        summarize_restore(results, hosts, args)

    print("\n" + "=" * 80)
    print(f"{'主机':<20}{'gns3-server':<24}{'ubridge':<20}{'DB备份':<12}{'gns3服务':<10}")
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
            dep_col = stage(r, ["sdeps"]) if args.server_deps else "skip"
            ai_col = stage(r, ["ai"]) if args.ai_features else "skip"
            extra = ""
            if dep_col != "skip":
                extra += " +DEP" if dep_col == "OK" else f" DEP:{dep_col}"
            if ai_col != "skip":
                extra += " +AI" if ai_col == "OK" else f" AI:{ai_col}"
            if s_col == "OK":
                v = r["info"].get("server-version", "?")
                s_col = f"OK {v}" + ("" if v == info.get("wheel_ver") else f" ≠本地{info['wheel_ver']}") + extra
            else:
                s_col += extra
        if args.only == "server":
            u_col = "skip"
        else:
            u_col = stage(r, ["apt", "build", "install"])
            if u_col == "OK":
                u_col = "OK" if r["steps"].get("verify") == "OK" else "OK(校验FAIL)"
        if args.only == "ubridge" or args.db_backups <= 0:
            db_col = "skip"
        else:
            db_col = stage(r, ["dbbackup"])
            if db_col == "OK" and "downgrade-warning" in r["info"]:
                db_col = "OK(降级!)"
        if args.no_restart:
            svc = "skip"
        else:
            svc = r["info"].get("service", r["steps"].get("restart", "FAIL"))
            if r["steps"].get("health") == "FAIL":
                svc = "FAIL(健康检查)"
        print(f"{h:<20}{s_col:<24}{u_col:<20}{db_col:<12}{svc:<10}")
        for k in ("venv", "which", "md5", "server-reason", "server-log", "sdeps-index", "sdeps-log",
                  "ai-index", "ai-log", "ai-mcp", "apt-log", "make-log", "inst-log", "journal",
                  "db-src", "db-path", "db-rev", "db-file", "db-skip", "downgrade-warning", "dbbackup-log",
                  "health", "health-reason"):
            if k in r["info"]:
                print(f"{'':<20}· {k}: {r['info'][k][:120]}")
        if r["error"]:
            print(f"{'':<20}! {r['error']}")
        ok = s_col in ("skip",) or (s_col.startswith("OK") and "FAIL" not in s_col)
        ok = ok and (u_col in ("skip",) or (u_col.startswith("OK") and "FAIL" not in u_col))
        ok = ok and (db_col in ("skip",) or (db_col.startswith("OK") and "FAIL" not in db_col))
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
