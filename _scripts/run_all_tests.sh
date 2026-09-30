#!/usr/bin/env bash
# run_all_tests.sh — 一键跑全部契约测试
#
#   ./run_all_tests.sh            # 全部
#   ./run_all_tests.sh --quick    # 跳过真实语料重扫 + 跳过需要运行时的重活
#
# 退出码 0 表示全绿。任何一项红即非零退出，可直接用于 CI / 提交前检查。
#
# ★ 设计要点：测试文件**自动发现**（`_tests/test_*.py`），不再手写清单。
#   旧版把 9 个套件写死在脚本里，于是 Phase 3 / 3B 的 6 个测试文件
#   **一直没有被这个「一键」脚本跑到** —— 清单会漂移，自动发现不会。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TESTS="$HERE/_tests"
VAULT="$(cd "$HERE/.." && pwd)"
FAILED=0
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1
# Phase 3C §24 第 21 条要求「tests 全绿」有**可核记录**，不是一句声明。
RESULT_TSV="$(mktemp)"
trap 'rm -f "$RESULT_TSV"' EXIT

# ── 逐套件**真实耗时**落盘（Phase 5A §38）
#   为什么：`Ran N tests in X.XXXs` 只在日志里、且按套件归属不可靠；
#   验收报告要 median / p95 / top-slow，必须有**结构化**的逐套件耗时。
#   columns: <name>\t<status>\t<seconds>（与 product_acceptance.run_regression 对齐）
TIMING_TSV="${LACAN_SUITE_TIMING:-}"
if [ -n "$TIMING_TSV" ]; then
  mkdir -p "$(dirname "$TIMING_TSV")" 2>/dev/null || true
  : > "$TIMING_TSV"
fi
now_s() { python3 -c 'import time;print("%.3f" % time.time())'; }

banner() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
ok()     { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad()    { printf '  \033[31mFAIL\033[0m %s\n' "$1"; }

banner "环境自检"
python3 - <<'PY'
import sys
print(f"  python {sys.version.split()[0]}")
mods = ["pypdf", "docx", "yaml", "jsonschema", "ebooklib", "PIL", "langdetect"]
missing = []
for m in mods:
    try:
        __import__(m)
        print(f"  OK   {m}")
    except Exception:
        print(f"  MISS {m}")
        missing.append(m)
if missing:
    print(f"\n  缺依赖: {', '.join(missing)}")
    print("  安装: python3 -m pip install --user " + " ".join(missing))
PY
echo "  可选运行时："
for v in "$VAULT/.venv-embedding" "$HOME/Desktop/<WORKSPACE>/.lacan-build/reference-venv"; do
  if [ -x "$v/bin/python" ]; then ok "$v"; else
    printf '  \033[33mMISS\033[0m %s（相关测试会 skip）\n' "$v"
  fi
done

banner "1/3 inventory 引擎契约测试"
if (cd "$HERE" && python3 -m unittest test_inventory); then
  printf 'inventory\tOK\n' >> "$RESULT_TSV"
else
  printf 'inventory\tFAIL\n' >> "$RESULT_TSV"; FAILED=1
fi

# ── 2/3：自动发现 _tests/test_*.py ────────────────────────────────────────
# 「慢套件」会**整体重建**大派生物（Passage Store / 词法索引 / 完整 build）：
#   test_phase2_deterministic  —— 每个测试跑一次完整 build（实测整套约 8 分钟）
#   test_phase2_passage_store  —— 重建 Passage Store
#   test_phase3_lexical        —— 重建 249,105 条词法索引
# 完整跑一遍约 25 分钟（实测）。`--quick` 会**明确打印 SKIP**（不是静默跳过），
# 提交前请跑一次完整版。
SLOW_SUITES="test_phase2_deterministic test_phase2_passage_store test_phase3_lexical"

# ── Phase 4C.1-B §23：**测试不得修改真实仓库历史**
#    历史教训：test_phase2_deterministic 旧版会 `git add -A && git commit` 建立基线，
#    每跑一次测试就前移真实 HEAD（49b9e90 → ee0eed4 → 0bee05f → f70402e）。
#    这里在跑套件前后记录 HEAD；不同即判 FAIL（hard acceptance criterion）。
HEAD_BEFORE="$(git -C "$VAULT" rev-parse HEAD 2>/dev/null || echo none)"
export HEAD_BEFORE

banner "2/3 _tests/ 全部套件（自动发现）"
# 不用 mapfile（macOS 自带 bash 3.2 没有它）
SUITES="$(cd "$TESTS" && ls test_*.py 2>/dev/null | sed 's/\.py$//' | sort)"
SUITE_COUNT="$(printf '%s\n' "$SUITES" | grep -c . || true)"
if [ "$SUITE_COUNT" -eq 0 ]; then
  bad "没有发现任何 test_*.py"; FAILED=1
fi
for s in $SUITES; do
  if [ "$QUICK" -eq 1 ] && printf '%s\n' $SLOW_SUITES | grep -qx "$s"; then
    printf '\n\033[1m-- %s\033[0m\n' "$s"
    printf '  \033[33mSKIP\033[0m 慢套件（--quick）。跑完整版：%s\n' "./_scripts/run_all_tests.sh"
    printf '%s\tSKIP\n' "$s" >> "$RESULT_TSV"
    if [ -n "$TIMING_TSV" ]; then
      printf '%s\tSKIP\t0.000\n' "$s" >> "$TIMING_TSV"
    fi
    continue
  fi
  printf '\n\033[1m-- %s\033[0m\n' "$s"
  _t0="$(now_s)"
  if (cd "$TESTS" && python3 -m unittest "$s"); then
    printf '%s\tOK\n' "$s" >> "$RESULT_TSV"
    _st="OK"
  else
    printf '%s\tFAIL\n' "$s" >> "$RESULT_TSV"; FAILED=1
    _st="FAIL"
  fi
  if [ -n "$TIMING_TSV" ]; then
    _t1="$(now_s)"
    printf '%s\t%s\t%s\n' "$s" "$_st" \
      "$(python3 -c "print('%.3f' % (float('$_t1')-float('$_t0')))")" >> "$TIMING_TSV"
  fi
done
printf '\n  共 %s 个套件\n' "$SUITE_COUNT"

# ── §23 HEAD guard: the suite must not rewrite real repo history
#    (old test_phase2_deterministic ran `git add -A && git commit`, which moved HEAD).
HEAD_AFTER="$(git -C "$VAULT" rev-parse HEAD 2>/dev/null || echo none)"
HEAD_BEFORE="${HEAD_BEFORE:-none}"
HEAD_AFTER="${HEAD_AFTER:-none}"
if [ "$HEAD_BEFORE" = "$HEAD_AFTER" ]; then
  ok "tests did not modify real git HEAD ($HEAD_AFTER)"
  printf 'tool:%s\tOK\n' "sec23 tests did not modify real git HEAD" >> "$RESULT_TSV"
else
  bad "repo mutated by tests: HEAD $HEAD_BEFORE -> $HEAD_AFTER"
  printf 'tool:%s\tFAIL\n' "sec23 tests did not modify real git HEAD" >> "$RESULT_TSV"
  FAILED=1
fi

# ── 套件结果**中间落盘**：产物级校验里的「完成门」需要在**同一次运行内**
#    读到本轮的套件结果，而 TEST_RUN.json 要等全部校验跑完才能写。
#    没有这个中间文件，「Phase 4A.1 §10 完成门」会永远读上一轮的记录 → 假红。
python3 - "$RESULT_TSV" "$VAULT" "$QUICK" <<'PYEOF'
import json, os, sys, time
tsv, vault, quick = sys.argv[1], sys.argv[2], int(sys.argv[3])
rows = []
for line in open(tsv, encoding="utf-8"):
    name, _, status = line.rstrip("\n").partition("\t")
    if name and not name.startswith("tool:"):
        rows.append({"name": name, "status": status})
out = {"schema_version": "test-run-suites/v1",
       "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "quick_mode": bool(quick),
       "suites": len(rows),
       "failed_suites": [r["name"] for r in rows if r["status"] == "FAIL"],
       "results": rows,
       "note": ("**本次运行**的套件结果（在产物校验之前写入）。"
                "TEST_RUN.json 会在全部校验结束后再写一份完整记录。")}
p = os.path.join(vault, "_data", "index", "TEST_RUN.suites.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("  -> %s（%d 套件，failed=%s）" % (p, out["suites"],
                                        out["failed_suites"] or "[]"))
PYEOF

# ── 3/3：产物级校验（manifest / parity / 消融 / 幂等）─────────────────────
banner "3/3 产物校验 + inventory 幂等性"
if [ "$QUICK" -eq 0 ]; then
  python3 - "$HERE" "$VAULT" <<'PYEOF'
import json, subprocess, sys, os
here, vault = sys.argv[1], sys.argv[2]
p = os.path.join(vault, "_data", "corpus_inventory.json")
def norm(d):
    d = dict(d); d.pop("generated_at", None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)
before = norm(json.load(open(p, encoding="utf-8")))
r = subprocess.run([sys.executable, os.path.join(here, "inventory_corpus.py")],
                   capture_output=True, text=True)
after = norm(json.load(open(p, encoding="utf-8")))
if r.returncode != 0:
    print("  FAIL  重跑失败:", r.stderr[-300:]); sys.exit(1)
print("  OK    inventory 重跑结果一致（幂等）" if before == after
      else "  FAIL  重跑结果不同 —— 幂等性被破坏")
sys.exit(0 if before == after else 1)
PYEOF
  [ $? -ne 0 ] && FAILED=1
else
  echo "  （--quick：跳过重扫）"
fi

# 需要运行时的产物校验：缺 venv 就明确说「跳过」，不静默当通过
check_tool() {   # $1=描述  $2=python  $3=脚本  $4...=参数
  local desc="$1" py="$2" script="$3"; shift 3
  # ⚠️ `python3` 是**命令名**不是路径，`[ -x python3 ]` 会失败 →
  #    之前 12 个产物校验器全被 SKIP 成「缺 python3」，而它们其实都能跑。
  #    没有斜杠时先解析成绝对路径。
  case "$py" in
    */*) ;;
    *) py="$(command -v "$py" 2>/dev/null || echo "$py")" ;;
  esac
  if [ ! -x "$py" ]; then
    printf '  \033[33mSKIP\033[0m %s（缺 %s）\n' "$desc" "$py"
    return 0
  fi
  local _t0 _t1 _st
  _t0="$(now_s)"
  if out=$("$py" "$script" "$@" 2>&1); then
    printf '  \033[32mOK\033[0m   %s\n' "$desc"
    printf 'tool:%s\tOK\n' "$desc" >> "$RESULT_TSV"
    _st="OK"
  else
    printf '  \033[31mFAIL\033[0m %s\n%s\n' "$desc" "$(echo "$out" | tail -12)"
    printf 'tool:%s\tFAIL\n' "$desc" >> "$RESULT_TSV"
    FAILED=1
    _st="FAIL"
  fi
  if [ -n "$TIMING_TSV" ]; then
    _t1="$(now_s)"
    printf 'tool:%s\t%s\t%s\n' "$desc" "$_st" \
      "$(python3 -c "print('%.3f' % (float('$_t1')-float('$_t0')))")" >> "$TIMING_TSV"
  fi
}

check_tool "wheelhouse 逐 wheel sha256 校验" python3 "$HERE/_tools/build_wheelhouse.py" --verify
check_tool "MODEL_MANIFEST 逐文件 hash 校验" python3 "$HERE/_tools/build_model_manifest.py" --verify
check_tool "参考权重来源可追溯（ModelScope 上游）" python3 "$HERE/_tools/fetch_reference_model.py" --verify
check_tool "§11 reference parity 一致性" python3 "$HERE/_tools/check_reference_parity.py" --verify
check_tool "§9/§13 tokenizer + 运行时确定性 gate" python3 "$HERE/_tools/check_runtime_gates.py" --verify
check_tool "§14–§20 语义 benchmark + 消融" python3 "$HERE/_tools/semantic_benchmark.py" --verify
check_tool "§16 跨语言诊断" python3 "$HERE/_tools/diagnose_crosslang.py" --check
check_tool "§16 方向 C/D 补充评测（独立分母）" python3 "$HERE/_tools/evaluate_fr_directions.py" --verify
check_tool "§21 全量门禁未被绕过" python3 "$HERE/_tools/update_vector_gate.py" --verify
check_tool "§23 17 项硬门禁统一重算" python3 "$HERE/_tools/check_hard_gates.py" --verify
check_tool "§25 §1–§25 逐条可核判据" python3 "$HERE/_tools/check_objective_compliance.py" --verify
check_tool "§22 溯源候选（未晋级）" python3 "$HERE/_tools/build_concept_source_candidates.py" --verify

# ── Phase 4A §20/§21/§25/§28：MCP 访问层
check_tool "Phase 4A §21 只读硬门（canonical/索引逐字节）" python3 "$HERE/_tools/check_phase4a_readonly.py"
check_tool "Phase 4A §27 11 项硬门禁 = 0" python3 "$HERE/_tools/check_phase4a_hard_gates.py" --verify
check_tool "Phase 4A §20 MCP 契约自检（34 项）" python3 "$HERE/_tools/lacan_mcp/selftest.py"
check_tool "Phase 4A §25 契约文档与 schemas.py 同步" python3 "$HERE/_tools/render_contracts.py" --check
check_tool "Phase 4A §28 完成门（20 条）" python3 "$HERE/_tools/check_phase4a_completion.py" --verify

# ── Phase 4A.1 §1–§10：版本化本体层
check_tool "Phase 4A.1 本体层与 spec 一致（可复算）" python3 "$HERE/_tools/build_ontology_v4a1.py" --check
check_tool "Phase 4A.1 本体层校验器（0 error）" python3 "$HERE/_tools/validate_ontology_v4a1.py" --verify
check_tool "Phase 4A.1 缺口状态已应用（追加式）" python3 "$HERE/_tools/apply_ontology_v4a1_repairs.py" --check
check_tool "Phase 4A.1 回归（resolver/术语/guard/MCP/完整性）" python3 "$HERE/_tools/regress_ontology_v4a1.py" --verify
check_tool "Phase 4A.1 §10 完成门（18 条）" python3 "$HERE/_tools/check_phase4a1_completion.py" --verify

# ── Phase 4B §3–§35：研究质量层
check_tool "Phase 4B 任务集与 gold 推导一致" python3 "$HERE/_tools/build_research_tasks_v1.py" --check
check_tool "Phase 4B 预算耗尽行为（必须 hedge、不得编造）" python3 "$HERE/_tools/research_eval_4b.py" --budget-check --quiet
check_tool "Phase 4B §33 12 项硬门禁 = 0" python3 "$HERE/_tools/check_phase4b_hard_gates.py" --verify
check_tool "Phase 4B §35 完成门（24 条）" python3 "$HERE/_tools/check_phase4b_completion.py" --verify

# ── Phase 4C §27–§42：证据充分性分层与人工评审基础设施
check_tool "Phase 4C 校准集与 spec 一致" python3 "$HERE/_tools/calibrate_sufficiency_v2.py" --check
check_tool "Phase 4C 校准运行（分层判定）" python3 "$HERE/_tools/calibrate_sufficiency_v2.py" --quiet
check_tool "Phase 4C §39 + 4C.1-A 硬门禁（12 继承 + 7 新增）" python3 "$HERE/_tools/check_phase4c_hard_gates.py" --verify
check_tool "Phase 4C §42 完成门（24 条，两状态）" python3 "$HERE/_tools/check_phase4c_completion.py" --verify

# ── Phase 4C.1-A §A1–§A7：评测完整性（Evaluation Integrity Repair）
check_tool "4C.1-A §A2 trace 完整性（契约违规=0；历史不一致另册）" python3 "$HERE/_tools/check_trace_integrity.py" --verify
check_tool "4C.1-A §A3 run manifest 可复现" python3 "$HERE/_tools/build_eval_manifest.py" --verify
check_tool "4C.1-A §A3 run manifest 符合 schema" python3 "$HERE/_tools/build_eval_manifest.py" --check-schema
check_tool "4C.1-A §A4 gold lane 审计未过期" python3 "$HERE/_tools/audit_gold_lanes.py" --check
check_tool "4C.1-A §A5 裁决题 evaluation truth 与冻结输入一致" python3 "$HERE/_tools/build_adjudicated_truth.py" --check
check_tool "4C.1-A §A6/§12 回归规格可复现（14 任务）" python3 "$HERE/_tools/build_scholarly_regression_v1.py" --check
check_tool "4C.1-A §A1/§A7 评测完整性审计一致" python3 "$HERE/_tools/build_evaluation_integrity_audit.py" --check

# ── Phase 4C.1-B §B0/§19/§21/§16：研究契约 · 仓库安全 · gold_v2
check_tool "4C.1-B §12–§14 trace 完整性（含 research-trace/v2）" python3 "$HERE/_tools/check_trace_integrity.py" --verify
check_tool "4C.1-B §12–§21 研究契约编译与硬规则（14 任务 / 10 类 / 14 项）" python3 "$HERE/_tools/check_research_contracts.py" --verify
check_tool "4C.1-B §16 gold_v2 与 v1 不变式一致" python3 "$HERE/_tools/build_gold_v2.py" --check
check_tool "4C.1-B §17 人工复核 lane 清单可复算" python3 "$HERE/_tools/build_manual_review_lanes.py" --quiet
check_tool "4C.1-A §A3 run manifest 可复现（含 4C.1-B 引擎）" python3 "$HERE/_tools/build_eval_manifest.py" --verify

# ── Phase 4C.1-C §9/§27/§29：synthesis run 不可变 + Gate 20
check_tool "4C.1-C §27 run 不可变（manifest 钉住 + 指标可复算 + Gate 20=0）" python3 "$HERE/_tools/run_synthesis_4c1c.py" --check
check_tool "4C.1-C §9 Gate 20 复算（synthesis 引用/来源角色/弃权契约）" python3 "$HERE/_tools/build_evaluation_integrity_audit.py" --check

# ── Phase 4C.1-D §30/§36/§37/§43：entailment run 不可变 + Gate 21 + 校准集
check_tool "4C.1-D §37 entailment run 不可变（manifest 钉住 + 指标可复算 + Gate 21=0）" python3 "$HERE/_tools/run_synthesis_4c1d.py" --check
check_tool "4C.1-D §43 entailment 校准集可复现" python3 "$HERE/_tools/build_entailment_calibration.py" --check
check_tool "4C.1-D §36 Gate 21 复算（claim–evidence 蕴含完整性）" python3 "$HERE/_tools/build_evaluation_integrity_audit.py" --check

# ── Phase 4C.1-E §14/§28：Round 2 盲评包完整性 + 无泄漏 + 无自动评分
check_tool "4C.1-E §14 Round2 盲评包（14/14 + 钉住封存答案 + 无 Round1 泄漏）" python3 "$HERE/_tools/round2_review.py" --check
check_tool "4C.1-E §28 D2 封存 run 复验（seal/manifest/engine/prompt/14 题）" python3 "$HERE/_tools/round2_review.py" --verify-run

# ── Phase 4D.0 §2/§8：Scholarly Core Freeze + 核心变更请求协议
check_tool "4D.0 §2 scholarly core freeze 校验（39 个语义单元哈希钉住）" python3 "$HERE/_tools/core_freeze.py" --verify
check_tool "4D.0 §8 核心变更请求协议（schema/template/状态机）" python3 "$HERE/_tools/check_core_change_requests.py" --verify

# ── Phase 4D.1 §5/§17/§19/§27：MCP 契约（工具集 / 信封 / 错误 / 审计 / 冻结门）
check_tool "4D.1 §5/§27 MCP 契约自检（10 工具 + 严格 schema + fail closed + 审计 + freeze）" python3 "$HERE/_tools/check_mcp_contract.py"
check_tool "4D.1 §27 MCP server 启动与 core freeze 校验" python3 "$VAULT/mcp_server/server.py" --selftest

# ── Phase 4D.2 §3/§28/§42/§45：冻结谱系 + Workspace UI 契约
check_tool "4D.2 §3 冻结谱系（4D.0→4D.1→4D.2；核心语义变化 0）" python3 "$HERE/_tools/freeze_lineage.py" --verify
check_tool "4D.2 §28/§42 Workspace UI 契约（状态/静态资源/写入边界/无 innerHTML）" python3 "$HERE/_tools/check_workspace_ui.py"

# ── Phase 4D.3 §2/§22/§44–§46：Obsidian 集成契约（复用 vault / 工作区隔离 / 冻结不变）
check_tool "4D.3 §22/§44-46 Obsidian 集成契约（vault 复用/隔离/wikilink/冻结）" python3 "$HERE/_tools/check_obsidian_integration.py"
# ── Phase 4D.4 §42/§43/§62/§63：Explorer 契约（browse 只读 / ESM 语法 / 分页 / 冻结）
check_tool "4D.4 §42-43/§62-63 Explorer 契约（browse 只读/分层/ESM/分页/冻结）" python3 "$HERE/_tools/check_explorer.py"
# ── Phase 4D.5 §2/§33/§59/§67：Research Project 契约（USER_WORKSPACE/不进 evidence/冲突/冻结）
check_tool "4D.5 §2-3/§59/§67 Research Project 契约（工作区/无 evidence/冲突/冻结）" python3 "$HERE/_tools/check_project.py"
# ── Phase 4D.6 §5/§56/§62-63：Export & Citation 契约（四格式身份/citation 能力/bundle/freeze）
check_tool "4D.6 §5/§56/§62-63 Export & Citation 契约（四格式身份/bundle/citation/冻结）" python3 "$HERE/_tools/check_export.py"

# ── Phase 4E §18/§51/§68：CCR-0001 remediation 的工件完整性（只读；不改历史）
check_tool "4E §18/§56 冻结修复记录与自身 lineage 段快照一致（只允许产品边界组件变化）" python3 "$HERE/_tools/phase4e_freeze_record.py" --check
check_tool "4E §51 / 5A §51 Gate 未被事后改动（冻结完整性）" python3 "$HERE/_tools/phase4e_acceptance.py" --freeze-gate
check_tool "4E §68 凭据泄漏审计（运行工件内 API key / Bearer 命中 = 0）" python3 "$HERE/_tools/phase4e_secret_audit.py"

# ── Phase 5A §51/§62：presentation hardening 的工件完整性（只读）
check_tool "5A §62 冻结修复记录与自身 lineage 段快照一致（PDR-0001）" python3 "$HERE/_tools/phase5a_freeze_record.py" --check
check_tool "5A §51 Hardening Gate v2 未被事后改动（冻结完整性；H1–H18）" python3 "$HERE/_tools/phase5a_acceptance.py" --freeze-gate
check_tool "5A §20 Hardening Gate v1 历史不可变（11/14 失败记录保留）" env P5A_GATE=_data/phase5a/phase5a_hardening_gate_v1.json python3 "$HERE/_tools/phase5a_acceptance.py" --freeze-gate
check_tool "5A P5A-006 §6 语料差异审计（added=1 / 无未解释变化）" python3 "$HERE/_tools/phase5a_corpus_diff.py"
check_tool "5A P5A-006 §4 数据版本声明与冻结现状一致（依赖构件状态）" python3 "$HERE/_tools/phase5a_declare_data_version.py" --check
check_tool "5B §32 Entity Explorer Gate v1 未被事后改动（冻结完整性）" python3 "$HERE/_tools/phase5b_acceptance.py" --freeze-gate
check_tool "5C §59 Bibliography Gate v1 未被事后改动（冻结完整性）" python3 "$HERE/_tools/phase5c_acceptance.py" --freeze-gate
check_tool "5C §10/§54 书目 registry 与重建一致（确定性）" python3 "$HERE/_tools/build_bibliography_registry.py" --check
check_tool "Final Daily Use §41 Gate v1 未被事后改动（冻结完整性；F1–F18）" python3 "$HERE/_tools/daily_use_acceptance.py" --freeze-gate --require-existing
check_tool "Final Daily Use §2–§10 逐样式引文可用性带原因 / candidate 不可引用" python3 -c "import sys;sys.path.insert(0,'$VAULT');from workspace_ui.server import bibliography as B;a=B.citation_availability('bib.witness.seuil-pdf');assert a['passage_realizations']['total']==0 and all((not r['available']) and r['reason'] for r in a['rows'] if r['style'] in ('internal_short','internal_full','provenance')) and all(not r['available'] for r in a['rows']);c=B.citation_availability('bib.doc.lacan.seminar-23');assert c['candidate_not_citable'] and all(not r['available'] for r in c['rows']);print('citation-availability OK')"
check_tool "P5D-004 §11 Daily Use Gate v2 未被事后改动（冻结完整性；F1–F19）" python3 "$HERE/_tools/daily_use_acceptance.py" --freeze-gate --gate v2 --require-existing
check_tool "P5D-004 §9 i18n 资源一致性（catalog ↔ 词典 ↔ 调用点 ↔ index.html）" python3 "$HERE/_tools/build_i18n.py" --check
check_tool "P5D-004 §9 i18n 词典完整性（en/zh key 集合一致、无空值、无 undefined/null）" node --input-type=module -e "import {MESSAGES,FALLBACK_LOCALE} from '$VAULT/workspace_ui/static/src/i18n_messages.js'; const en=Object.keys(MESSAGES.en), zh=Object.keys(MESSAGES.zh); if(en.length!==zh.length) throw new Error('key count differs '+en.length+'/'+zh.length); const bad=en.filter(k=>!MESSAGES.en[k]||!MESSAGES.zh[k]||/^(undefined|null)$/.test(MESSAGES.zh[k])); if(bad.length) throw new Error('bad values: '+bad.slice(0,3).join(',')); if(FALLBACK_LOCALE!=='en') throw new Error('fallback locale'); console.log('i18n dict OK: '+en.length+' keys x 2 locales')"
check_tool "P5D-004 §4.2/§8/§9 locale 真源·回退链·html lang 实现存在（requested→default→可读兜底）" bash -c 'cd "$0" && grep -q "MESSAGES\[FALLBACK_LOCALE\]" workspace_ui/static/src/i18n.js && grep -q "missing.push(key)" workspace_ui/static/src/i18n.js && grep -q "htmlLangFor" workspace_ui/static/src/i18n.js && grep -q "Storage_Key\|STORAGE_KEY" workspace_ui/static/src/i18n.js && echo "i18n runtime OK"' "$VAULT"
check_tool "Final Daily Use §24–§27 一键接口脚本存在且无危险 kill（只杀身份通过的 PID）" bash -c 'cd "$0" && for f in _scripts/runtime/start_lacan_os.sh _scripts/runtime/stop_lacan_os.sh _scripts/runtime/check_lacan_os.sh "Start Lacan Knowledge OS.command" "Stop Lacan Knowledge OS.command" "Check Lacan Knowledge OS.command"; do [ -f "$f" ] || { echo "missing $f"; exit 1; }; done; ! grep -vE "^[[:space:]]*#" _scripts/runtime/*.sh | grep -qE "killall|pkill|kill -f|kill chrome|xargs kill" && echo "launchers OK"' "$VAULT"

banner "记录结果（§24 第 21 条要有可核记录）"
python3 - "$RESULT_TSV" "$VAULT" "$FAILED" "$QUICK" <<'PYEOF'
import json, os, sys, time
tsv, vault, failed, quick = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
rows = []
for line in open(tsv, encoding="utf-8"):
    name, _, status = line.rstrip("\n").partition("\t")
    if name:
        rows.append({"name": name, "status": status})
out = {
    "schema_version": "test-run/v1",
    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "quick_mode": bool(quick),
    "exit_code": failed,
    "suites": len([r for r in rows if not r["name"].startswith("tool:")]),
    "checks": len([r for r in rows if r["name"].startswith("tool:")]),
    "failed_suites": [r["name"] for r in rows if r["status"] == "FAIL"],
    "skipped": [r["name"] for r in rows if r["status"] == "SKIP"],
    "results": rows,
    "note": ("exit_code=0 且 failed_suites 为空才算全绿。"
             "--quick 会 SKIP 三个慢套件 → §24 第 21 条要求完整跑一次，"
             "SKIP 时不得据此判 green。" if quick else
             "完整模式：所有套件都已执行。"),
}
p = os.path.join(vault, "_data", "index", "TEST_RUN.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("  -> %s（%d 套件 / %d 校验器 / failed=%s）" % (
    p, out["suites"], out["checks"], out["failed_suites"] or "[]"))
PYEOF

banner "结果"
if [ "$FAILED" -eq 0 ]; then
  if [ "$QUICK" -eq 1 ]; then
    printf '\033[33m快速模式通过（有 SKIP，不得据此判 §24 第 21 条 green）\033[0m\n'
  else
    printf '\033[32m全部通过\033[0m\n'
  fi
else
  printf '\033[31m有失败项\033[0m\n'
fi
exit "$FAILED"
