#!/usr/bin/env bash
# check_lacan_os.sh — 体检（**只读**：绝不 kill、绝不写核心/语料、绝不打印任何密钥或环境变量值）
#
# §38 先输出规范块（9 行：Core / Freeze / MCP / Corpus / Workspace / Explorer /
#      Bibliography / Obsidian / Provider）；缺一层报 UNAVAILABLE；
#      Freeze = core freeze 校验 + freeze lineage 校验（PASS/FAIL）；
#      Bibliography 行带客观 count（不输出任何"完整度百分比"）。
# 退出码：核心层 READY 且 UI 在跑 → 0；否则非 0。
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
cd "$REPO" || exit 1
# shellcheck source=/dev/null
. "$HERE/lib.sh"

TAILN="${LACAN_CHECK_TAIL:-12}"
pid="$(read_pid)"
ui_alive=no; ui_ours=no
if [ -n "$pid" ] && alive "$pid"; then
  ui_alive=yes
  is_uivproc "$pid" && ui_ours=yes
fi
mcp_pids="$(our_mcppids | tr '\n' ' ' | sed 's/ *$//' || true)"
inst_pid="$(port_ui_pid)"; [ -n "$inst_pid" ] || inst_pid="$pid"
inst_mcp=""
if [ -n "$inst_pid" ]; then inst_mcp="$(mcp_children_of "$inst_pid" | tr '\n' ' ' | sed 's/ *$//')"; fi
port_holder="$(port_pid "$port" 2>/dev/null || true)"
if port_listening "$port"; then listening=yes; else listening=no; fi

# ── HTTP 只读探测：状态码与响应体分开取（早先把"赋值成功"当成 code=0，会误报）
st_code="$(http_code /api/status 2>/dev/null || echo 0)"
bib_code="$(http_code /api/explore/bibliography_health 2>/dev/null || echo 0)"
status_json="$(http_json /api/status 2>/dev/null || true)"
bib_json="$(http_json /api/explore/bibliography_health 2>/dev/null || true)"

# ── 冻结校验（只读：core_freeze.py --verify 与 freeze_lineage.py --verify 都不写盘）
freeze_msg="$(verify_core_freeze 2>&1)"; freeze_rc=$?
lineage_msg="$(verify_freeze_lineage 2>&1)"; lineage_rc=$?
if [ "$freeze_rc" = 0 ] && [ "$lineage_rc" = 0 ]; then freeze_verdict=PASS; else freeze_verdict=FAIL; fi

# ── 只提取白名单字段。python 逐行打印 "KEY<TAB>VALUE"，
#    bash 用 while read 逐行收（早先用多行 heredoc + read 只吃到第一行，字段整体错位）。
fields="$("$(python_bin)" - "$status_json" <<'PY'
import json, sys

def flat(x):
    return str(x).replace("\t", " ").replace("\r", " ").replace("\n", " ")

try:
    d = json.loads(sys.argv[1] or "{}")
except Exception:
    d = {}
if not isinstance(d, dict):
    d = {}
lay = d.get("layers")
lay = lay if isinstance(lay, dict) else {}
order = ["core", "mcp", "corpus", "workspace", "explorer", "obsidian",
         "bibliography", "provider"]
state = {k: (flat(lay.get(k)) if k in lay else "UNAVAILABLE") for k in order}
print("LAYERS\t" + " ".join("%s=%s" % (k, state[k]) for k in order))
print("LAYERS_PRESENT\t%d" % sum(1 for k in order if k in lay))
print("LAYERS_READY\t%d" % sum(1 for k in order if lay.get(k) == "READY"))
for k in order:
    print("L_%s\t%s" % (k.upper(), state[k]))
prov = d.get("provider")
prov = prov if isinstance(prov, dict) else {}
print("PROVIDER_STATE\t" + flat(prov.get("state", "UNAVAILABLE")))
print("FREEZE_OK\t" + flat(d.get("core_freeze_verified", "UNAVAILABLE")))
print("MCP_CONN\t" + flat(d.get("mcp_connected", "UNAVAILABLE")))
print("RESEARCH_DISABLED\t" + flat(d.get("research_disabled", "UNAVAILABLE")))
deg = d.get("degraded")
deg = deg if isinstance(deg, list) else []
print("DEGRADED\t" + (",".join(flat(x) for x in deg) if deg else "-"))
PY
)"

layers="-"; layers_present=0; layers_ready=0
ly_core=UNAVAILABLE; ly_mcp=UNAVAILABLE; ly_corpus=UNAVAILABLE; ly_workspace=UNAVAILABLE
ly_explorer=UNAVAILABLE; ly_obsidian=UNAVAILABLE; ly_bibliography=UNAVAILABLE; ly_provider=UNAVAILABLE
provider_state="UNAVAILABLE"; freeze_ok="UNAVAILABLE"; mcp_conn="UNAVAILABLE"
research_disabled="UNAVAILABLE"; degraded="-"
while IFS="$(printf '\t')" read -r k v; do
  case "$k" in
    LAYERS)            layers="$v" ;;
    LAYERS_PRESENT)    layers_present="$v" ;;
    LAYERS_READY)      layers_ready="$v" ;;
    L_CORE)            ly_core="$v" ;;
    L_MCP)             ly_mcp="$v" ;;
    L_CORPUS)          ly_corpus="$v" ;;
    L_WORKSPACE)       ly_workspace="$v" ;;
    L_EXPLORER)        ly_explorer="$v" ;;
    L_OBSIDIAN)        ly_obsidian="$v" ;;
    L_BIBLIOGRAPHY)    ly_bibliography="$v" ;;
    L_PROVIDER)        ly_provider="$v" ;;
    PROVIDER_STATE)    provider_state="$v" ;;
    FREEZE_OK)         freeze_ok="$v" ;;
    MCP_CONN)          mcp_conn="$v" ;;
    RESEARCH_DISABLED) research_disabled="$v" ;;
    DEGRADED)          degraded="$v" ;;
  esac
done <<EOF
$fields
EOF

# ── 书目客观计数（优先 bibliography_health，退回 /api/status 内的 registry 快照）
bib_fields="$("$(python_bin)" - "$bib_json" "$status_json" <<'PY'
import json, sys

def load(s):
    try:
        d = json.loads(s or "{}")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}

b = load(sys.argv[1])
s = load(sys.argv[2])
src = b if b else (s.get("bibliography_registry") or {})
if not isinstance(src, dict):
    src = {}
keys = ("registry", "items", "reviewed", "candidates", "editions", "works")
def g(k):
    v = src.get(k)
    return "-" if v is None else str(v).replace("\t", " ").replace("\n", " ")
missing = [k for k in keys if src.get(k) is None]
print("BIB_LINE\t" + " ".join("%s=%s" % (k, g(k)) for k in keys))
print("BIB_COUNTS\t" + " ".join("%s=%s" % (k, g(k)) for k in keys if k != "registry"))
if missing:
    print("BIB_MISSING\t" + ",".join(missing))
PY
)"
bib_line=""; bib_counts=""; bib_missing=""
while IFS="$(printf '\t')" read -r k v; do
  case "$k" in
    BIB_LINE)    bib_line="$v" ;;
    BIB_COUNTS)  bib_counts="$v" ;;
    BIB_MISSING) bib_missing="$v" ;;
  esac
done <<EOF
$bib_fields
EOF

# ── 运行状态（只看**本实例**：记录 PID / 我们端口 / 本实例的 MCP 子进程；
#    仓库全量里并发会话的进程不影响这里的判定，只在详情里诊断展示）
if [ "$ui_ours" = yes ] && [ "$listening" = yes ] && [ "$st_code" = "200" ]; then
  run_state="RUNNING"
elif [ "$listening" = no ] && [ "$ui_alive" = no ] && [ -z "$inst_mcp" ]; then
  run_state="NOT_RUNNING"
else
  run_state="PARTIAL"
fi

# ══ §38 规范块（9 行）
printf 'Lacan Knowledge OS\n\n'
printf '%-14s%s\n' "Core" "$ly_core"
printf '%-14s%s\n' "Freeze" "$freeze_verdict"
printf '%-14s%s\n' "MCP" "$ly_mcp"
printf '%-14s%s\n' "Corpus" "$ly_corpus"
printf '%-14s%s\n' "Workspace" "$ly_workspace"
printf '%-14s%s\n' "Explorer" "$ly_explorer"
printf '%-14s%s   %s\n' "Bibliography" "$ly_bibliography" "${bib_counts:-（无计数）}"
printf '%-14s%s\n' "Obsidian" "$ly_obsidian"
printf '%-14s%s\n' "Provider" "$ly_provider"

# ══ 详情（只打印白名单字段，不含任何密钥/环境变量）
echo
echo "—— 详情（$(ts)）——"
echo "  repo            : $REPO"
echo "  url             : http://${host}:${port}/"
echo "  status          : $run_state"
echo "  ui pid          : ${pid:-none}  alive=$ui_alive  identity_ok=$ui_ours"
echo "  mcp child(ren)  : ${inst_mcp:-none}（本实例：${inst_pid:-none} 的子进程）"
echo "  mcp (repo-wide) : ${mcp_pids:-none}（同仓库全量，可能含并发会话）"
echo "  port listening  : $listening  holder=${port_holder:-none}"
echo "  http /api/status: code=$st_code"
echo "  http bibliography_health: code=$bib_code  $bib_line"
echo "  core freeze verify  : rc=$freeze_rc  $freeze_msg"
echo "  freeze lineage verify: rc=$lineage_rc  $lineage_msg"
echo "  core_freeze_verified : $freeze_ok"
echo "  mcp_connected        : $mcp_conn"
echo "  research_disabled    : $research_disabled"
echo "  provider             : $provider_state"
echo "  degraded layers      : $degraded"
[ -n "$bib_missing" ] && echo "  bibliography missing : $bib_missing"
echo "  layers ($layers_ready/$layers_present READY):"
for kv in $layers; do echo "    - $kv"; done
echo "  recent log lines ($TAILN):"
tail -n "$TAILN" "$(log_file)" 2>/dev/null | sed 's/^/    | /' || echo "    | (no log yet)"

rc=0
[ "$listening" = yes ] || rc=1
[ "$ui_ours" = yes ] || rc=1
[ "$ly_core" = READY ] || rc=1
if [ "$run_state" = NOT_RUNNING ]; then
  echo "  verdict         : NOT_RUNNING (exit=$rc)"
elif [ "$rc" = 0 ]; then
  echo "  verdict         : HEALTHY (exit=$rc)"
else
  echo "  verdict         : NOT_HEALTHY (exit=$rc)"
fi
exit "$rc"
