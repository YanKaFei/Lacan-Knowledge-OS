#!/usr/bin/env bash
# selftest_runtime.sh — Batch 3 自测：start → start(幂等) → check → stop → check → stop(幂等)
#
# 纪律：
#   * 前置清理与收尾**只碰我们自己这条实例**（记录 PID / 我们端口上的监听者 + 它们的
#     MCP 子进程），不碰别的会话在同一仓库里跑的进程（§27：只按身份发信号）。
#   * 计数分两套：**端口作用域**（本实例，断言用它）与**仓库全量**（诊断用）。
#   * 结束前必须 leftover_processes == []（本实例遗留）。
#
# 并发会话干扰：同一仓库里别的会话可能也在 3090 上起实例（共享 `ui.pid`，无法从进程
# 身份上区分）。本脚本因此：
#   ① 每次尝试前等一个「安静窗口」（端口空闲，有界）；
#   ② 一步到底后做**干扰判定**（步骤 1 未真正 spawn / 停止后记录被人重写 / 幂等停止
#      没看到 NOT_RUNNING / 有遗留）；被判为干扰的尝试整轮重来；
#   ③ 证据里如实记 attempt 次数与 interference 标志。
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=/dev/null
. "$HERE/lib.sh"

export LACAN_NO_OPEN=1
STAMP="$(date +%Y%m%dT%H%M%S)"
OUT_JSON="$RUNTIME_DIR/runtime_selftest_${STAMP}.json"
OUT_MD="$RUNTIME_DIR/runtime_selftest_${STAMP}.md"
ATTEMPTS_MAX="${LACAN_SELFTEST_ATTEMPTS:-5}"
QUIET_WAIT_MAX="${LACAN_SELFTEST_QUIET_WAIT:-90}"
ensure_runtime_dirs

snap() {  # $1 = step name → JSON 片段写入 $TMP/$1.json
  local step="$1" ui_all mcp_all port_ui pid owner mcp_children listening
  ui_all="$(count_uipids)"; mcp_all="$(count_mcppids)"
  port_ui="$(count_port_ui)"
  pid="$(read_pid)"
  owner="$(port_ui_pid)"
  [ -n "$owner" ] || owner="$pid"
  mcp_children=0
  if [ -n "$owner" ]; then mcp_children="$(count_mcp_children_of "$owner")"; fi
  if port_listening "$port"; then listening=yes; else listening=no; fi
  "$(python_bin)" - "$step" "$TMP" "$ui_all" "$mcp_all" "$port_ui" "$mcp_children" \
     "$pid" "$listening" "$owner" >/dev/null 2>&1 <<'PY' || true
import json, os, sys
step, tmp, ui_all, mcp_all, port_ui, kids, pid, listening, owner = sys.argv[1:10]
json.dump({"step": step,
           "ui_processes_repo_wide": int(ui_all or 0),
           "mcp_processes_repo_wide": int(mcp_all or 0),
           "port_ui_count": int(port_ui or 0),
           "mcp_children_of_instance": int(kids or 0),
           "instance_pid": (owner or None),
           "pid_file": (pid or None),
           "port_listening": listening},
          open(os.path.join(tmp, step + ".json"), "w"), ensure_ascii=False, indent=1)
PY
}

run() {  # $1 = step name; 其余 = 命令 → 记录 stdout/exit
  local step="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  printf '%s' "$out" > "$TMP/${step}.out"
  printf '%s' "$rc" > "$TMP/${step}.rc"
  snap "$step"
  return 0
}

wait_quiet_window() {  # 等到端口空闲（有界）
  local waited=0
  while port_listening "$port"; do
    if [ "$waited" -ge "$QUIET_WAIT_MAX" ]; then
      say "   等待安静窗口超时（${waited}s）：端口 ${port} 仍被占用"
      return 1
    fi
    sleep 3; waited=$((waited + 3))
  done
  say "   安静窗口：端口 ${port} 空闲（等待 ${waited}s）"
  return 0
}

pre_clean() {  # 只处理"我们自己这条实例"，并把 pre_* 写成全局
  rec="$(read_pid)"
  rec_foreign=0
  if [ -n "$rec" ] && pid_owns_other_port "$rec"; then
    warn "记录 PID ${rec} 在监听别的端口（$(pid_ports "$rec")）→ 属于另一条实例：不接管、不清理、不删记录"
    rec_foreign=1; rec=""
  fi
  pre_targets=""
  if [ -n "$rec" ] && is_uivproc "$rec"; then
    pre_targets="$rec $(mcp_children_of "$rec" | tr '\n' ' ')"
  fi
  ph="$(port_ui_pid)"
  if [ -n "$ph" ] && [ "$ph" != "${rec:-}" ]; then
    warn "端口 ${port} 的监听者 ${ph} 不是记录中的 PID（${rec:-none}）→ 按本实例处理"
    pre_targets="$pre_targets $ph $(mcp_children_of "$ph" | tr '\n' ' ')"
  fi
  pre_targets="$(printf '%s' "$pre_targets" | tr ' ' '\n' | grep . | sort -u | tr '\n' ' ' | sed 's/ *$//')"
  if [ -n "$pre_targets" ]; then
    for p in $pre_targets; do
      say "   TERM $p  cmd=$(proc_cmd "$p" | cut -c1-70)"
      kill -TERM "$p" 2>/dev/null || true
    done
    i=0
    while [ "$i" -lt 20 ]; do
      left=0
      for p in $pre_targets; do alive "$p" && left=1; done
      [ "$left" = "0" ] && break
      i=$((i + 1)); sleep 0.5
    done
    for p in $pre_targets; do
      if alive "$p"; then say "   10s 未退出 → KILL $p（身份已校验）"; kill -9 "$p" 2>/dev/null || true; fi
    done
    sleep 0.5
  fi
  [ "$rec_foreign" = "0" ] && rm -f "$PID_FILE"
  pre_ui="$(count_uipids)"; pre_mcp="$(count_mcppids)"; pre_port="$(count_port_ui)"
  say "前置：本实例 ui=${pre_port}（必须 0）；仓库全量 ui=${pre_ui} mcp=${pre_mcp}（含并发会话，仅诊断）"
}

run_steps() {
  say "== 1/6 start（§25 顺序：runtime → freeze → lineage → MCP → server → health → browser）"
  run step1_start env LACAN_NO_OPEN=1 bash "$HERE/start_lacan_os.sh"
  ui_after_start="$(read_pid)"
  say "   exit=$(cat "$TMP/step1_start.rc") ui_pid=${ui_after_start:-none}"

  say "== 2/6 start（§26 幂等：不得起第二套 MCP/server；LACAN_OPEN_CMD=/bin/echo 证明会自动打开浏览器）"
  run step2_start_again env -u LACAN_NO_OPEN LACAN_OPEN_CMD=/bin/echo bash "$HERE/start_lacan_os.sh"
  ui_after_second="$(read_pid)"
  say "   exit=$(cat "$TMP/step2_start_again.rc") ui_pid=${ui_after_second:-none}"

  say "== 3/6 check（§38 规范块）"
  run step3_check bash "$HERE/check_lacan_os.sh"
  say "   exit=$(cat "$TMP/step3_check.rc")"

  say "== 4/6 stop"
  run step4_stop bash "$HERE/stop_lacan_os.sh"
  say "   exit=$(cat "$TMP/step4_stop.rc")"

  say "== 5/6 check（应 NOT_RUNNING / 非 0）"
  run step5_check_after_stop bash "$HERE/check_lacan_os.sh"
  say "   exit=$(cat "$TMP/step5_check_after_stop.rc")"

  say "== 6/6 stop（幂等，应 0）"
  run step6_stop_again bash "$HERE/stop_lacan_os.sh"
  say "   exit=$(cat "$TMP/step6_stop_again.rc")"
}

collect_end_state() {  # 本实例遗留 + 仓库全量残留
  sleep 1
  our_final="$(read_pid)"
  leftover=""
  if [ -n "$our_final" ] && alive "$our_final"; then leftover="$leftover $our_final"; fi
  if [ "$(count_port_ui)" != "0" ]; then leftover="$leftover $(port_ui_pid)"; fi
  leftover="$(printf '%s' "$leftover" | tr ' ' '\n' | grep . | sort -u | tr '\n' ' ' | sed 's/ *$//')"
  repo_ui_after="$(count_uipids)"; repo_mcp_after="$(count_mcppids)"
}

attempts_log=""
attempt=0
interference=1
while :; do
  attempt=$((attempt + 1))
  say "═══ attempt ${attempt}/${ATTEMPTS_MAX} ═══"
  TMP="$(mktemp -d)"
  say "== 前置清理（只碰本实例：记录 PID + 本端口的监听者 + 它们的 MCP 子进程）"
  pre_clean
  wait_quiet_window || true
  run_steps
  collect_end_state
  # ── 干扰判定（并发会话在 3090 上起实例的三种签名）
  interference=0
  case "$(cat "$TMP/step1_start.out")" in
    *"⑤ Workspace server"*) ;;
    *) interference=1 ;;
  esac
  if grep -q '"pid_file": *"[0-9]' "$TMP/step5_check_after_stop.json" 2>/dev/null; then interference=1; fi
  case "$(cat "$TMP/step6_stop_again.out")" in
    *"无 PID 记录"*) ;;
    *) interference=1 ;;
  esac
  [ -n "$leftover" ] && interference=1
  attempts_log="${attempts_log}${attempt}:interference=${interference} "
  if [ "$interference" = "0" ]; then
    say "attempt ${attempt} 判定：无干扰 ✓"
    break
  fi
  if [ "$attempt" -ge "$ATTEMPTS_MAX" ]; then
    warn "attempt ${attempt} 仍有并发会话干扰（已达上限 ${ATTEMPTS_MAX}）→ 按当前结果出具证据"
    break
  fi
  warn "INTERFERENCE_DETECTED（attempt ${attempt}）→ 清理本实例后整轮重试"
  say "   前置清理（重试前）"
  pre_clean
  rm -rf "$TMP"
done

# ── 组装证据（用最后一轮 attempt 的 $TMP）
python3 - "$TMP" "$OUT_JSON" "$OUT_MD" "$STAMP" "$REPO" "$port" \
  "$pre_port" "$pre_ui" "$pre_mcp" "$ui_after_start" "$ui_after_second" "$leftover" \
  "$repo_ui_after" "$repo_mcp_after" "$pre_targets" "$attempt" "$interference" "$attempts_log" \
  "$ATTEMPTS_MAX" <<'PY'
import json, os, re, sys
(tmp, out_json, out_md, stamp, repo, port, pre_port, pre_ui, pre_mcp, p1, p2,
 leftover, repo_ui_after, repo_mcp_after, pre_targets, attempt, interference,
 attempts_log, attempts_max) = sys.argv[1:20]

def rd(n):
    p = os.path.join(tmp, n)
    return open(p, encoding="utf-8", errors="replace").read() if os.path.isfile(p) else ""

NAMES = ("step1_start", "step2_start_again", "step3_check", "step4_stop",
         "step5_check_after_stop", "step6_stop_again")
COMMANDS = {
    "step1_start": "LACAN_NO_OPEN=1 bash _scripts/runtime/start_lacan_os.sh",
    "step2_start_again": "LACAN_OPEN_CMD=/bin/echo bash _scripts/runtime/start_lacan_os.sh",
    "step3_check": "bash _scripts/runtime/check_lacan_os.sh",
    "step4_stop": "bash _scripts/runtime/stop_lacan_os.sh",
    "step5_check_after_stop": "bash _scripts/runtime/check_lacan_os.sh",
    "step6_stop_again": "bash _scripts/runtime/stop_lacan_os.sh",
}
full = {n: rd(n + ".out") for n in NAMES}
steps = []
for name in NAMES:
    try:
        meta = json.load(open(os.path.join(tmp, name + ".json"), encoding="utf-8"))
    except Exception:
        meta = {}
    meta["command"] = COMMANDS[name]
    try:
        meta["exit_code"] = int(rd(name + ".rc").strip() or "0")
    except Exception:
        meta["exit_code"] = None
    meta["stdout"] = full[name]
    steps.append(meta)
s1, s2, s3, s5, s6 = (full["step1_start"], full["step2_start_again"],
                      full["step3_check"], full["step5_check_after_stop"],
                      full["step6_stop_again"])
lo = [x for x in leftover.split() if x]

STAGES = ["① verify runtime", "② core freeze", "③ freeze lineage", "④ MCP 前置",
          "⑤ Workspace server", "⑥ health", "⑦ default browser"]
idx = [s1.find(m) for m in STAGES]
BLOCK = ["Core", "Freeze", "MCP", "Corpus", "Workspace", "Explorer",
         "Bibliography", "Obsidian", "Provider"]
block_states = {}
for nm in BLOCK:
    m = re.search(r"(?m)^%s\s+(READY|UNAVAILABLE|PASS|FAIL)\b" % re.escape(nm), s3)
    block_states[nm] = m.group(1) if m else None
bib_line = re.search(r"(?m)^Bibliography\s+\S+(.*)$", s3)
bib_counts = (bib_line.group(1) if bib_line else "").strip()

log_path = os.path.join(repo, "_workspace", "runtime", "logs", "ui-%s.log" % stamp[:8])
try:
    log_text = open(log_path, encoding="utf-8", errors="replace").read()
except Exception:
    log_text = ""

secret_vals = [v for k, v in os.environ.items()
               if any(t in k.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and len(v) >= 8]
leaked = sorted({v[:6] + "..." for v in secret_vals for out in full.values() if v in out})

def scoped(i, key):
    return steps[i].get(key)

base = "http://127.0.0.1:%s/" % port

assertions = {
    "no_interference": interference == "0",
    "pre_state_clean": int(pre_port or 0) == 0,
    "start_stage_order_ok": all(i >= 0 for i in idx) and idx == sorted(idx),
    "start_freeze_and_lineage_pass": "FREEZE PASS" in s1 and "LINEAGE PASS" in s1,
    "no_open_skip_respected": ("browser_open skipped url=%s" % base) in s1
                              and "reason=LACAN_NO_OPEN" in s1,
    "browser_open_executed_with_echo": ("browser_open url=%s" % base) in s2
                                       and "cmd=/bin/echo" in s2,
    "browser_open_logged_in_runtime_log": ("browser_open url=%s cmd=/bin/echo" % base) in log_text,
    "after_first_start_ui_eq_1": scoped(0, "port_ui_count") == 1,
    "after_first_start_mcp_children_eq_1": scoped(0, "mcp_children_of_instance") == 1,
    "double_start_same_ui_pid": p1 == p2 and bool(p1),
    "after_double_start_ui_eq_1": scoped(1, "port_ui_count") == 1,
    "after_double_start_mcp_children_eq_1": scoped(1, "mcp_children_of_instance") == 1,
    "double_start_no_spawn_and_exit_0": steps[1].get("exit_code") == 0
                                        and "ALREADY_RUNNING" in s2 and "未 spawn 任何进程" in s2,
    "check_healthy_exit_0": steps[2].get("exit_code") == 0,
    "check_block_9_lines_present": all(v is not None for v in block_states.values()),
    "check_all_layers_ready": all(block_states[k] == "READY" for k in BLOCK if k != "Freeze")
                              and block_states["Freeze"] == "PASS",
    "check_bib_counts_present": all(t in bib_counts for t in
                                    ("items=", "reviewed=", "candidates=", "editions=", "works=")),
    "check_no_completeness_percentage": "%" not in s3,
    "check_no_secret_leak": leaked == [],
    "stop_exit_0": steps[3].get("exit_code") == 0,
    "after_stop_ui_eq_0": scoped(3, "port_ui_count") == 0,
    "after_stop_mcp_children_eq_0": scoped(3, "mcp_children_of_instance") == 0,
    "check_after_stop_nonzero": steps[4].get("exit_code") != 0,
    "check_after_stop_not_running": "NOT_RUNNING" in s5,
    "check_after_stop_layers_unavailable": bool(re.search(r"(?m)^Core\s+UNAVAILABLE\b", s5)),
    "second_stop_idempotent_exit_0": steps[5].get("exit_code") == 0 and "NOT_RUNNING" in s6,
    "leftover_processes_empty": lo == [],
    "port_released": steps[5].get("port_listening") == "no",
}
rec = {"schema_version": "runtime-selftest/v1", "stamp": stamp, "repo": repo,
       "port": int(port or 0), "LACAN_NO_OPEN": "1", "python_bin": "python3",
       "attempt": int(attempt or 0), "attempts_max": int(attempts_max or 0),
       "attempts_log": attempts_log.strip(), "interference": interference == "0",
       "scope_note": "断言用『端口作用域』计数（本实例）；repo_wide_* 为诊断值，"
                     "同一仓库里并发会话的进程会体现在其中，本脚本不会处理它们。",
       "pre_state": {"instance_ui": int(pre_port or 0),
                     "repo_wide_ui": int(pre_ui or 0), "repo_wide_mcp": int(pre_mcp or 0)},
       "pre_clean_targets": [x for x in pre_targets.split() if x],
       "repo_wide_after": {"ui": int(repo_ui_after or 0), "mcp": int(repo_mcp_after or 0)},
       "steps": steps, "ui_pid_first": p1 or None, "ui_pid_second": p2 or None,
       "check_block_states": block_states, "check_bib_counts": bib_counts,
       "runtime_log": log_path, "secret_leak_probe": leaked,
       "leftover_processes": lo, "assertions": assertions,
       "passed": all(assertions.values())}
json.dump(rec, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

L = ["# Runtime self-test — Batch 3（一键启动/停止/体检）", "",
     "```text", "stamp = %s" % stamp, "repo  = %s" % repo, "port  = %s" % port,
     "LACAN_NO_OPEN = 1", "passed = %s" % rec["passed"],
     "passed_assertions = %d/%d" % (sum(1 for v in assertions.values() if v), len(assertions)),
     "attempt = %s/%s（attempts_log: %s）" % (attempt, attempts_max, attempts_log.strip()),
     "interference = %s" % (interference == "0"),
     "```", "",
     "计数口径：`port_ui_count` / `mcp_children_of_instance` 是**本实例**（断言用）；",
     "`*_repo_wide` 是同一仓库里的全量（诊断用，可能含并发会话）。", "",
     "| 步骤 | 命令 | exit | 本实例 UI | 本实例 MCP 子 | 端口 | 仓库全量 ui/mcp |",
     "|---|---|---|---|---|---|---|"]
for s in steps:
    L.append("| %s | `%s` | %s | %s | %s | %s | %s/%s |" % (
        s.get("step"), s.get("command"), s.get("exit_code"), s.get("port_ui_count"),
        s.get("mcp_children_of_instance"), s.get("port_listening"),
        s.get("ui_processes_repo_wide"), s.get("mcp_processes_repo_wide")))
L += ["", "## §38 check 规范块（从 step3 输出逐行解析）", ""]
for nm in BLOCK:
    L.append("* %s : **%s**" % (nm, block_states[nm]))
L += ["", "  Bibliography counts : `%s`" % bib_counts, "", "## 断言", ""]
for k, v in assertions.items():
    L.append("* %s : **%s**" % (k, "PASS" if v else "FAIL"))
L += ["", "## 关键观察", "",
      "* 第一次 start 后 UI pid = `%s`；第二次 start 后 pid = `%s` → %s" % (
          p1 or "-", p2 or "-",
          "未产生第二个 UI（同一 PID）" if p1 == p2 else "**PID 变化**"),
      "* `LACAN_NO_OPEN=1` 跳过语义：step1 输出含 `browser_open skipped …`（见断言）",
      "* 自动打开浏览器（`LACAN_OPEN_CMD=/bin/echo`，不真弹）：step2 输出含 `browser_open url=… cmd=/bin/echo`，"
      "且该行同时写入了运行期日志 `%s`" % log_path,
      "* 前置本实例 ui = %s（必须 0）；仓库全量 ui/mcp = %s/%s（诊断）" % (
          pre_port, pre_ui, pre_mcp),
      "* 前置清理目标（只含本实例 PID）= `%s`" % (rec["pre_clean_targets"] or []),
      "* leftover_processes = `%s`（必须为空数组）" % json.dumps(lo),
      "* 端口是否释放 = %s" % steps[5].get("port_listening"),
      "* 仓库全量残留（诊断，含并发会话）= ui %s / mcp %s" % (repo_ui_after, repo_mcp_after),
      "* 密钥泄漏探针 = `%s`（必须为空）" % json.dumps(leaked), "",
      "## 步骤输出", ""]
for s in steps:
    L += ["### %s（exit=%s，本实例 ui=%s mcp=%s）" % (
              s.get("step"), s.get("exit_code"), s.get("port_ui_count"),
              s.get("mcp_children_of_instance")),
          "", "```text", (s.get("stdout") or "").strip(), "```", ""]
open(out_md, "w", encoding="utf-8").write("\n".join(L) + "\n")
print(out_json)
print(out_md)
print("PASSED=%s" % rec["passed"])
print("assertions=%d/%d" % (sum(1 for v in assertions.values() if v), len(assertions)))
print("attempt=%s interference=%s" % (attempt, interference == "0"))
for k, v in assertions.items():
    if not v:
        print("FAILED: %s" % k)
print("leftover=%s" % json.dumps(lo))
PY
rm -rf "$TMP"
