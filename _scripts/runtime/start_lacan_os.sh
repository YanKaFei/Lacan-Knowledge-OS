#!/usr/bin/env bash
# start_lacan_os.sh — 启动 Lacan Knowledge OS（只启动 UI 一个进程；MCP 由 UI 自己 spawn）
#
# §25 启动顺序（严格）：
#     ① verify runtime → ② core freeze → ③ freeze lineage → ④ MCP
#     → ⑤ Workspace server → ⑥ health → ⑦ default browser
#   ②/③ 不过 → **不启动**，明确报错并非 0 退出。
#   启动路径不做：调用 LLM、重建 corpus、import bibliography、访问 Zotero API。
#
# §26 Double Start：已在跑 → **不启动第二套 MCP/server**，只做 health → 打开浏览器 → 退 0。
# §27 只对「记录 + 身份校验通过」的 PID 发信号；绝不做任何无差别的批量杀进程。
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=/dev/null
. "$HERE/lib.sh"

URL="http://${host}:${port}/"
trap 'release_lock' EXIT

ensure_runtime_dirs
rotate_logs
acquire_lock

PY="$(python_bin)"
[ -n "$PY" ] || die "找不到 python3"

open_browser() {                               # §25 第 7 步 / §26
  # LACAN_OPEN_CMD 可替换打开浏览器的命令（缺省 open）。
  # 用途：验收时 `LACAN_OPEN_CMD=/bin/echo` 就能**不真弹浏览器**却证明这一步被执行——
  #       日志里会出现 browser_open url=... 那一行。
  if [ "${LACAN_NO_OPEN:-0}" = "1" ]; then
    audit "browser_open skipped url=${URL} reason=LACAN_NO_OPEN"
    return 0
  fi
  local cmd="${LACAN_OPEN_CMD:-open}"
  local resolved; resolved="$(command -v "$cmd" 2>/dev/null || true)"
  [ -n "$resolved" ] || resolved="$cmd"
  audit "browser_open url=${URL} cmd=${resolved}"
  "$cmd" "$URL" >/dev/null 2>&1 || warn "打开浏览器失败：$cmd $URL（不影响服务）"
  return 0
}

# ── §26 已在跑：health → browser → exit 0（不 spawn 任何进程）
already_running() {                            # $1 = pid  $2 = 来源
  local p="$1" src="$2"
  ok "ALREADY_RUNNING pid=$p url=${URL}（来源=${src}；未 spawn 任何进程）"
  local code; code="$(http_code /api/status 2>/dev/null || echo 0)"
  if [ "$code" = "200" ]; then
    ok "HEALTH code=200"
  else
    warn "HEALTH code=${code}（进程在跑但 /api/status 不健康；未 spawn 任何进程）"
    summary_processes "$p"
    exit 1
  fi
  summary_processes "$p"
  printf '[%s] 提示：第二次启动只做 health → 打开浏览器，未启动第二套 MCP/server\n' "$(ts)"
  open_browser
  exit 0
}

# ══ §26 前置：已有记录 / 端口已被我们的实例监听？
prev="$(read_pid)"
if [ -n "$prev" ] && pid_owns_other_port "$prev"; then
  warn "记录 PID $prev 在监听**别的端口**（$(pid_ports "$prev")）→ 属于另一条实例：不接管、不清记录、不发信号"
  prev=""
fi
if [ -n "$prev" ]; then
  if alive "$prev" && is_uivproc "$prev"; then
    already_running "$prev" "pid_record"
  fi
  if alive "$prev"; then
    warn "PID $prev 存活但**身份不符**（不是 ${UI_MODULE}）→ 不动它，清理陈旧记录"
    printf '[%s] STALE_PID_RECOVERED pid=%s reason=identity_mismatch\n' "$(ts)" "$prev"
  else
    printf '[%s] STALE_PID_RECOVERED pid=%s reason=process_dead\n' "$(ts)" "$prev"
  fi
  clear_pid
fi

if port_listening "$port"; then
  holder="$(port_pid "$port")"
  if [ -n "$holder" ] && is_uivproc "$holder"; then
    write_pid "$holder"
    already_running "$holder" "port_listener"
  fi
  die "端口 $port 已被占用且**不是**我们的 UI（holder=${holder:-unknown}）—— 未做任何 kill；请先处理该进程"
fi

# ══ §25 ① verify runtime
say "== ① verify runtime"
msg="$(preflight_runtime)" || die "RUNTIME_VERIFY_FAILED（不启动）：$msg"
ok "RUNTIME $msg"

# ══ §25 ② core freeze 校验（不过则不启动）
say "== ② core freeze 校验"
msg="$(verify_core_freeze)" || die "FREEZE_VERIFY_FAILED（不启动）：$msg"
ok "FREEZE PASS $msg"

# ══ §25 ③ freeze lineage 校验（不过则不启动）
say "== ③ freeze lineage 校验"
msg="$(verify_freeze_lineage)" || die "LINEAGE_VERIFY_FAILED（不启动）：$msg"
ok "LINEAGE PASS $msg"

# ══ §25 ④ MCP 前置（不预启动第二个实例）
say "== ④ MCP 前置校验"
msg="$(preflight_mcp)" || die "MCP_PREFLIGHT_FAILED（不启动）：$msg"
ok "MCP PREFLIGHT $msg"

# ══ §25 ⑤ Workspace server
say "== ⑤ Workspace server 启动"
LOG="$(log_file)"
say "START 启动 UI：$PY -m $UI_MODULE --port ${port}（cwd=${REPO}）"
PYTHONPATH="$REPO" nohup "$PY" -u -m "$UI_MODULE" --port "$port" >> "$LOG" 2>&1 &
uipid=$!
write_pid "$uipid"
say "UI pid=$uipid log=$LOG"

ready=0
i=0
while [ "$i" -lt 60 ]; do
  if ! alive "$uipid"; then
    warn "UI 进程启动后即退出；日志尾部："
    tail -n 15 "$LOG" 2>/dev/null || true
    clear_pid
    die "START_FAILED（UI 未存活）"
  fi
  if [ "$(http_code /api/status)" = "200" ] && port_listening "$port"; then
    ready=1; break
  fi
  i=$((i + 1)); sleep 0.5
done
[ "$ready" = "1" ] || { warn "30s 内未就绪；日志尾部："; tail -n 15 "$LOG" 2>/dev/null || true; die "START_FAILED（未就绪）"; }

# ══ §25 ⑥ health
say "== ⑥ health"
status_json="$(http_json /api/status 2>/dev/null || true)"
code="$(http_code /api/status 2>/dev/null || echo 0)"
core_state="$(printf '%s' "$status_json" | status_layer core)"
ok "HEALTH code=$code core=$core_state"
[ "$code" = "200" ] || die "START_DEGRADED（服务在跑但 health code=${code}；请运行 Check）"

mcp_n=0; i=0
while [ "$i" -lt 20 ]; do
  mcp_n="$(count_mcp_children_of "$uipid")"
  [ -n "$mcp_n" ] && [ "$mcp_n" -ge 1 ] && break
  i=$((i + 1)); sleep 0.5
done
if [ "$mcp_n" = "1" ]; then
  ok "MCP child=1（恰好 1 个，未多起）"
else
  warn "MCP child=${mcp_n}（期望恰好 1 个）"
fi
summary_processes "$uipid"
[ "$core_state" = "READY" ] || { warn "core 层非 READY（core=${core_state}）→ 服务在跑但降级，请运行 Check"; exit 1; }

ok "STARTED url=$URL pid=$uipid"

# ══ §25 ⑦ default browser
say "== ⑦ default browser"
open_browser
exit 0
