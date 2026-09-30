#!/usr/bin/env bash
# lib.sh — Lacan Knowledge OS 运行接口的共用函数（Batch 3）
#
# 纪律（Gate 逐条检查）：
#   * 只对**身份校验通过**的记录 PID 发信号；绝不做任何无差别的批量杀进程。
#   * 幂等：重复 start/stop 不产生第二个 UI，也不多出 MCP。
#   * 只读/只写运行期状态目录 `_workspace/runtime/`；不碰冻结核心与语料。
set -u

# ── 路径与解释器（由调用方 cd 到 REPO 后 source）
RUNTIME_DIR="${REPO:-$PWD}/_workspace/runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/ui.pid"
LOCK_DIR="$RUNTIME_DIR/.start.lock"
UI_MODULE="workspace_ui.server.cli"
MCP_MODULE="mcp_server/server.py"
LOG_MAX_BYTES=$((5 * 1024 * 1024))
LOG_KEEP=5

port="${LACAN_UI_PORT:-3090}"
host="${LACAN_UI_HOST:-127.0.0.1}"

python_bin() { command -v python3 2>/dev/null || true; }

ensure_runtime_dirs() { mkdir -p "$LOG_DIR" 2>/dev/null || true; }

log_file() { printf '%s/ui-%s.log' "$LOG_DIR" "$(date +%Y%m%d)"; }

ts() { date '+%Y-%m-%dT%H:%M:%S%z'; }

say()  { printf '[%s] %s\n' "$(ts)" "$*"; }
ok()   { printf '[%s] OK   %s\n' "$(ts)" "$*"; }
warn() { printf '[%s] WARN %s\n' "$(ts)" "$*"; }
die()  { printf '[%s] FAIL %s\n' "$(ts)" "$*" >&2; exit 1; }

# 同时打到 stdout **和**运行期日志文件（`logs/ui-YYYYMMDD.log`）。
# 用途：验收可以在"不真弹浏览器"的前提下，从日志文件里核对某一步确实执行了。
audit() {
  local line; line="[$(ts)] $*"
  printf '%s\n' "$line"
  ensure_runtime_dirs
  printf '%s\n' "$line" >> "$(log_file)" 2>/dev/null || true
}

# ── PID 记录读写
write_pid() { ensure_runtime_dirs; printf '%s\n' "$1" > "$PID_FILE"; }
read_pid()  { [ -f "$PID_FILE" ] && tr -d ' \n' < "$PID_FILE" || true; }
clear_pid() { rm -f "$PID_FILE" 2>/dev/null || true; }

# ── 身份校验：只有命令行里出现我们的 UI 模块才算"我们的进程"
proc_cmd()  { ps -o command= -p "$1" 2>/dev/null || true; }
proc_stat() { ps -o stat= -p "$1" 2>/dev/null | tr -d ' \n' || true; }
proc_ppid() { ps -o ppid= -p "$1" 2>/dev/null | tr -d ' \n' || true; }
proc_cwd() {                                   # → 进程 cwd（拿不到则空）
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n1 || true
}
# 解释器判定：命令行第一个 token 的 basename 是不是 Python（macOS 上是 Python.app 的 `Python`）
proc_is_python() {
  local cmd; cmd="$(proc_cmd "${1:-}")"
  [ -n "$cmd" ] || return 1
  local exe="${cmd%% *}"
  [ "$exe" != "$cmd" ] || return 1          # 有参数才算（排除裸命令名）
  case "$(basename "$exe")" in
    Python|Python3|python|python3|python3.*) return 0 ;;
    *) return 1 ;;
  esac
}
# 命令行里是否存在某个"独立的空格分隔 token"匹配给定通配（用于要求绝对路径参数）
proc_arg_matches() {                           # $1=pid  $2=case 通配
  local cmd tok; cmd="$(proc_cmd "${1:-}")"; [ -n "$cmd" ] || return 1
  for tok in $cmd; do
    case "$tok" in $2) return 0 ;; esac
  done
  return 1
}
is_uivproc() {
  local pid="${1:-}"; [ -n "$pid" ] || return 1
  local cmd; cmd="$(proc_cmd "$pid")"
  [ -n "$cmd" ] || return 1
  # 必须是"真的在跑这个模块"的进程：解释器 + `-m workspace_ui.server.cli`。
  # 只匹配模块名会把"命令行里恰好提到这个字符串"的进程（例如同仓库里别的
  # 脚本 `grep -c "workspace_ui.server.cli"` 的 bash）也算进来 —— 那会误杀。
  case "$cmd" in *"-m $UI_MODULE"*) ;; *) return 1 ;; esac
  proc_is_python "$pid"
}
# MCP 比 UI 容易撞名（其它项目也可能有 mcp_server/server.py），
# 所以要求"解释器 + 独立的绝对路径参数指向本仓库入口 + 属于本仓库"：
#   命令行含 REPO 绝对路径（正常情况）／父进程是我们的 UI。
is_mcp_proc() {
  local pid="${1:-}"; [ -n "$pid" ] || return 1
  proc_is_python "$pid" || return 1
  proc_arg_matches "$pid" "*/$MCP_MODULE" || return 1
  local cmd; cmd="$(proc_cmd "$pid")"
  case "$cmd" in *"$REPO"*) return 0 ;; esac
  local pp; pp="$(proc_ppid "$pid")"
  [ -n "$pp" ] && is_uivproc "$pp" && return 0
  return 1
}
# 僵尸进程对 kill -0 仍然成功，但已经不是"在跑的服务"，故显式排除
alive() {
  local s; s="$(proc_stat "$1")"
  [ -n "$s" ] || return 1
  case "$s" in *Z*) return 1 ;; esac
  kill -0 "$1" 2>/dev/null
}

# ── 我们名下的进程枚举（UI / MCP）——用于计数与收尾验证（僵尸进程不算"在跑"）
our_uipids() {
  ps -eo pid=,stat=,command= 2>/dev/null | while read -r p s c; do
    case "$s" in *Z*) continue ;; esac
    if is_uivproc "$p"; then printf '%s\n' "$p"; fi
  done
}
our_mcppids() {
  ps -eo pid=,stat=,command= 2>/dev/null | while read -r p s c; do
    case "$s" in *Z*) continue ;; esac
    if is_mcp_proc "$p"; then printf '%s\n' "$p"; fi
  done
}
count_uipids() { our_uipids | grep -c . 2>/dev/null || true; }
count_mcppids() { our_mcppids | grep -c . 2>/dev/null || true; }

# 我们这条实例的**端口作用域**：谁在监听我们的端口（且身份通过）
port_ui_pid() {
  local h; h="$(port_pid "$port" 2>/dev/null || true)"
  if [ -n "$h" ] && is_uivproc "$h"; then printf '%s' "$h"; fi
}
count_port_ui() { port_ui_pid | grep -c . 2>/dev/null || true; }
# 某个 PID 在监听哪些端口（空格分隔；拿不到/不监听则空）
pid_ports() {
  command -v lsof >/dev/null 2>&1 || return 0
  # ⚠️ 必须带 -a：不带时 lsof 把 -p 与 -i 取**并集**，会返回整个 fd 表
  #    （路径名被当成"端口"），从而把本实例误判成"别的实例"。
  lsof -nP -a -p "${1:-}" -iTCP -sTCP:LISTEN 2>/dev/null | tail -n +2 | awk '{print $9}' \
    | sed 's/.*://' | grep -E '^[0-9]+$' | sort -u | tr '\n' ' ' || true
}
# 记录里的 PID 是否**属于另一条实例**（身份像我们、却在监听别的端口）。
# 共享一个 `ui.pid` 的多会话环境里，这条判定让我们绝不接管/打扰别人的实例。
pid_owns_other_port() {                        # 0 = 它在监听别的端口
  local ports x; ports="$(pid_ports "${1:-}")"
  [ -n "$ports" ] || return 1
  for x in $ports; do
    [ "$x" != "$port" ] && return 0
  done
  return 1
}
# 某个 UI 的 MCP 子进程数（§26 判"有没有多起一套"就靠它）
count_mcp_children_of() { mcp_children_of "$1" | grep -c . 2>/dev/null || true; }

# 指定 PID 的**子进程**里属于我们 MCP 的那些（用于 stop 时连带收尾）
mcp_children_of() {
  local parent="${1:-}"
  [ -n "$parent" ] || return 0
  ps -eo pid=,ppid=,stat= 2>/dev/null | while read -r p pp s; do
    [ "$pp" = "$parent" ] || continue
    case "$s" in *Z*) continue ;; esac
    if is_mcp_proc "$p"; then printf '%s\n' "$p"; fi
  done
}

# ── 端口探测
port_pid() {                                  # → 监听该端口的 PID（可能为空）
  command -v lsof >/dev/null 2>&1 || return 0
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -n1 || true
}
port_listening() {
  local p="${1:-$port}"
  [ -n "$(port_pid "$p")" ] && return 0
  # 退路：直接 TCP 连接（不依赖 lsof）
  "$(python_bin)" - "$host" "$p" <<'PY' >/dev/null 2>&1
import socket, sys
h, p = sys.argv[1], int(sys.argv[2])
s = socket.socket(); s.settimeout(0.6)
try:
    s.connect((h, p)); sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

# ── HTTP（只读）
http_json() {                                  # $1 = path → stdout JSON，失败非零
  "$(python_bin)" - "$host" "$port" "$1" <<'PY'
import json, sys, urllib.request, urllib.error
h, p, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
url = "http://%s:%d%s" % (h, p, path)
try:
    with urllib.request.urlopen(url, timeout=8) as r:
        sys.stdout.write(r.read().decode("utf-8", "replace"))
except Exception as exc:
    sys.stderr.write("%s: %s\n" % (type(exc).__name__, exc)); sys.exit(1)
PY
}
http_code() {                                  # $1 = path → HTTP 状态码
  "$(python_bin)" - "$host" "$port" "$1" <<'PY'
import sys, urllib.request, urllib.error
h, p, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
url = "http://%s:%d%s" % (h, p, path)
try:
    with urllib.request.urlopen(url, timeout=8) as r:
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print(0)
PY
}

# ── 日志轮转（自实现；不用 logrotate）
rotate_logs() {
  ensure_runtime_dirs
  local cur; cur="$(log_file)"
  # ① 当前文件超限 → 重命名轮转
  if [ -f "$cur" ]; then
    local sz; sz=$(wc -c < "$cur" 2>/dev/null | tr -d ' ')
    if [ -n "$sz" ] && [ "$sz" -gt "$LOG_MAX_BYTES" ]; then
      mv "$cur" "${cur}.rot-$(date +%s)" 2>/dev/null || true
      say "ROTATED 日志超限（${sz} bytes > ${LOG_MAX_BYTES}）已轮转重命名"
    fi
  fi
  # ② 只保留最近 LOG_KEEP 个 ui-*.log*
  local n=0 f
  for f in $(ls -1t "$LOG_DIR"/ui-*.log* 2>/dev/null); do
    n=$((n + 1))
    if [ "$n" -gt "$LOG_KEEP" ]; then rm -f "$f" 2>/dev/null || true; fi
  done
}

# ── start 互斥锁（mkdir 原子性；陈旧锁按年龄清理）
acquire_lock() {
  ensure_runtime_dirs
  local waited=0
  while ! mkdir "$LOCK_DIR" 2>/dev/null; do
    if [ -f "$LOCK_DIR/ts" ]; then
      local age; age=$(( $(date +%s) - $(tr -d ' \n' < "$LOCK_DIR/ts" 2>/dev/null || echo 0) ))
      if [ "$age" -gt 120 ]; then
        warn "清理陈旧启动锁（${age}s）"
        rm -rf "$LOCK_DIR" 2>/dev/null || true
        continue
      fi
    fi
    waited=$((waited + 1))
    [ "$waited" -gt 40 ] && die "无法获取启动锁（${LOCK_DIR}）"
    sleep 0.25
  done
  date +%s > "$LOCK_DIR/ts" 2>/dev/null || true
}
release_lock() { rm -rf "$LOCK_DIR" 2>/dev/null || true; }

# ── 摘要输出（供 start/stop 共用）：第一行是**本实例口径**（断言看这个），
#    第二行是同仓库全量（多会话环境下会有别人的进程，仅诊断）
summary_processes() {                          # $1 = 本实例 UI pid（可选）
  local inst="${1:-}" kids=0 inst_ui=0
  if [ -n "$inst" ] && alive "$inst" && is_uivproc "$inst"; then
    inst_ui=1
    kids="$(count_mcp_children_of "$inst")"
  fi
  printf 'ui_processes=%s mcp_processes=%s（本实例口径）\n' "$inst_ui" "$kids"
  printf 'repo_wide_ui_processes=%s repo_wide_mcp_processes=%s（同仓库全量，可能含并发会话）\n' \
    "$(count_uipids)" "$(count_mcppids)"
}

# ══ §25 启动前置校验（**全部只读**：不调用 LLM、不重建语料、不 import bibliography、
#     不访问 Zotero；只写 _workspace/runtime/）
FREEZE_TOOL="_scripts/_tools/core_freeze.py"
LINEAGE_TOOL="_scripts/_tools/freeze_lineage.py"
MCP_SERVER_FILE="mcp_server/server.py"

# 单行摘要 + 退出码（stdout 只留最后一行非空输出，便于日志）
_free_check_tool() {                           # $1 = 工具相对路径
  local rel="$1" tool="$REPO/$1"
  if [ ! -f "$tool" ]; then printf 'FAIL tool_missing(%s)' "$rel"; return 2; fi
  local out rc
  out="$("$(python_bin)" "$tool" --verify 2>&1)"; rc=$?
  printf '%s' "$(printf '%s\n' "$out" | grep -v '^[[:space:]]*$' | tail -n1)"
  return $rc
}
verify_core_freeze()    { _free_check_tool "$FREEZE_TOOL"; }    # 0=PASS
verify_freeze_lineage() { _free_check_tool "$LINEAGE_TOOL"; }   # 0=PASS

# 运行期可写性（不碰核心/语料）
preflight_runtime() {
  local py; py="$(python_bin)"
  [ -n "$py" ] || { printf 'FAIL python3_not_found'; return 1; }
  ensure_runtime_dirs
  [ -d "$RUNTIME_DIR" ] || { printf 'FAIL runtime_dir_missing(%s)' "$RUNTIME_DIR"; return 1; }
  if ! : > "$RUNTIME_DIR/.write_probe" 2>/dev/null; then
    printf 'FAIL runtime_dir_not_writable(%s)' "$RUNTIME_DIR"; return 1
  fi
  rm -f "$RUNTIME_DIR/.write_probe" 2>/dev/null || true
  printf 'OK python3=%s runtime=%s' "$py" "$RUNTIME_DIR"
  return 0
}

# MCP 前置：**不预启动第二个 MCP 实例**，只做"模块在位 + 语法可编译"的就绪判定。
# 真实实例由 Workspace server 自己 spawn（保持恰好 1 个），其就绪由 health 步确认。
preflight_mcp() {
  local f="$REPO/$MCP_SERVER_FILE"
  [ -f "$f" ] || { printf 'FAIL mcp_module_missing(%s)' "$MCP_SERVER_FILE"; return 1; }
  local out rc
  out="$("$(python_bin)" -c 'import sys
src = open(sys.argv[1], encoding="utf-8", errors="replace").read()
compile(src, sys.argv[1], "exec")' "$f" 2>&1)"; rc=$?
  if [ "$rc" != 0 ]; then printf 'FAIL mcp_module_uncompilable: %s' "$(printf '%s\n' "$out" | tail -n1)"; return 1; fi
  printf 'OK module=%s（未预启动实例；由 Workspace server spawn，恰好 1 个）' "$MCP_SERVER_FILE"
  return 0
}

# 从 status JSON（stdin）取某一层的状态；缺失 → UNAVAILABLE（§38）
status_layer() {                               # $1 = 层名
  "$(python_bin)" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
lay = d.get("layers") if isinstance(d, dict) else None
lay = lay if isinstance(lay, dict) else {}
print(lay.get(sys.argv[1], "UNAVAILABLE"))' "$1"
}
