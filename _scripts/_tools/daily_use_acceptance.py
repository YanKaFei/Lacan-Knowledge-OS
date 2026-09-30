#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_use_acceptance.py — Final Daily Use Gate v1（F1–F18）验收运行器。

边界（§39）：
    * 本文件**只做产品层验收**：启动/停止/体检接口、首页与书目 UI、导入 UI、无伪造引文扫描、
      密钥泄漏扫描、冻结/谱系校验、全量回归。
    * **不**改任何 scholarly semantics；不重跑/不改写历史 run。

用法：
    python3 _scripts/_tools/daily_use_acceptance.py --freeze-gate    # 冻结 Gate v1（已存在则校验）
    python3 _scripts/_tools/daily_use_acceptance.py --run            # 正式验收（生成 immutable run）
    可选：--port 3090、--skip-regression、--only F7,F8、--keep-vault

run 目录（**immutable**，禁止改写旧 run）：
    _data/daily_use/daily_use_bibliography_acceptance_<UTC ts>_<8hex>/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
VAULT = os.path.dirname(SCRIPTS)
TESTS = os.path.join(SCRIPTS, "_tests")
for _p in (VAULT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

GATE_ID = "final-daily-use-gate-v1"
GATE_PATH = os.path.join(VAULT, "_data", "daily_use", "daily_use_gate_v1.json")
# P5D-004：Gate v2 = v1 的 F1–F18 **逐字不变** + 新的 blocking F19。
# v1 文件**永不改写**（历史不可变，§16）；v2 是新的冻结产物。
GATE_ID_V2 = "final-daily-use-gate-v2"
GATE_PATH_V2 = os.path.join(VAULT, "_data", "daily_use", "daily_use_gate_v2.json")
F19 = ("F19", "LANGUAGE_SWITCH_FUNCTIONAL（真实浏览器：双向切换/无刷新/持久化/"
       "路由保持/html lang/无 JS 错误/学术文本不变）")
# P5D-005：Gate v3 = v2 的 F1–F19 **逐字不变** + 新的 blocking F20。
GATE_ID_V3 = "final-daily-use-gate-v3"
GATE_PATH_V3 = os.path.join(VAULT, "_data", "daily_use", "daily_use_gate_v3.json")
F20 = ("F20", "HELP_SYSTEM_EFFECTIVE（首页任务入口/模块 deep link/Help 内部链接与锚点/"
       "contextual help/8 个首用者任务/documentation fiction = 0）")
HELP_BROWSER_EVIDENCE = os.path.join(VAULT, "_workspace", "ui_qa",
                                     "p5d005_help_browser.json")
HELP_CLAIM_BROWSER = os.path.join(VAULT, "_workspace", "ui_qa",
                                  "p5d005_help_claim_browser.json")
HELP_LINK_REPORT = os.path.join(VAULT, "HELP_LINK_REPORT.json")
HELP_CLAIM_REPORT = os.path.join(VAULT, "HELP_CLAIM_VERIFICATION.json")
BUILD_HELP = os.path.join(HERE, "build_help.py")
HELP_TASK_IDS = ["TASK_1_RESEARCH", "TASK_2_EVIDENCE", "TASK_3_EXPLORE",
                 "TASK_4_PROJECT", "TASK_5_BIBLIOGRAPHY", "TASK_6_ZOTERO",
                 "TASK_7_SOURCE_TRACE", "TASK_8_LANGUAGE"]
I18N_EVIDENCE = os.path.join(VAULT, "_workspace", "ui_qa", "p5d004_i18n_evidence.json")
RUN_ROOT = os.path.join(VAULT, "_data", "daily_use")
RUNTIME = os.path.join(SCRIPTS, "runtime")
LOG_DIR = os.path.join(VAULT, "_workspace", "runtime", "logs")
PID_FILE = os.path.join(VAULT, "_workspace", "runtime", "ui.pid")
CAND_STORE = os.path.join(VAULT, "_workspace", "bibliography",
                          "imported_candidates.jsonl")
CONFLICT_STORE = os.path.join(VAULT, "_workspace", "bibliography",
                              "metadata_conflicts.jsonl")
REGRESSION = os.path.join(SCRIPTS, "run_all_tests.sh")

# §41：Gate v1 条目（一字不改；全部 blocking）
F_ITEMS = [
    ("F1", "one-click start PASS"),
    ("F2", "one-click stop PASS"),
    ("F3", "double-start safe"),
    ("F4", "stale PID recovery PASS"),
    ("F5", "browser auto-open PASS"),
    ("F6", "homepage navigation PASS"),
    ("F7", "bibliography UI PASS"),
    ("F8", "candidate never citable"),
    ("F9", "incomplete metadata never rendered as full citation"),
    ("F10", "Zotero import always candidate"),
    ("F11", "metadata conflict not silently resolved"),
    ("F12", "Obsidian user content preserved"),
    ("F13", "provider unavailable does not block local use"),
    ("F14", "secrets leakage = 0"),
    ("F15", "scholarly semantic drift = 0"),
    ("F16", "full regression clean"),
    ("F17", "core freeze PASS"),
    ("F18", "freeze lineage PASS"),
]

SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9_\-]{12,}",
    r"AIza[0-9A-Za-z_\-]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"DSH_SYNTHESIS_API_KEY\s*[:=]\s*\S",
    r"Authorization:\s*Bearer\s+\S",
)


# ────────────────────────────────────────────────────────────── 基础工具
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else
                          data.encode("utf-8")).hexdigest()


def gate_body_v2():
    """Gate v2：F1–F18 与 v1 完全一致，追加 blocking F19。"""
    body = gate_body()
    items = list(body["items"]) + [{"id": F19[0], "title": F19[1], "blocking": True}]
    body.update({"schema_version": "final-daily-use-gate/v2", "gate_id": GATE_ID_V2,
                 "source_clause": "§11（P5D-004，2026-09-28 追加）",
                 "supersedes": GATE_ID,
                 "added_after": ("P5D-004 discovered after Daily Use Gate v1："
                                 "Gate v1 缺少语言切换的**行为**覆盖（只有结构/存在性断言）"),
                 "items": items, "items_n": len(items)})
    return body


def gate_body():
    return {
        "schema_version": "final-daily-use-gate/v1",
        "gate_id": GATE_ID,
        "phase": "Final Daily Use & Bibliography UX Hardening",
        "source_clause": "§41",
        "items": [{"id": i, "title": t, "blocking": True} for i, t in F_ITEMS],
        "items_n": len(F_ITEMS),
        "all_blocking": True,
        "rule": "全部 blocking：任一 F 项 FAIL 则本阶段不成立。",
    }


def gate_body_v3():
    """Gate v3：F1–F19 与 v2 完全一致，追加 blocking F20（帮助系统真的有效）。"""
    body = gate_body_v2()
    items = list(body["items"]) + [{"id": F20[0], "title": F20[1], "blocking": True}]
    body.update({"schema_version": "final-daily-use-gate/v3", "gate_id": GATE_ID_V3,
                 "source_clause": "§20（P5D-005，2026-09-30 追加）",
                 "supersedes": GATE_ID_V2,
                 "added_after": ("P5D-005 discovered after Daily Use Gate v2："
                                 "Gate v2 只覆盖文案与行为，没有覆盖"
                                 "「用户能不能靠首页与 Help 完成任务」（onboarding/help 有效性）"),
                 "items": items, "items_n": len(items)})
    return body


def gate_path(version="v1"):
    if version == "v3":
        return GATE_PATH_V3
    return GATE_PATH if version == "v1" else GATE_PATH_V2


def gate_hash(body):
    payload = dict(body)
    payload.pop("gate_hash", None)
    payload.pop("frozen_at", None)
    return _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def cmd_gate_freeze(require_existing=False, version="v1"):
    body = {"v1": gate_body, "v2": gate_body_v2, "v3": gate_body_v3}[version]()
    gate_file = gate_path(version)
    h = gate_hash(body)
    if os.path.isfile(gate_file):
        with open(gate_file, encoding="utf-8") as fh:
            cur = json.load(fh)
        if cur.get("gate_hash") != gate_hash(cur):
            print(json.dumps({"kind": "gate", "status": "TAMPERED",
                              "path": os.path.relpath(gate_file, VAULT)},
                             ensure_ascii=False))
            return 2
        if cur.get("gate_hash") != h:
            print(json.dumps({"kind": "gate", "status": "CONTENT_MISMATCH",
                              "path": os.path.relpath(gate_file, VAULT)},
                             ensure_ascii=False))
            return 2
        print(json.dumps({"kind": "gate", "status": "FROZEN_OK",
                          "gate_id": cur.get("gate_id"), "items_n": cur.get("items_n"),
                          "gate_hash": cur.get("gate_hash"),
                          "frozen_at": cur.get("frozen_at"),
                          "path": os.path.relpath(gate_file, VAULT)},
                         ensure_ascii=False))
        return 0
    if require_existing:
        print(json.dumps({"kind": "gate", "status": "MISSING",
                          "path": os.path.relpath(gate_file, VAULT)},
                         ensure_ascii=False))
        return 3
    os.makedirs(os.path.dirname(gate_file), exist_ok=True)
    body["frozen_at"] = _now()
    body["gate_hash"] = h
    with open(gate_file, "w", encoding="utf-8") as fh:
        json.dump(body, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps({"kind": "gate", "status": "FROZEN",
                      "gate_id": body["gate_id"], "items_n": body["items_n"],
                      "gate_hash": h, "path": os.path.relpath(gate_file, VAULT)},
                     ensure_ascii=False))
    return 0


_recorded_pid_before = None


class Ctx:
    """验收上下文：端口、run 目录、进程与日志工具。"""

    def __init__(self, port, run_dir, keep_vault=False):
        self.port = port
        self.base = "http://127.0.0.1:%d" % port
        self.run_dir = run_dir
        self.keep_vault = keep_vault
        self.checks = {}
        self.timing = {}
        self.notes = []

    # ── 文件/HTTP
    def page(self, path=""):
        """页 URL（Gate 内部导航统一钉住 `uiLocale=en`）。

        P5D-004 之后产品默认按**浏览器语言**初始化；本机 Chrome 是 zh-CN，
        而 Gate 的既有断言（F6/F7/F10/F11…）断言的是**英文文案**。
        测试必须钉住它断言的语言，而不是让产品去迁就测试。
        """
        url = self.base + (path or "/")
        if "uiLocale=" in url:
            return url
        return url + ("&" if "?" in url else "?") + "uiLocale=en"

    def write(self, rel, text):
        p = os.path.join(self.run_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return os.path.relpath(p, self.run_dir)

    def write_json(self, rel, obj):
        return self.write(rel, json.dumps(obj, ensure_ascii=False, indent=1,
                                          sort_keys=True))

    def get(self, path, timeout=20):
        url = self.base + path
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:                                              # noqa: BLE001
                body = {"raw": "unparsable"}
            return e.code, body
        except Exception as exc:                                           # noqa: BLE001
            return 0, {"error": type(exc).__name__}

    def post(self, path, payload, timeout=60):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:                                              # noqa: BLE001
                body = {"raw": "unparsable"}
            return e.code, body
        except Exception as exc:                                           # noqa: BLE001
            return 0, {"error": type(exc).__name__}

    # ── 进程/端口（只读；绝不做 killall/pkill）
    def status(self):
        code, data = self.get("/api/status")
        return {"code": code, "data": data}

    def procs(self):
        out = subprocess.run(["ps", "-eo", "pid=,command="], capture_output=True,
                             text=True).stdout
        rows = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            pid, _, cmd = line.partition(" ")
            rows.append((int(pid), cmd.strip()))
        return rows

    def count(self, needle):
        return [p for p, c in self.procs() if needle in c and "daily_use_acceptance" not in c]

    def port_open(self, port=None):
        s = socket.socket()
        s.settimeout(0.6)
        try:
            s.connect(("127.0.0.1", port or self.port))
            return True
        except Exception:                                                  # noqa: BLE001
            return False
        finally:
            s.close()

    def wait_health(self, port=None, timeout=90):
        base = "http://127.0.0.1:%d" % (port or self.port)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/api/status", timeout=4) as r:
                    if r.status == 200:
                        return True
            except Exception:                                              # noqa: BLE001
                time.sleep(0.5)
        return False

    # ── 运行外部命令
    def sh(self, args, env=None, timeout=600, cwd=VAULT):
        """跑外部命令并把输出写进**临时文件**（不是管道）。

        ⚠️ 实测踩过（P5D-004 第二次验收）：回归里的套件会 spawn 子进程
        （UI → MCP、Chrome…）。若用 `capture_output=True`（管道），脚本自己退出后
        **孤儿孙进程仍持有管道写端**，`subprocess.run` 会一直等 EOF → Gate 永久卡住。
        改成文件重定向后只等直接子进程，不再受孤儿影响。
        """
        e = dict(os.environ)
        e.update(env or {})
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="dsh_sh_") as td:
            out_p = os.path.join(td, "stdout")
            err_p = os.path.join(td, "stderr")
            code = -9
            with open(out_p, "wb") as fo, open(err_p, "wb") as fe:
                try:
                    proc = subprocess.run(args, stdout=fo, stderr=fe, env=e, cwd=cwd,
                                          timeout=timeout)
                    code = proc.returncode
                except subprocess.TimeoutExpired:
                    code = -9
            def _read(path):
                try:
                    with open(path, "rb") as fh:
                        return fh.read().decode("utf-8", "replace")
                except OSError:
                    return ""
            stdout, stderr = _read(out_p), _read(err_p)
        if code == -9 and not stderr:
            stderr = "TIMEOUT"
        return {"argv": args, "exit": code, "stdout": stdout[-200000:],
                "stderr": stderr[-200000:], "secs": round(time.time() - t0, 2)}

    def script(self, name):
        return os.path.join(RUNTIME, name)

    def logs_text(self):
        if not os.path.isdir(LOG_DIR):
            return ""
        blob = []
        for fn in sorted(os.listdir(LOG_DIR)):
            p = os.path.join(LOG_DIR, fn)
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        blob.append(fh.read())
                except OSError:
                    pass
        return "\n".join(blob)

    def record(self, fid, ok, detail, evidence=None):
        self.checks[fid] = {"id": fid, "status": "PASS" if ok else "FAIL",
                            "blocking": True, "detail": detail,
                            "evidence": evidence or []}
        print("  %-4s %s  %s" % (fid, "PASS" if ok else "FAIL",
                                 json.dumps(detail, ensure_ascii=False)[:220]))


# ────────────────────────────────────────────────────────────── 各项检查
def f17_core_freeze(ctx):
    r = ctx.sh([sys.executable, os.path.join(HERE, "core_freeze.py"), "--verify"])
    ok = r["exit"] == 0 and "SCHOLARLY_CORE_READY" in (r["stdout"] + r["stderr"])
    ctx.record("F17", ok, {"exit": r["exit"], "out": r["stdout"].strip()[:200]})


def f18_freeze_lineage(ctx):
    r = ctx.sh([sys.executable, os.path.join(HERE, "freeze_lineage.py"), "--verify"])
    live = os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json")
    seg = {}
    if os.path.isfile(live):
        with open(live, encoding="utf-8") as fh:
            seg = json.load(fh)
    ok = (r["exit"] == 0 and seg.get("all_segments_status_pass") is True
          and seg.get("live_matches_last_segment") is True
          and len(seg.get("segments") or []) >= 7)
    ctx.record("F18", ok, {"exit": r["exit"], "segments": len(seg.get("segments") or []),
                           "live_matches_last_segment": seg.get("live_matches_last_segment"),
                           "out": r["stdout"].strip()[:200]})


def f15_semantic_drift(ctx):
    live = os.path.join(VAULT, "_data", "core_freeze", "freeze_lineage.json")
    with open(live, encoding="utf-8") as fh:
        seg = json.load(fh)
    per = [s.get("scholarly_semantic_changes") for s in (seg.get("segments") or [])]
    bad = [s.get("phase") for s in (seg.get("segments") or [])
           if s.get("status") != "PASS" or s.get("failure_codes")]
    ok = (seg.get("semantic_changes_total") == 0
          and seg.get("all_segments_semantic_changes_zero") is True
          and not bad and all(x == 0 for x in per))
    ctx.record("F15", ok, {"semantic_changes_total": seg.get("semantic_changes_total"),
                           "all_segments_zero": seg.get("all_segments_semantic_changes_zero"),
                           "segments": len(seg.get("segments") or []),
                           "per_segment_semantic": per,
                           "bad_segments": bad,
                           "failure_codes": []})


def _mcp_children(pid):
    """某 pid 名下的 MCP 子进程（只读）。"""
    if not pid:
        return []
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,command="], capture_output=True,
                         text=True).stdout
    kids = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        cpid, ppid, cmd = parts
        if ppid == str(pid) and "mcp_server/server.py" in cmd:
            kids.append(int(cpid))
    return kids


def _port_holder(port):
    """监听该端口的、且身份是**我们的 UI 模块**的 pid（只读）。"""
    out = subprocess.run(["lsof", "-ti", "tcp:%d" % port], capture_output=True,
                         text=True).stdout.split()
    for tok in out:
        if not tok.strip().isdigit():
            continue
        pid = int(tok)
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True).stdout
        if "workspace_ui.server.cli" in cmd:
            return pid
    return None


def _recorded_pid():
    try:
        with open(PID_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except Exception:                                                      # noqa: BLE001
        return None


def _alive(pid):
    if not pid:
        return False
    out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                         capture_output=True, text=True).stdout
    return "workspace_ui.server.cli" in out


def _script_counts(stdout):
    """解析 start/stop 脚本自报的进程计数（本实例口径 vs 同仓库全量）。"""
    out = {}
    m = re.search(r"ui_processes=(\d+)\s+mcp_processes=(\d+)", stdout or "")
    if m:
        out["instance_ui"], out["instance_mcp"] = int(m.group(1)), int(m.group(2))
    m2 = re.search(r"repo_wide_ui_processes=(\d+)\s+repo_wide_mcp_processes=(\d+)",
                   stdout or "")
    if m2:
        out["repo_wide_ui"], out["repo_wide_mcp"] = int(m2.group(1)), int(m2.group(2))
    return out


def _orphan_mcp(ctx):
    """父进程已是 1 的 MCP 子进程（UI 异常死亡后可能残留）。**只统计，不杀。**"""
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,command="], capture_output=True,
                         text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid, cmd = parts
        if "mcp_server/server.py" in cmd and ppid == "1":
            rows.append(int(pid))
    return rows


def f1_start(ctx):
    r = ctx.sh(["bash", ctx.script("start_lacan_os.sh")],
               env={"LACAN_NO_OPEN": "1", "LACAN_OPEN_CMD": "/bin/echo"}, timeout=300)
    health = ctx.wait_health(timeout=90)
    st = ctx.status()["data"] if health else {}
    counts = _script_counts(r["stdout"])
    orphans = _orphan_mcp(ctx)
    layers = (st.get("layers") or {})
    pid = _recorded_pid()
    holder = _port_holder(ctx.port)
    ok = (r["exit"] == 0 and health
          and counts.get("instance_ui") == 1 and counts.get("instance_mcp") == 1
          and _alive(pid) and holder == pid
          and layers.get("core") == "READY" and layers.get("mcp") == "READY")
    ctx.write("logs/start.stdout.txt", r["stdout"])
    ctx.write("logs/start.stderr.txt", r["stderr"])
    ctx.record("F1", ok, {"exit": r["exit"], "health": health, "counts": counts,
                          "recorded_pid": pid, "recorded_pid_alive": _alive(pid),
                          "port_holder": holder,
                          "repo_wide": {"ui": len(ctx.count("workspace_ui.server.cli")),
                                        "mcp": len(ctx.count("mcp_server/server.py"))},
                          "orphan_mcp_pids": orphans, "layers": layers})


def f3_double_start(ctx):
    before_ui = len(ctx.count("workspace_ui.server.cli"))
    before_mcp = len(ctx.count("mcp_server/server.py"))
    r = ctx.sh(["bash", ctx.script("start_lacan_os.sh")],
               env={"LACAN_NO_OPEN": "1", "LACAN_OPEN_CMD": "/bin/echo"}, timeout=300)
    time.sleep(1.5)
    after_ui = len(ctx.count("workspace_ui.server.cli"))
    after_mcp = len(ctx.count("mcp_server/server.py"))
    counts = _script_counts(r["stdout"])
    already = "ALREADY_RUNNING" in (r["stdout"] + r["stderr"])
    health = ctx.wait_health(timeout=60)
    pid = _recorded_pid()
    alive_after = _alive(pid)
    no_new_instance = after_ui <= before_ui and after_mcp <= before_mcp
    ok = (r["exit"] == 0 and already and health and alive_after and no_new_instance
          and counts.get("instance_ui") == 1 and counts.get("instance_mcp") == 1)
    ctx.write("logs/start2.stdout.txt", r["stdout"])
    ctx.write("logs/start2.stderr.txt", r["stderr"])
    ctx.record("F3", ok, {"exit": r["exit"], "already_running_marker": already,
                          "health": health, "counts": counts,
                          "recorded_pid": pid, "recorded_pid_alive_after": alive_after,
                          "no_new_instance": no_new_instance,
                          "ui_before": before_ui, "ui_after": after_ui,
                          "mcp_before": before_mcp, "mcp_after": after_mcp})


def f5_browser_open(ctx):
    """§25 第 7 步：真的执行「打开默认浏览器」这一步，但不真的弹窗。

    做法：`LACAN_OPEN_CMD=/bin/echo`（缺省 open）→ 日志出现
    `browser_open url=http://127.0.0.1:<port>/ cmd=/bin/echo`。
    """
    stop = ctx.sh(["bash", ctx.script("stop_lacan_os.sh")], timeout=180)
    time.sleep(1.5)
    before = len(ctx.logs_text())
    r = ctx.sh(["bash", ctx.script("start_lacan_os.sh")],
               env={"LACAN_OPEN_CMD": "/bin/echo"}, timeout=300)
    tail = ctx.logs_text()[before:]
    blob = tail + r["stdout"] + r["stderr"]
    url_in_log = bool(re.search(re.escape(ctx.base) + r"/?", blob))
    marker = re.search(r"browser_open url=\S+ cmd=\S+", blob)
    health = ctx.wait_health(timeout=90)
    ctx.write("logs/browser_open.txt", blob[-4000:])
    ctx.write("logs/f5_stop.stdout.txt", stop["stdout"])
    pid = _recorded_pid()
    holder = _port_holder(ctx.port)
    ok = (r["exit"] == 0 and health and url_in_log and bool(marker)
          and _alive(pid) and holder == pid)
    ctx.record("F5", ok, {"exit": r["exit"], "health": health,
                          "recorded_pid": pid, "port_holder": holder,
                          "url_in_log": url_in_log,
                          "browser_open_marker": (marker.group(0) if marker else None),
                          "open_cmd_used": "/bin/echo (no real window)"})


def f4_stale_pid(ctx):
    # 先正常停止（复用 stop 脚本），再写入一个**不存在**的 PID 记录
    stop = ctx.sh(["bash", ctx.script("stop_lacan_os.sh")], timeout=180)
    time.sleep(2)
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as fh:
        fh.write("999999\n")
    before = len(ctx.logs_text())
    r = ctx.sh(["bash", ctx.script("start_lacan_os.sh")],
               env={"LACAN_NO_OPEN": "1", "LACAN_OPEN_CMD": "/bin/echo"}, timeout=300)
    health = ctx.wait_health(timeout=90)
    tail = ctx.logs_text()[before:]
    marker = "STALE_PID_RECOVERED" in tail or "STALE_PID_RECOVERED" in (
        r["stdout"] + r["stderr"])
    pid = _recorded_pid()
    holder = _port_holder(ctx.port)
    ok = (r["exit"] == 0 and health and marker and _alive(pid) and holder == pid)
    ctx.write("logs/stale_stop.stdout.txt", stop["stdout"])
    ctx.write("logs/stale_start.stdout.txt", r["stdout"])
    ctx.record("F4", ok, {"exit": r["exit"], "health": health,
                          "stale_marker": marker, "recorded_pid": pid,
                          "port_holder": holder, "recorded_pid_alive": _alive(pid),
                          "stale_pid_written": 999999})


def f2_stop(ctx):
    global _recorded_pid_before
    _recorded_pid_before = _recorded_pid()
    r = ctx.sh(["bash", ctx.script("stop_lacan_os.sh")], timeout=180)
    time.sleep(2)
    pid_before = _recorded_pid_before
    dead = not _alive(pid_before)
    holder = _port_holder(ctx.port)
    open_after = ctx.port_open()
    pid_left = os.path.isfile(PID_FILE)
    # 幂等：再停一次
    r2 = ctx.sh(["bash", ctx.script("stop_lacan_os.sh")], timeout=120)
    mcp_kids = _mcp_children(pid_before)
    ok = (r["exit"] == 0 and dead and holder is None and not open_after
          and not pid_left and r2["exit"] == 0 and not mcp_kids)
    ctx.write("logs/stop.stdout.txt", r["stdout"])
    ctx.write("logs/stop2.stdout.txt", r2["stdout"])
    ctx.record("F2", ok, {"exit": r["exit"], "exit_second": r2["exit"],
                          "stopped_pid": pid_before, "port_holder": holder,
                          "mcp_children_left": mcp_kids,
                          "port_open": open_after, "pid_file_left": pid_left,
                          "repo_wide": {"ui": len(ctx.count("workspace_ui.server.cli")),
                                        "mcp": len(ctx.count("mcp_server/server.py"))}})
    ctx.write_json("logs/stop.stdout.txt.json", _script_counts(r["stdout"]))


def _nav_obsidian_probe(ctx):
    """§32：侧边栏 Obsidian 按钮必须真的绑定动作（点击后请求 /api/obsidian/status）。

    headless 里不能真的跳到 obsidian://，所以用 fetch 打点证明「有动作」而不是死按钮。
    """
    out = {"ok": False}
    try:
        from _cdp_testlib import CDP, chrome_available
        if not chrome_available():
            out["error"] = "chrome unavailable"
            return out
        cdp = CDP(window="1200,900")
        try:
            cdp.navigate(ctx.page("/?view=home"))
            cdp.js("(function(){window.__calls=[];var of=window.fetch.bind(window);"
                   "window.fetch=function(){try{window.__calls.push(String(arguments[0]))}"
                   "catch(e){};return of.apply(null,arguments)};})()")
            cdp.js("document.getElementById('nav-obsidian').click()")
            time.sleep(1.5)
            calls = cdp.js("window.__calls") or []
            out["calls"] = [c for c in calls if "obsidian" in str(c)]
            out["ok"] = bool(out["calls"])
        finally:
            cdp.close()
    except Exception as exc:                                               # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    return out


# ── 浏览器证据：统一走 CDP（等待 data-ready + 视图标记），不用 --dump-dom
#    原因（实测）：本机高负载时 `--dump-dom` 的看门狗会拿到**部分 DOM**，
#    产生假红。CDP 的 navigate 会等 `body[data-ready=1]`，再等视图标记，
#    渲染不稳定时**重试**（重试只针对渲染，不针对断言）。
def _cdp_dom_once(ctx, url, wait_js=None, window="1500,1100"):
    from _cdp_testlib import CDP, chrome_available
    if not chrome_available():
        return None, "chrome_unavailable"
    cdp = CDP(window=window, timeout=60)
    try:
        if not cdp.navigate(url):
            return None, "navigate_timeout"
        if wait_js:
            if not cdp.wait_js(wait_js, 30):
                return None, "view_marker_timeout"
        dom = cdp.js("document.documentElement.outerHTML") or ""
        return dom, None
    finally:
        try:
            cdp.close()
        except Exception:                                                  # noqa: BLE001
            pass


def _dom(ctx, url, wait_js=None, min_len=4000, tries=3):
    """→ (dom, meta)。渲染失败/过短 → 重试（记录 render_tries）。"""
    last = None
    for i in range(tries):
        if not ctx.port_open():
            ctx.wait_health(timeout=60)
        try:
            dom, err = _cdp_dom_once(ctx, url, wait_js=wait_js)
        except Exception as exc:                                           # noqa: BLE001
            # Chrome/CDP 偶发启动失败（高负载实测：无法连上 DevTools 端口）属于**渲染**失败，
            # 与断言失败不同：重试即可，并把原因记进证据。
            dom, err = None, "%s: %s" % (type(exc).__name__, str(exc)[:120])
        if dom and len(dom) >= min_len:
            return dom, {"render_tries": i + 1, "dom_len": len(dom), "error": None}
        last = err or ("short_dom:%d" % len(dom or ""))
        time.sleep(1.5)
    return "", {"render_tries": tries, "dom_len": 0, "error": last}


def f6_homepage(ctx):
    dom_home, m1 = _dom(ctx, ctx.page("/?view=home"),
                        wait_js="!!document.getElementById('home-title')")
    dom_explore, m2 = _dom(ctx, ctx.page("/?view=explore"),
                           wait_js="!!document.querySelector('#explore-list [data-explore]')")
    ctx.write("browser_qa/home.html", dom_home)
    ctx.write("browser_qa/explore.html", dom_explore)
    need_home = ["home-title", "Lacan Knowledge OS", "System Status", "home-research",
                 "home-explore", "home-projects", "home-bibliography",
                 "home-open-obsidian", "status-core", "status-mcp", "status-corpus",
                 "status-workspace", "status-explorer", "status-obsidian",
                 "status-bibliography", "status-provider"]
    need_explore = ['data-explore="%s"' % k for k in
                    ("concepts", "persons", "cases", "seminars", "passages",
                     "terminology", "bibliography")]
    miss_home = [n for n in need_home if n not in dom_home]
    miss_ex = [n for n in need_explore if n not in dom_explore]
    nav = ["nav-home", "nav-research", "nav-explore", "nav-projects",
           "nav-bibliography", "nav-obsidian", "nav-history", "nav-saved"]
    miss_nav = [n for n in nav if n not in dom_home]
    obsidian = _nav_obsidian_probe(ctx)
    ok = not miss_home and not miss_ex and not miss_nav and obsidian.get("ok")
    ctx.write_json("browser_qa/nav_obsidian.json", obsidian)
    ctx.record("F6", ok, {"render": {"home": m1, "explore": m2},
                          "missing_home": miss_home, "missing_explore": miss_ex,
                          "missing_nav": miss_nav, "explore_domains": 7,
                          "system_status_layers": 8,
                          "obsidian_button_wired": obsidian.get("ok"),
                          "obsidian_calls": obsidian.get("calls")})


def _project_bibliography_probe(ctx):
    """§20/§21：项目书目三组 + 显式 Link（真实 HTTP + 真实浏览器）。

    会创建一个**探针项目**并在结束时删除（只删本次创建的那个目录；先快照目录列表）。
    """
    import project_api.store as PS
    out = {"ok": False, "steps": {}}
    projects_dir = PS.PROJECTS_DIR
    before = sorted(os.listdir(projects_dir)) if os.path.isdir(projects_dir) else []
    pid = None
    try:
        code, proj = ctx.post("/api/projects/create",
                              {"title": "FINALDAILY probe project",
                               "description": "acceptance probe (auto-removed)"})
        out["steps"]["create"] = code
        if code != 200 or proj.get("kind") == "error":
            out["error"] = "create failed: %s" % json.dumps(proj, ensure_ascii=False)[:200]
            return out
        _pv = proj.get("project") or proj
        pid = _pv.get("project_id")
        rev = _pv.get("revision")
        if pid is None:
            out["error"] = "no project_id in create response"
            return out
        # 组 2/3：用户自由输入（legacy 自由文本）
        code, added = ctx.post("/api/projects/add",
                               {"project_id": pid, "expected_revision": rev,
                                "kind": "bibliography",
                                "payload": {"title": "Probe legacy reference",
                                            "author": "Probe", "year": "1966"}})
        out["steps"]["add_legacy_ref"] = code
        rev = (added.get("project") or added).get("revision", rev)
        # 组 1：显式挂接 reviewed registry 条目
        code, linked = ctx.post("/api/projects/add_bibliographic_item",
                                {"project_id": pid, "expected_revision": rev,
                                 "bibliographic_id": "bib.witness.staferla"})
        out["steps"]["add_bibliographic_item"] = code
        if code != 200:
            out["error"] = json.dumps(linked, ensure_ascii=False)[:200]
            return out
        code, det = ctx.get("/api/projects/detail?id=%s&tab=bibliography" % pid)
        pb = det.get("project_bibliography") or {}
        reviewed = [r for r in (pb.get("project_bibliography_refs") or [])
                    if not r.get("user_supplied")]
        legacy = pb.get("legacy_user_supplied_refs") or []
        out["steps"]["reviewed_n"] = len(reviewed)
        out["steps"]["legacy_n"] = len(legacy)
        # 显式 Link（§21）
        link_ok = None
        if legacy:
            ref_id = legacy[0].get("ref_id")
            code, lr = ctx.post("/api/projects/link_legacy_ref",
                                {"project_id": pid, "expected_revision":
                                 det.get("project", {}).get("revision"),
                                 "ref_id": ref_id,
                                 "bibliographic_id": "bib.witness.staferla"})
            out["steps"]["link_legacy_ref"] = code
            link_ok = code == 200
            _, det2 = ctx.get("/api/projects/detail?id=%s&tab=bibliography" % pid)
            leg2 = (det2.get("project_bibliography") or {}).get(
                "legacy_user_supplied_refs") or []
            link_ok = link_ok and any(r.get("linked_bibliographic_id")
                                      for r in leg2)
        dom, mp = _dom(ctx, ctx.page("/?view=project&id=%s&tab=bibliography" % pid),
                       wait_js="!!document.getElementById('pbg-reviewed')")
        ctx.write("browser_qa/project_bibliography.html", dom)
        groups = {g: ('id="%s"' % g) in dom for g in
                  ("pbg-reviewed", "pbg-user-supplied", "pbg-legacy")}
        heads = {h: (h in dom) for h in ("Reviewed references",
                                         "User-supplied references",
                                         "Unlinked legacy references")}
        link_btn = ("Link to Bibliographic Item" in dom)
        out["steps"]["groups"] = groups
        out["steps"]["heads"] = heads
        out["steps"]["link_button"] = link_btn
        out["steps"]["link_ok"] = link_ok
        out["ok"] = (len(reviewed) == 1 and len(legacy) == 1
                     and all(groups.values()) and all(heads.values())
                     and link_btn and link_ok is True)
    except Exception as exc:                                               # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        if pid:
            after = sorted(os.listdir(projects_dir)) if os.path.isdir(projects_dir) else []
            created = [d for d in after if d not in before]
            for d in created:
                shutil.rmtree(os.path.join(projects_dir, d), ignore_errors=True)
            out["cleaned"] = (sorted(os.listdir(projects_dir))
                              == before) if os.path.isdir(projects_dir) else True
    return out


def f7_bibliography_ui(ctx):
    checks = {}
    ok = True
    # (a) 列表 + 分页结构
    dom_list, ml = _dom(ctx, ctx.page("/?view=bibliography"),
                        wait_js="document.querySelectorAll('.bib-row').length > 0")
    ctx.write("browser_qa/bibliography_list.html", dom_list)
    checks["render_list"] = ml
    checks["list_rows"] = dom_list.count('class="link-btn bib-row"')
    checks["list_has_ids"] = all(b in dom_list for b in
                                 ("bib.witness.staferla", "bib.doc.lacan.seminar-3"))
    # (b) reviewed 详情：reviewed / completeness / citation availability 三者并存
    dom_d, md = _dom(ctx, ctx.page("/?view=bibliography&id=bib.witness.staferla"),
                     wait_js="!!document.getElementById('bib-availability')")
    ctx.write("browser_qa/bibliography_staferla.html", dom_d)
    need = ["Overview", "Review Status", "Metadata Completeness",
            "Citation Availability", "Editions", "Witnesses", "Passages",
            "Seminars", "Projects", "Provenance",
            "bib-review-status", "bib-metadata-completeness",
            "bib-reviewed-not-complete", "bib-availability",
            "bib-passage-realizations", "Cop", "Chicago — UNAVAILABLE"]
    miss = [n for n in need if n not in dom_d]
    checks["render_detail"] = md
    checks["detail_missing"] = miss
    checks["reviewed_shown"] = 'id="bib-review-status"' in dom_d and "reviewed" in dom_d
    checks["completeness_shown"] = 'id="bib-metadata-completeness"' in dom_d
    checks["availability_shown"] = 'id="bib-availability"' in dom_d
    ok = ok and not miss and checks["list_has_ids"]
    # §42–§47：五个真实浏览器走查（reviewed / candidate / Staferla / Seuil / 中文回译）
    cases = {}
    dom_seuil, ms = _dom(ctx, ctx.page("/?view=bibliography&id=bib.witness.seuil-pdf"),
                         wait_js="!!document.getElementById('bib-passage-realizations')")
    ctx.write("browser_qa/bibliography_seuil.html", dom_seuil)
    cases["seuil"] = {
        "passage_realizations_0": "Passage Realizations: 0" in dom_seuil,
        "internal_unavailable": "Internal Short — UNAVAILABLE" in dom_seuil,
        "witness_record_exists": "bib-seuil-note" in dom_seuil,
        "no_copy_button": 'id="bib-cite-' not in dom_seuil,
        "render": ms,
    }                                                              # §46
    dom_zh, mzh = _dom(ctx,
                       ctx.page("/?view=bibliography&id=bib.witness.translation-project"),
                       wait_js="!!document.getElementById('bib-trace-incomplete')")
    ctx.write("browser_qa/bibliography_zh.html", dom_zh)
    cases["zh_recovered"] = {
        "source_trace_incomplete": "SOURCE_TRACE_INCOMPLETE" in dom_zh,
        "not_operational_error": "not an operational error" in dom_zh,
        "render": mzh,
    }                                                              # §47
    cases["staferla"] = {
        "internal_ready": 'id="bib-cite-internal_short"' in dom_d,
        "formal_unavailable": "Chicago — UNAVAILABLE" in dom_d,
        "passage_realizations": "Passage Realizations: 166,527" in dom_d,
    }                                                              # §45
    cases["reviewed_three_displays"] = {
        "reviewed": "reviewed" in dom_d,
        "completeness": "bib-metadata-completeness" in dom_d,
        "availability": "bib-availability" in dom_d,
    }                                                              # §43
    checks["qa_cases"] = cases
    ok = ok and all(cases["seuil"][k] for k in
                    ("passage_realizations_0", "internal_unavailable",
                     "witness_record_exists", "no_copy_button")) \
        and cases["zh_recovered"]["source_trace_incomplete"] \
        and cases["staferla"]["internal_ready"] \
        and cases["staferla"]["formal_unavailable"] \
        and cases["staferla"]["passage_realizations"] \
        and all(cases["reviewed_three_displays"].values())
    # §20/§21：项目书目三组 + 显式 Link
    proj = _project_bibliography_probe(ctx)
    checks["project_bibliography"] = proj.get("ok")
    checks["project_steps"] = proj.get("steps")
    ok = ok and bool(proj.get("ok")) and bool(proj.get("cleaned"))
    ctx.write_json("browser_qa/project_bibliography.json", proj)
    ctx.record("F7", ok, checks)


def f8_candidate_never_citable(ctx):
    cand = "bib.doc.lacan.seminar-23"
    code, av = ctx.get("/api/explore/citation_availability?id=" + cand)
    rows = av.get("rows") or []
    api_blocked = code == 200 and rows and all(r.get("available") is False for r in rows)
    styles = ["internal_short", "internal_full", "provenance", "chicago", "apa",
              "mla", "bibtex"]
    cites = {}
    for s in styles:
        _, r = ctx.get("/api/explore/bibliography_citation?id=%s&style=%s" % (cand, s))
        cites[s] = {"available": r.get("available"), "reason": (r.get("reason") or "")[:60]}
    cite_blocked = all(v["available"] is False for v in cites.values())
    dom, mc = _dom(ctx, ctx.page("/?view=bibliography&id=" + cand),
                   wait_js="!!document.getElementById('bib-candidate-banner')")
    ctx.write("browser_qa/bibliography_candidate.html", dom)
    banner = "NEEDS REVIEW" in dom and "NOT CITABLE" in dom
    no_button = 'id="bib-cite-' not in dom
    no_style_list = 'id="bib-availability"' not in dom
    ok = api_blocked and cite_blocked and banner and no_button and no_style_list
    ctx.record("F8", ok, {"api_all_unavailable": api_blocked, "citation_endpoint_blocked":
                          cite_blocked, "banner": banner, "no_copy_button": no_button,
                          "no_style_list": no_style_list, "citations": cites})


def f9_no_fake_citation(ctx):
    import bibliography as B
    reviewed = [i for i in B.registry.items()]
    findings = []
    formal = ("chicago", "apa", "mla", "bibtex")
    for it in reviewed:
        bid = it["bibliographic_id"]
        _, av = ctx.get("/api/explore/citation_availability?id=" + bid)
        av_rows = {r["style"]: r for r in (av.get("rows") or [])}
        for s in formal:
            row = av_rows.get(s) or {}
            if row.get("available"):
                _, c = ctx.get("/api/explore/bibliography_citation?id=%s&style=%s"
                               % (bid, s))
                text = c.get("text") or ""
                year = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", text)
                if year and not it.get("publication_year"):
                    findings.append({"item": bid, "style": s, "fake_year": year})
                if re.search(r"\bISBN\b", text) and not it.get("isbn"):
                    findings.append({"item": bid, "style": s, "fake_isbn": True})
                if it.get("publisher") and it["publisher"] not in text:
                    findings.append({"item": bid, "style": s, "missing_publisher": True})
        # null metadata 必须保持 null（不得被填上）
        if it.get("review_status") == "reviewed":
            for f in ("publisher", "publication_year", "isbn"):
                if it.get(f) not in (None, ""):
                    findings.append({"item": bid, "unexpected_metadata": f})
    # Obsidian 派生笔记：null → 破折号，绝不填值
    note_findings = []
    tmp_vault = os.path.join(VAULT, "_workspace", "test_vaults",
                             "dailyuse_f9_%d" % int(time.time()))
    try:
        import obsidian_adapter as OA
        from obsidian_adapter import bibliography as OAB
        from obsidian_adapter import vault as V
        v = V.Vault(root=tmp_vault)
        for bid in ("bib.witness.staferla", "bib.witness.seuil-pdf",
                    "bib.witness.translation-project"):
            OAB.save_bibliography_note(bid, vault=v)
            text = v.read(OAB.note_rel(bid))
            ctx.write("obsidian/%s.md" % bid, text)
            if "publisher: —" not in text or "publication_year: —" not in text:
                note_findings.append({"item": bid, "note": "null metadata not shown as —"})
            if re.search(r"isbn:\s*\S", text):
                note_findings.append({"item": bid, "note": "unexpected isbn"})
    finally:
        if not ctx.keep_vault and os.path.isdir(tmp_vault):
            shutil.rmtree(tmp_vault, ignore_errors=True)
    # 浏览器 DOM：null 必须显示为 —
    dom, mz = _dom(ctx, ctx.page("/?view=bibliography&id=bib.witness.staferla"),
                   wait_js="!!document.getElementById('bib-availability')")
    dom_ok = ("publisher" in dom and "—" in dom and "publication_year" in dom)
    if re.search(r"ISBN[:=]?\s*\d", dom):
        findings.append({"ui": "isbn_digits_in_dom"})
    ok = not findings and not note_findings and dom_ok
    ctx.write_json("no_fake_citation.json", {"findings": findings,
                                             "note_findings": note_findings,
                                             "dom_null_dash": dom_ok})
    ctx.record("F9", ok, {"api_findings": findings, "note_findings": note_findings,
                          "formal_styles_all_unavailable": not [f for f in findings
                                                                if "fake" in str(f)],
                          "ui_null_rendered_as_dash": dom_ok})


def _store_snapshot(path):
    if not os.path.isfile(path):
        return {"exists": False, "bytes": 0, "sha": None, "content": ""}
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    return {"exists": True, "bytes": len(content.encode("utf-8")),
            "sha": _sha(content), "content": content}


def _store_restore(path, snap):
    if not snap["exists"]:
        if os.path.isfile(path):
            os.remove(path)
        return not os.path.isfile(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(snap["content"])
    return _store_snapshot(path)["sha"] == snap["sha"]


def f10_zotero_import_always_candidate(ctx):
    import bibliography as B
    before_hash = B.registry.manifest().get("content_hash")
    before_counts = ctx.get("/api/status")[1].get("bibliography_registry")
    snap_c, snap_x = _store_snapshot(CAND_STORE), _store_snapshot(CONFLICT_STORE)
    if snap_c["exists"]:
        ctx.write("imports/imported_candidates.before.jsonl", snap_c["content"])
    payload = json.dumps([{
        "type": "book", "title": "FINALDAILY probe — candidate-only import",
        "author": [{"family": "Probe", "given": "Final"}],
        "issued": {"date-parts": [[2001]]},
        "DOI": "10.9999/finaldaily.probe.unique", "id": "probe-final-unique"}])
    prev_url = "/api/bibliography/import"
    code, prev = ctx.post(prev_url, {"text": payload, "source": "csl-json",
                                     "mode": "preview"})
    code2, commit = ctx.post(prev_url, {"text": payload, "source": "csl-json",
                                        "mode": "commit"})
    cands = ctx.get("/api/explore/bibliography_imports")[1].get("items") or []
    after_hash = B.registry.manifest().get("content_hash")
    after_counts = ctx.get("/api/status")[1].get("bibliography_registry")
    stored = [c for c in cands if "probe" in json.dumps(c, ensure_ascii=False).lower()
              or "FINALDAILY" in json.dumps(c, ensure_ascii=False)]
    all_candidate = all((c.get("review_status") or "candidate") == "candidate"
                        for c in stored) and bool(stored)
    # 浏览器：DataTransfer 注入文件 → Preview → Import as candidate（真实页面逻辑）
    browser = _import_browser_probe(ctx, payload, expect_conflict=False)
    # 再导入同一 DOI → 强去重
    _, again = ctx.post(prev_url, {"text": payload, "source": "csl-json",
                                   "mode": "preview"})
    dup = (again.get("duplicates") or [])
    strong = [d for d in dup if d.get("kind") == "EXACT_KEY"]
    restored = _store_restore(CAND_STORE, snap_c) and _store_restore(CONFLICT_STORE, snap_x)
    ok = (code == 200 and code2 == 200
          and prev.get("will_be", {}).get("review_status") == "candidate"
          and prev.get("will_be", {}).get("canonicalized") is False
          and commit.get("message", "").startswith("Imported as candidate")
          and all_candidate
          and before_hash == after_hash
          and before_counts == after_counts
          and strong and all(d.get("auto_merged") is False for d in strong)
          and browser.get("ok") and restored)
    ctx.write_json("imports/f10.json", {"preview_counts": prev.get("counts"),
                                        "commit_counts": commit.get("counts"),
                                        "stored_candidates": len(stored),
                                        "registry_hash_unchanged": before_hash == after_hash,
                                        "duplicates": dup, "browser": browser,
                                        "store_restored": restored})
    ctx.record("F10", ok, {"import_always_candidate": all_candidate,
                           "preview_will_be": prev.get("will_be"),
                           "commit_message": (commit.get("message") or "")[:60],
                           "registry_unchanged": before_hash == after_hash,
                           "strong_duplicate": bool(strong),
                           "auto_merged": [d.get("auto_merged") for d in strong],
                           "browser_import_ui": browser.get("ok"),
                           "store_restored": restored})


def _import_browser_probe(ctx, payload_text, expect_conflict):
    """真实浏览器：DataTransfer 注入文件 → 点 Preview → 点 Import as candidate。"""
    out = {"ok": False}
    try:
        from _cdp_testlib import CDP, chrome_available
        if not chrome_available():
            out["error"] = "chrome unavailable"
            return out
        cdp = CDP(window="1400,1000")
        try:
            cdp.navigate(ctx.page("/?view=bibliography"))
            # 打开 import 面板并注入文件（OS 文件选择器在 headless 下无法弹出 → 用 DataTransfer）
            expr = """
            (async () => {
              const box = document.getElementById('bib-import-panel');
              if (box) box.open = true;
              const input = document.getElementById('bib-import-file');
              if (!input) return {err: 'no input'};
              const dt = new DataTransfer();
              dt.items.add(new File([%s], 'probe.json', {type: 'application/json'}));
              input.files = dt.files;
              input.dispatchEvent(new Event('change', {bubbles: true}));
              const sel = document.getElementById('bib-import-source');
              if (sel) sel.value = 'csl-json';
              document.getElementById('bib-import-preview').click();
              return {files: input.files.length};
            })()
            """ % json.dumps(payload_text)
            out["inject"] = cdp.js(expr)
            cdp.wait_js("!!document.querySelector('#bib-import-preview-table')", 30)
            out["preview_rows"] = cdp.js(
                "document.querySelectorAll('#bib-import-preview-table .bib-preview-row').length")
            out["preview_counts"] = cdp.js(
                "(document.getElementById('bib-import-counts')||{}).textContent || null")
            out["preview_html"] = (cdp.js(
                "(document.getElementById('bib-import-preview-out')||{}).innerHTML || ''") or "")[:20000]
            # 先记录 preview 阶段的去重/冲突展示（点 commit 后预览区会被清空重绘）
            out["duplicates_shown"] = cdp.js(
                "!!document.querySelector('#bib-import-duplicates')")
            out["conflicts_shown"] = cdp.js(
                "!!document.querySelector('#bib-import-conflicts')")
            out["duplicate_text"] = cdp.js(
                "(document.getElementById('bib-import-duplicates')||{}).textContent || null")
            out["conflict_text"] = cdp.js(
                "(document.getElementById('bib-import-conflicts')||{}).textContent || null")
            # §16：不存在任何「全部批准」的**可点击入口**（正文说明不算入口）
            out["no_approve_all"] = cdp.js(
                "!Array.from(document.querySelectorAll('button,a,input[type=submit]'))"
                ".some(e => /approve all|import & approve|approve_all/i.test("
                "(e.textContent || e.value || '')))")
            cdp.js("document.getElementById('bib-import-commit').click()")
            cdp.wait_js("!!document.querySelector('#bib-import-message')", 30)
            out["message"] = cdp.js(
                "(document.getElementById('bib-import-message')||{}).textContent || null")
            out["ok"] = bool(out["preview_rows"]) and bool(out["message"]) \
                and "Not automatically canonicalized" in (out["message"] or "") \
                and out["no_approve_all"] is True
        finally:
            cdp.close()
    except Exception as exc:                                               # noqa: BLE001
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    return out


def f11_conflict_not_resolved(ctx):
    import bibliography as B
    snap_c, snap_x = _store_snapshot(CAND_STORE), _store_snapshot(CONFLICT_STORE)
    before_hash = B.registry.manifest().get("content_hash")
    payload = json.dumps([
        {"type": "book", "title": "FINALDAILY conflict probe",
         "author": [{"family": "Probe", "given": "Conflict"}],
         "issued": {"date-parts": [[1966]]}, "publisher": "Alpha Press",
         "DOI": "10.9999/finaldaily.probe.conflict", "id": "probe-conflict-a"},
        {"type": "book", "title": "FINALDAILY conflict probe",
         "author": [{"family": "Probe", "given": "Conflict"}],
         "issued": {"date-parts": [[1967]]}, "publisher": "Beta Press",
         "DOI": "10.9999/finaldaily.probe.conflict", "id": "probe-conflict-b"}])
    _, prev = ctx.post("/api/bibliography/import",
                       {"text": payload, "source": "csl-json", "mode": "preview"})
    _, commit = ctx.post("/api/bibliography/import",
                         {"text": payload, "source": "csl-json", "mode": "commit"})
    conflicts = prev.get("conflicts") or []
    stored = ctx.get("/api/explore/bibliography_conflicts")[1].get("items") or []
    dup = prev.get("duplicates") or []
    unresolved = bool(conflicts) and all(
        c.get("resolution") == "UNRESOLVED" and c.get("auto_overwrite") is False
        for c in conflicts)
    fields = sorted({c.get("field") for c in conflicts})
    values = {c.get("field"): c.get("values") for c in conflicts}
    both_kept = len({c.get("candidate_id") for c in prev.get("preview") or []}) == 2
    browser = _import_browser_probe(ctx, payload, expect_conflict=True)
    after_hash = B.registry.manifest().get("content_hash")
    restored = _store_restore(CAND_STORE, snap_c) and _store_restore(CONFLICT_STORE, snap_x)
    ok = (unresolved and fields and both_kept and browser.get("ok")
          and browser.get("conflicts_shown") is True
          and before_hash == after_hash and restored)
    ctx.write_json("imports/f11.json", {"conflicts": conflicts, "fields": fields,
                                        "values": values,
                                        "duplicates": dup,
                                        "stored_conflicts": len(stored),
                                        "browser": browser, "store_restored": restored})
    ctx.record("F11", ok, {"conflicts_n": len(conflicts), "fields": fields,
                           "values": values, "unresolved": unresolved,
                           "both_candidates_kept": both_kept,
                           "browser_conflict_shown": browser.get("conflicts_shown"),
                           "registry_unchanged": before_hash == after_hash,
                           "store_restored": restored})


def f12_obsidian_user_content(ctx):
    tmp = os.path.join(VAULT, "_workspace", "test_vaults",
                       "dailyuse_f12_%d" % int(time.time()))
    findings = {}
    try:
        from obsidian_adapter import bibliography as OAB
        from obsidian_adapter import vault as V
        v = V.Vault(root=tmp)
        bid = "bib.witness.staferla"
        first = OAB.save_bibliography_note(bid, vault=v)
        rel = OAB.note_rel(bid)
        text0 = v.read(rel)
        findings["created"] = first.get("created")
        markers = ("## My Notes\n\nSTAŻ user zone — îéà 中文 😀\n"
                   "second line with trailing spaces   \n\n")
        v.write(rel, text0 + markers)
        before = v.read(rel)
        OAB.save_bibliography_note(bid, vault=v)
        after = v.read(rel)
        import re as _re
        def user_zone(t):
            i = t.find("## My Notes")
            return t[i:] if i >= 0 else ""
        findings["user_zone_byte_preserved"] = user_zone(before) == user_zone(after)
        findings["user_zone_has_bytes"] = "😀" in user_zone(after)
        findings["no_id_frontmatter"] = not _re.search(r"^id:\s", after, _re.M)
        findings["no_type_frontmatter"] = not _re.search(r"^type:\s", after, _re.M)
        findings["managed_region_present"] = ("<!-- lacan:managed:start -->" in after
                                              or "managed:start" in after)
        findings["path_ok"] = rel == "_System/bibliography/%s.md" % bid
        findings["candidate_refused"] = False
        try:
            OAB.save_bibliography_note("bib.doc.lacan.seminar-23", vault=v)
        except Exception:                                                  # noqa: BLE001
            findings["candidate_refused"] = True
        ctx.write("obsidian/f12_note.md", after)
    finally:
        if not ctx.keep_vault and os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
    ok = all(findings.get(k) for k in ("user_zone_byte_preserved", "user_zone_has_bytes",
                                       "no_id_frontmatter", "no_type_frontmatter",
                                       "path_ok", "candidate_refused"))
    ctx.record("F12", ok, findings)


def f13_provider_unavailable(ctx):
    import tempfile
    port = ctx.port + 3
    home = tempfile.mkdtemp(prefix="dailyuse_nohome_")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home,
           "LACAN_UI_PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "workspace_ui.server.cli",
                             "--port", str(port)], cwd=VAULT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = "http://127.0.0.1:%d" % port
    up = False
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/status", timeout=4) as r:
                up = r.status == 200
                break
        except Exception:                                                  # noqa: BLE001
            time.sleep(0.6)
    out = {"provider_layer": None, "research_disabled": None, "local_endpoints": {}}
    try:
        if up:
            with urllib.request.urlopen(base + "/api/status", timeout=8) as r:
                st = json.loads(r.read().decode("utf-8"))
            out["provider_layer"] = (st.get("layers") or {}).get("provider")
            out["provider_state"] = (st.get("provider") or {}).get("state")
            out["research_disabled"] = st.get("research_disabled")
            for p in ("/api/explore/bibliography?limit=5", "/api/projects",
                      "/api/explore/bibliography_health", "/api/history?limit=3"):
                try:
                    with urllib.request.urlopen(base + p, timeout=10) as r:
                        out["local_endpoints"][p] = r.status
                except urllib.error.HTTPError as e:
                    out["local_endpoints"][p] = e.code
                except Exception as exc:                                   # noqa: BLE001
                    out["local_endpoints"][p] = type(exc).__name__
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:                                                  # noqa: BLE001
            proc.kill()
        shutil.rmtree(home, ignore_errors=True)
    provider_off = out.get("provider_state") in ("DEGRADED", "UNAVAILABLE")
    local_ok = bool(out["local_endpoints"]) and all(
        v == 200 for v in out["local_endpoints"].values())
    ok = up and provider_off and out.get("research_disabled") is False and local_ok
    ctx.write_json("provider_unavailable.json", out)
    ctx.record("F13", ok, out)


def f14_secrets(ctx):
    findings = []
    # 真实凭据值（读入内存用于比对；**绝不写入任何输出**）
    secret_value = None
    cred = os.path.expanduser("~/.dsh/.credentials.yaml")
    if os.path.isfile(cred):
        with open(cred, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*DEEPSEEK_API_KEY:\s*(\S+)\s*$", line)
                if m:
                    secret_value = m.group(1)
    if os.environ.get("DSH_SYNTHESIS_API_KEY"):
        secret_value = os.environ["DSH_SYNTHESIS_API_KEY"]
    targets = []
    scan_dirs = [ctx.run_dir, LOG_DIR]
    for d in scan_dirs:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                targets.append(os.path.join(root, fn))
    for p in targets:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                blob = fh.read()
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, blob):
                findings.append({"file": os.path.relpath(p, VAULT),
                                 "pattern": pat, "sample": m.group(0)[:8] + "…"})
        if secret_value and secret_value in blob:
            findings.append({"file": os.path.relpath(p, VAULT),
                             "pattern": "credential_value", "sample": "***"})
    # HTTP 载荷也必须不含密钥
    for path in ("/api/status", "/api/explore/bibliography_health"):
        _, data = ctx.get(path)
        blob = json.dumps(data, ensure_ascii=False)
        for pat in SECRET_PATTERNS:
            if re.search(pat, blob):
                findings.append({"file": "HTTP " + path, "pattern": pat, "sample": "***"})
        if secret_value and secret_value in blob:
            findings.append({"file": "HTTP " + path, "pattern": "credential_value",
                             "sample": "***"})
    ctx.write_json("secrets_scan.json", {"scanned_files": len(targets),
                                         "findings": findings,
                                         "credential_present_but_never_written": bool(secret_value)})
    ctx.record("F14", not findings, {"scanned_files": len(targets),
                                     "findings": findings[:5], "findings_n": len(findings),
                                     "credential_value_read": bool(secret_value)})


def _run_i18n_suite(ctx, tag):
    """跑一次 P5D-004 浏览器套件，返回 (exit, evidence, stderr_tail)。"""
    r = ctx.sh([sys.executable, "-m", "unittest", "test_p5d004_language_switch"],
               env={"PYTHONPATH": VAULT}, timeout=2400, cwd=TESTS)
    tests = {}
    if os.path.isfile(I18N_EVIDENCE):
        with open(I18N_EVIDENCE, encoding="utf-8") as fh:
            tests = (json.load(fh) or {}).get("tests") or {}
    ctx.write_json("i18n/browser_evidence_%s.json" % tag, tests)
    return r, tests, (r["stderr"] or "")[-1500:]


def _is_infra_failure(suite, tests, stderr):
    """区分**基础设施抖动**（Chrome/CDP 起不来）与**行为失败**（断言/证据不全）。

    只有前者允许一次有界重试（与本项目既有策略一致：对 Chrome 卡住重试，绝不对断言重试）。
    """
    if "CDP" in stderr or "无法连上 Chrome DevTools" in stderr or "chrome" in stderr.lower():
        return True
    expected = {"test_01_en_to_zh", "test_02_zh_to_en", "test_03_persistence",
                "test_04_navigation_persistence", "test_05_deep_route",
                "test_06_html_lang", "test_07_no_js_errors",
                "test_08_scholarly_integrity"}
    missing = sorted(expected - set(tests))
    # 证据缺失 + 套件非零退出，且**没有任何** FAIL 记录 → 归为基础设施抖动
    if missing and suite["exit"] != 0:
        any_fail = any((v or {}).get("status") == "FAIL" for v in tests.values())
        return not any_fail
    return False


def f19_language_switch(ctx):
    """§11 F19：语言切换必须**真的**能用（真实浏览器行为 + 产物一致性）。

    子条件（任一失败 → F19 FAIL）：
        EN_TO_ZH / ZH_TO_EN / NO_RELOAD_REQUIRED / VISIBLE_LABELS_CHANGED(≥5) /
        PERSISTENCE / ROUTE_PERSISTENCE / DEEP_ROUTE / HTML_LANG_SYNC /
        NO_CONSOLE_ERRORS / SCHOLARLY_CONTENT_MUTATION_0

    基础设施抖动（Chrome/CDP 起不来、证据缺失且无任何断言失败）→ **一次**有界重试，
    并如实记录 attempts 与首次失败原因；断言/行为失败**绝不**重试。
    """
    suite, tests, stderr = _run_i18n_suite(ctx, "attempt1")
    attempts = [{"attempt": 1, "exit": suite["exit"],
                 "tests": {k: (v or {}).get("status") for k, v in sorted(tests.items())},
                 "stderr_tail": stderr[-400:]}]
    infra = _is_infra_failure(suite, tests, stderr)
    if infra:
        time.sleep(5)
        suite, tests, stderr = _run_i18n_suite(ctx, "attempt2")
        attempts.append({"attempt": 2, "exit": suite["exit"],
                         "tests": {k: (v or {}).get("status") for k, v in sorted(tests.items())},
                         "stderr_tail": stderr[-400:]})
    ctx.write_json("i18n/browser_evidence.json", tests)

    def st(name):
        return ((tests.get(name) or {}).get("status"))

    d1 = ((tests.get("test_01_en_to_zh") or {}).get("detail") or {})
    changed = d1.get("changed_labels") or []
    subs = {
        "EN_TO_ZH": st("test_01_en_to_zh") == "PASS",
        "ZH_TO_EN": st("test_02_zh_to_en") == "PASS",
        "NO_RELOAD_REQUIRED": bool(d1.get("no_reload")),
        "VISIBLE_LABELS_CHANGED": len(changed) >= 5,
        "PERSISTENCE": st("test_03_persistence") == "PASS",
        "ROUTE_PERSISTENCE": st("test_04_navigation_persistence") == "PASS",
        "DEEP_ROUTE": st("test_05_deep_route") == "PASS",
        "HTML_LANG_SYNC": st("test_06_html_lang") == "PASS",
        "NO_CONSOLE_ERRORS": st("test_07_no_js_errors") == "PASS",
        "SCHOLARLY_CONTENT_MUTATION_0": st("test_08_scholarly_integrity") == "PASS",
    }
    # §13：产物一致性（磁盘字节 == HTTP 服务字节）
    art = ctx.sh([sys.executable, os.path.join(HERE, "check_ui_artifacts.py"),
                  "--url", ctx.base,
                  "--out", os.path.join(ctx.run_dir, "i18n", "ui_artifacts.json")],
                 timeout=600)
    art_doc = {}
    art_file = os.path.join(ctx.run_dir, "i18n", "ui_artifacts.json")
    if os.path.isfile(art_file):
        with open(art_file, encoding="utf-8") as fh:
            art_doc = json.load(fh)
    # i18n 资源一致性（词典/调用点/index.html key）
    i18n = ctx.sh([sys.executable, os.path.join(HERE, "build_i18n.py"), "--check"],
                  timeout=600)
    ok = (suite["exit"] == 0 and all(subs.values())
          and art["exit"] == 0 and art_doc.get("verdict") == "PASS"
          and i18n["exit"] == 0)
    cat_file = os.path.join(VAULT, "_data", "daily_use", "i18n", "catalog.json")
    ctx.record("F19", ok, {
        "sub_conditions": subs,
        "suite_exit": suite["exit"],
        "suite_attempts": attempts,
        "infra_retry_used": bool(infra),
        "changed_labels": changed,
        "artifact_verdict": art_doc.get("verdict"),
        "artifact_assets_checked": art_doc.get("assets_checked"),
        "artifact_mismatched": art_doc.get("mismatched"),
        "i18n_check_exit": i18n["exit"],
        "catalog_counts": (json.load(open(cat_file, encoding="utf-8"))["counts"]
                           if os.path.isfile(cat_file) else None),
    })


def f16_regression(ctx, skip=False):
    """§50：Phase4 / 4D / 4E / 5A / 5B / 5C / Final Packaging 全量回归。

    权威结果取 `_data/index/TEST_RUN.json`（套件自身写的结构化记录），
    不靠解析 stdout；同时把 stdout 与 TEST_RUN.json 一起存进 run 目录当证据。
    """
    if skip:
        ctx.record("F16", False, {"skipped_by_flag": True})
        return
    started = _now()
    # 高负载/重建缓慢时 F16 可能远超 1 小时（实测某次 test_phase2_deterministic 单套件 ~2.5h）
    r = ctx.sh(["bash", REGRESSION], timeout=21600)
    ctx.write("logs/regression.stdout.txt", r["stdout"])
    ctx.write("logs/regression.stderr.txt", r["stderr"])
    doc_path = os.path.join(VAULT, "_data", "index", "TEST_RUN.json")
    doc = {}
    if os.path.isfile(doc_path):
        with open(doc_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        ctx.write_json("logs/TEST_RUN.json", doc)
    failed = doc.get("failed_suites")
    skipped = doc.get("skipped")
    ok = (r["exit"] == 0 and doc.get("exit_code") == 0
          and failed == [] and skipped == []
          and doc.get("quick_mode") is False
          and (doc.get("suites") or 0) >= 139
          and str(doc.get("recorded_at", "")) >= started)
    ctx.record("F16", ok, {"exit": r["exit"], "exit_code": doc.get("exit_code"),
                           "suites": doc.get("suites"), "checks": doc.get("checks"),
                           "failed": failed if failed is not None else "MISSING",
                           "skipped": skipped if skipped is not None else "MISSING",
                           "quick_mode": doc.get("quick_mode"),
                           "recorded_at": doc.get("recorded_at"),
                           "secs": r["secs"]})


# ══════════════════════════════════════════════════════════════════ P5D-005 F20
def _run_help_suite(ctx, tag):
    """跑一次 P5D-005 首用者任务套件，返回 (exit, tasks, claims, stderr)。"""
    r = ctx.sh([sys.executable, "-m", "unittest", "test_p5d005_help_browser"],
               env={"PYTHONPATH": VAULT}, timeout=3600, cwd=TESTS)
    tasks, claims = {}, {}
    if os.path.isfile(HELP_BROWSER_EVIDENCE):
        with open(HELP_BROWSER_EVIDENCE, encoding="utf-8") as fh:
            tasks = (json.load(fh) or {}).get("tasks") or {}
    if os.path.isfile(HELP_CLAIM_BROWSER):
        with open(HELP_CLAIM_BROWSER, encoding="utf-8") as fh:
            claims = (json.load(fh) or {}).get("claims") or {}
    ctx.write_json("help/browser_tasks_%s.json" % tag, tasks)
    return r, tasks, claims, (r["stderr"] or "")[-1500:]


def _help_infra_failure(suite, tasks, stderr):
    """只有 Chrome/CDP 基础设施抖动才允许一次有界重试；断言失败绝不重试。"""
    if "CDP" in stderr or "无法连上 Chrome DevTools" in stderr or "chrome" in stderr.lower():
        return True
    if not tasks and suite["exit"] != 0:
        return True
    any_fail = any((v or {}).get("status") == "FAIL" for v in tasks.values())
    return bool(suite["exit"] != 0 and not tasks and not any_fail)


def _contextual_help_probe(ctx):
    """§9：每个模块的 contextual help 必须指向**模块专属**帮助页（真实 DOM 读取）。"""
    expects = {"/research": "/help/research", "/explore": "/help/explore",
               "/projects": "/help/projects", "/bibliography": "/help/bibliography",
               "/persons": "/help/persons-cases",
               "/bibliography?import=1": "/help/bibliography",
               "/help": "/help", "/": "/help"}
    out = {}
    for path, want in expects.items():
        dom, meta = _dom(ctx, ctx.page(path),
                         wait_js="!!document.getElementById('contextual-help')")
        m = re.search(r'id="contextual-help"[^>]*href="([^"]+)"', dom)
        if not m:
            m = re.search(r'href="([^"]+)"[^>]*id="contextual-help"', dom)
        got = m.group(1) if m else None
        out[path] = {"href": got, "expected": want, "ok": got == want,
                     "render": meta.get("render_tries")}
    return out


def _homepage_entrypoint_probe(ctx):
    """§2–§6：首页必须是**任务型**且入口是真实链接。"""
    dom, meta = _dom(ctx, ctx.page("/"),
                     wait_js="!!document.querySelector('#home-cards .task-card')")
    order = []
    for tok in ("home-title", "home-hero", "hero-start-research", "hero-first-time",
                "home-cards", "home-flow-steps", "home-quickstart"):
        order.append((tok, tok in dom))
    cards = re.findall(r'class="task-card"[^>]*href="([^"]+)"', dom)
    if not cards:
        cards = re.findall(r'href="([^"]+)"[^>]*class="task-card"', dom)
    flow = re.findall(r'class="flow-step-link"[^>]*href="([^"]+)"', dom)
    if not flow:
        flow = re.findall(r'href="([^"]+)"[^>]*class="flow-step-link"', dom)
    anchors = len(re.findall(r'<a [^>]*href="/', dom))
    ok = (all(v for _k, v in order) and len(cards) >= 6 and len(flow) >= 6
          and anchors >= 10)
    return {"elements": dict(order), "task_cards": cards, "flow_steps": flow,
            "internal_anchors": anchors, "ok": ok, "render": meta.get("render_tries")}


def f20_help_system_effective(ctx):
    """§15 F20：Help 系统必须**真的有效**（不是"文件存在"/"返回 200"）。

    子条件（任一失败 → F20 FAIL）：
        HOMEPAGE_TASK_ENTRYPOINTS / MODULE_DEEP_LINKS / CONTEXTUAL_HELP /
        HELP_INTERNAL_LINKS / BROKEN_LINKS_0 / BROKEN_ANCHORS_0 /
        FIRST_TIME_TASKS_8_8 / DOCUMENTATION_FICTION_0 / CLAIM_PENDING_0 /
        HELP_PAGES_13 / I18N_OK
    """
    # ① 构建 + 链接/claim 报告（带真实 URL 复核）
    build = ctx.sh([sys.executable, BUILD_HELP, "--build", "--url", ctx.base],
                   timeout=900)
    link = {}
    if os.path.isfile(HELP_LINK_REPORT):
        with open(HELP_LINK_REPORT, encoding="utf-8") as fh:
            link = json.load(fh)
    claims = {}
    if os.path.isfile(HELP_CLAIM_REPORT):
        with open(HELP_CLAIM_REPORT, encoding="utf-8") as fh:
            claims = json.load(fh)
    ctx.write_json("help/link_report.json", link)
    ctx.write_json("help/claim_report.json", claims)

    # ② 真实浏览器：8 个首用者任务 + element claims（含一次有界 infra 重试）
    suite, tasks, elem, stderr = _run_help_suite(ctx, "attempt1")
    attempts = [{"attempt": 1, "exit": suite["exit"],
                 "tasks": {k: (v or {}).get("status") for k, v in sorted(tasks.items())},
                 "stderr_tail": stderr[-300:]}]
    infra = _help_infra_failure(suite, tasks, stderr)
    if infra:
        time.sleep(5)
        suite, tasks, elem, stderr = _run_help_suite(ctx, "attempt2")
        attempts.append({"attempt": 2, "exit": suite["exit"],
                         "tasks": {k: (v or {}).get("status")
                                   for k, v in sorted(tasks.items())},
                         "stderr_tail": stderr[-300:]})
    ctx.write_json("help/browser_tasks.json", tasks)

    done = {k: (v or {}).get("status") for k, v in tasks.items()}
    tasks_ok = all(done.get(t) == "PASS" for t in HELP_TASK_IDS)

    # ③ 首页任务入口 + 模块 contextual help（真实 DOM）
    home = _homepage_entrypoint_probe(ctx)
    ctx.write_json("help/homepage_entrypoints.json", home)
    ctx_help = _contextual_help_probe(ctx)
    ctx.write_json("help/contextual_help.json", ctx_help)
    ctx_ok = all(v["ok"] for v in ctx_help.values())

    # ④ i18n（Help 走既有词典）
    i18n = ctx.sh([sys.executable, os.path.join(HERE, "build_i18n.py"), "--check"],
                  timeout=600)

    subs = {
        "HOMEPAGE_TASK_ENTRYPOINTS": bool(home.get("ok")),
        "MODULE_DEEP_LINKS": ctx_ok,
        "CONTEXTUAL_HELP": ctx_ok,
        "HELP_INTERNAL_LINKS": link.get("broken_internal_links") == 0,
        "BROKEN_LINKS_0": link.get("broken_internal_links") == 0,
        "BROKEN_ANCHORS_0": link.get("broken_anchors") == 0
                            and link.get("broken_module_deep_links") == 0,
        "FIRST_TIME_TASKS_8_8": tasks_ok,
        "DOCUMENTATION_FICTION_0": claims.get("documentation_fiction") == 0,
        "CLAIM_PENDING_0": claims.get("pending_n") == 0,
        "CLAIM_VERIFIED_ALL": (claims.get("verified_n") or 0) == (claims.get("claims_n") or -1),
        "HELP_PAGES_13": link.get("help_pages") == 13,
        "I18N_OK": i18n["exit"] == 0,
        "ELEMENT_CLAIMS_BROWSER": bool(elem) and all(
            (v or {}).get("status") == "PASS" for v in elem.values()),
    }
    ok = suite["exit"] == 0 and all(subs.values())
    ctx.record("F20", ok, {
        "sub_conditions": subs,
        "suite_exit": suite["exit"],
        "suite_attempts": attempts,
        "infra_retry_used": bool(infra),
        "tasks": done,
        "tasks_n": len(HELP_TASK_IDS),
        "help_pages": link.get("help_pages"),
        "internal_links": link.get("internal_links"),
        "broken_internal_links": link.get("broken_internal_links"),
        "broken_anchors": link.get("broken_anchors"),
        "module_deep_links": link.get("module_deep_links"),
        "contextual_help": {k: v["href"] for k, v in ctx_help.items()},
        "homepage_task_cards": home.get("task_cards"),
        "homepage_flow_steps": home.get("flow_steps"),
        "claims": {"n": claims.get("claims_n"), "verified": claims.get("verified_n"),
                   "pending": claims.get("pending_n"),
                   "fiction": claims.get("documentation_fiction")},
        "build_exit": build["exit"],
        "i18n_check_exit": i18n["exit"],
        "findability": (json.load(open(HELP_BROWSER_EVIDENCE, encoding="utf-8"))
                        .get("findability") if os.path.isfile(HELP_BROWSER_EVIDENCE)
                        else None),
    })

# ────────────────────────────────────────────────────────────── 主流程
# 顺序：先做接口级（start/double-start/browser-open/stale-PID/stop 的语义），
# 再做 UI/浏览器证据（F6–F13），最后 stop + 扫描 + 全量回归。
# ⚠️ F13 会临时起第二个实例（无凭据 HOME），放在后面，避免与 F3 的资源峰值叠加。
ORDER = ["F17", "F18", "F15", "F1", "F3", "F5", "F4", "F6", "F7", "F8", "F9", "F10",
         "F11", "F12", "F13", "F14", "F19", "F20", "F2", "F16"]


def run_acceptance(port, only=None, skip_regression=False, keep_vault=False,
                   version="v2"):
    gate_file = gate_path(version)
    if not os.path.isfile(gate_file):
        print("GATE_NOT_FROZEN: run --freeze-gate --gate %s first" % version)
        return 3
    with open(gate_file, encoding="utf-8") as fh:
        gate = json.load(fh)
    if gate.get("gate_hash") != gate_hash(gate):
        print("GATE_TAMPERED")
        return 3
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rid = _sha(ts + str(os.getpid()))[:8]
    run_dir = os.path.join(RUN_ROOT,
                           "daily_use_bibliography_acceptance_%s_%s" % (ts, rid))
    if os.path.exists(run_dir):
        print("RUN_DIR_EXISTS: %s" % run_dir)
        return 3
    os.makedirs(run_dir)                      # immutable：独占创建，绝不覆盖
    ctx = Ctx(port, run_dir)
    t0 = time.time()
    print("RUN %s" % os.path.relpath(run_dir, VAULT))
    payload = {
        "schema_version": "daily-use-bibliography-acceptance/v1",
        "run_id": os.path.basename(run_dir),
        "created_at": _now(),
        "gate": {"gate_id": gate.get("gate_id"), "gate_hash": gate.get("gate_hash"),
                 "items_n": gate.get("items_n"), "frozen_at": gate.get("frozen_at")},
        "port": port,
        "host": os.uname().nodename,
        "python": sys.version.split()[0],
        "head_before": _head(),
        "checks": {}, "timing": {}, "notes": [],
    }
    checks = {"F1": f1_start, "F2": f2_stop, "F3": f3_double_start,
              "F4": f4_stale_pid, "F5": f5_browser_open, "F6": f6_homepage,
              "F7": f7_bibliography_ui, "F8": f8_candidate_never_citable,
              "F9": f9_no_fake_citation, "F10": f10_zotero_import_always_candidate,
              "F11": f11_conflict_not_resolved, "F12": f12_obsidian_user_content,
              "F13": f13_provider_unavailable, "F14": f14_secrets,
              "F15": f15_semantic_drift, "F17": f17_core_freeze,
              "F18": f18_freeze_lineage, "F19": f19_language_switch,
              "F20": f20_help_system_effective}
    todo = [f for f in ORDER if (not only or f in only)]
    order = [f for f in ORDER if f in todo]
    for fid in order:
        t = time.time()
        if fid == "F16":
            f16_regression(ctx, skip=skip_regression)
        else:
            try:
                checks[fid](ctx)
            except Exception as exc:                                       # noqa: BLE001
                ctx.record(fid, False, {"exception": "%s: %s" % (type(exc).__name__,
                                                                 str(exc)[:200])})
        ctx.timing[fid] = round(time.time() - t, 2)
        # 增量落盘（崩溃也不丢证据）
        payload["checks"] = ctx.checks
        payload["timing"] = ctx.timing
        ctx.write_json("summary.json", payload)
    payload["checks"] = ctx.checks
    payload["timing"] = ctx.timing
    payload["finished_at"] = _now()
    payload["total_secs"] = round(time.time() - t0, 2)
    payload["head_after"] = _head()
    payload["head_unchanged"] = payload["head_before"] == payload["head_after"]
    payload["failed"] = sorted([k for k, v in ctx.checks.items() if v["status"] != "PASS"])
    payload["passed"] = sorted([k for k, v in ctx.checks.items() if v["status"] == "PASS"])
    payload["verdict"] = ("COMPLETE" if not payload["failed"] and len(order) == gate["items_n"]
                          else ("PARTIAL_ALL_PASS" if not payload["failed"] else "FAILED"))
    ctx.write_json("gate.json", gate)
    ctx.write_json("summary.json", payload)
    ctx.write("REPORT.md", _report(payload))
    print("RUN_DONE %s failed=%s verdict=%s secs=%s"
          % (payload["run_id"], payload["failed"], payload["verdict"],
             payload["total_secs"]))
    return 0 if payload["verdict"] == "COMPLETE" else 1


def _head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=VAULT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:                                                      # noqa: BLE001
        return "unknown"


def _report(payload):
    L = ["# Final Daily Use Gate v1 — 验收记录", "",
         "- run_id: `%s`" % payload["run_id"],
         "- gate: `%s` (hash `%s`, %s items)"
         % (payload.get("gate", {}).get("gate_id"), payload.get("gate", {}).get("gate_hash"),
            payload.get("gate", {}).get("items_n")),
         "- started: %s / finished: %s / total %ss"
         % (payload.get("created_at"), payload.get("finished_at"),
            payload.get("total_secs")),
         "- HEAD before/after: `%s` / `%s` (unchanged=%s)"
         % (payload.get("head_before"), payload.get("head_after"),
            payload.get("head_unchanged")),
         "- verdict: **%s**" % payload["verdict"], "", "## F1–F18", "",
         "| item | status | detail | secs |", "| --- | --- | --- | --- |"]
    for fid, title in F_ITEMS + [F19]:
        c = payload["checks"].get(fid)
        if not c:
            L.append("| %s %s | NOT_RUN | — | — |" % (fid, title))
            continue
        L.append("| %s %s | **%s** | `%s` | %s |"
                 % (fid, title, c["status"],
                    json.dumps(c["detail"], ensure_ascii=False)[:600],
                    payload["timing"].get(fid)))
    L += ["", "## 未通过项", ""]
    L += (["- " + f for f in payload["failed"]] or ["（无）"])
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Final Daily Use Gate v1 acceptance")
    ap.add_argument("--freeze-gate", action="store_true")
    ap.add_argument("--gate", default=None, choices=["v1", "v2", "v3"],
                    help="Gate 版本；--freeze-gate 缺省 v1（保持既有套件行为），"
                         "--run 缺省 v2（含 F19）；v3 = v2 + F20（Help 系统有效）")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--require-existing", action="store_true")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LACAN_UI_PORT", "3090")))
    ap.add_argument("--skip-regression", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--keep-vault", action="store_true")
    a = ap.parse_args(argv)
    if a.freeze_gate:
        return cmd_gate_freeze(require_existing=a.require_existing,
                               version=(a.gate or "v1"))
    if a.run:
        only = set(x.strip() for x in a.only.split(",")) if a.only else None
        return run_acceptance(a.port, only=only, skip_regression=a.skip_regression,
                              keep_vault=a.keep_vault, version=(a.gate or "v2"))
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
