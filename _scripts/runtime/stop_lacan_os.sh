#!/usr/bin/env bash
# stop_lacan_os.sh — 停止 Lacan Knowledge OS（幂等；只杀身份通过的记录 PID + 其 MCP 子进程）
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=/dev/null
. "$HERE/lib.sh"

ensure_runtime_dirs
pid="$(read_pid)"

if [ -z "$pid" ]; then
  ok "NOT_RUNNING（无 PID 记录）"
  # 仍然验证：端口是否被我们之外的东西占用（只报告，不动）
  if port_listening "$port"; then
    warn "端口 $port 仍在监听（holder=$(port_pid "$port" 2>/dev/null || echo unknown)）—— 未做任何 kill"
  fi
  summary_processes
  exit 0
fi

if ! alive "$pid"; then
  printf '[%s] STALE_PID_RECOVERED pid=%s reason=process_dead（stop）\n' "$(ts)" "$pid"
  clear_pid
  ok "NOT_RUNNING（陈旧记录已清理）"
  summary_processes
  exit 0
fi

if ! is_uivproc "$pid"; then
  warn "SKIPPED pid=$pid 身份不符（不是 ${UI_MODULE}）—— **未发送任何信号**"
  cmd="$(proc_cmd "$pid")"
  [ -n "$cmd" ] && warn "  该 PID 实际命令：$(printf '%s' "$cmd" | cut -c1-140)"
  clear_pid
  summary_processes
  exit 0
fi

# ── 记录若属于**另一条实例**（在监听别的端口）：只报告，绝不发信号，保留记录
if pid_owns_other_port "$pid"; then
  warn "SKIPPED pid=$pid 在监听别的端口（$(pid_ports "$pid")）→ 属于另一条实例：**未发送任何信号**，记录保留"
  summary_processes
  exit 0
fi

# ── 先记下属于这个 UI 的 MCP 子进程（UI 退出后它们可能变孤儿）
kids="$(mcp_children_of "$pid" | tr '\n' ' ')"
say "STOP UI pid=${pid}（MCP 子进程：${kids:-none}）"

kill -TERM "$pid" 2>/dev/null || true
n=0
while [ "$n" -lt 20 ] && alive "$pid"; do sleep 0.5; n=$((n + 1)); done
if alive "$pid"; then
  warn "TERM 后 10s 仍未退出 → 使用 KILL"
  kill -9 "$pid" 2>/dev/null || true
  sleep 1
fi

# ── 收尾：孤儿 MCP（仅限身份通过者）
for k in $kids; do
  if alive "$k" && is_mcp_proc "$k"; then
    kill -TERM "$k" 2>/dev/null || true
    m=0
    while [ "$m" -lt 10 ] && alive "$k"; do sleep 0.5; m=$((m + 1)); done
    alive "$k" && kill -9 "$k" 2>/dev/null || true
  fi
done
# ── 收尾：只收**本实例**的 MCP —— 即上面记录下来的、那个 UI 的子进程。
#    绝不做"仓库全量清扫"：同一仓库里可能有别的会话的实例在跑，那些不是我们的。
survivors=0
for k in $(our_mcppids); do survivors=$((survivors + 1)); done
if [ "$survivors" != "0" ]; then
  warn "收尾后仓库内仍有 ${survivors} 个身份通过的 MCP 进程（可能属于并发会话的实例）→ **不动它们**"
fi
for k in $kids; do
  if alive "$k"; then
    warn "本实例 MCP $k 在 KILL 后仍存活 → 再试一次"
    kill -9 "$k" 2>/dev/null || true
  fi
done
sleep 1

clear_pid
if port_listening "$port"; then
  warn "端口 $port 仍未释放（holder=$(port_pid "$port" 2>/dev/null || echo unknown)）"
else
  ok "端口 $port 已释放"
fi
ok "STOPPED pid=$pid"
summary_processes
exit 0
