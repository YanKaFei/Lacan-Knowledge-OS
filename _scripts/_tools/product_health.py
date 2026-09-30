#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
product_health.py — Phase 4D.7 §77/§78：产品健康检查

分层报告，**不把 LLM provider 的可用性当成整个产品的死活**：

    Core / MCP / Browse / Workspace / Obsidian / Exports / Provider

每层 READY / DEGRADED / BLOCKED，最后汇总：
    READY    —— 核心层全部可用（离线/mock 模式也算 READY）
    DEGRADED —— 部分能力不可用（例如真实 LLM provider 缺凭据、导出目录不可写）
    BLOCKED  —— 学术核心不可用（core freeze 校验失败 / 语料存储缺失）

用法：
    python3 _scripts/_tools/product_health.py            # 人读
    python3 _scripts/_tools/product_health.py --json      # 机器读
退出码：0 = READY，1 = DEGRADED，2 = BLOCKED。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)


def _freeze():
    r = subprocess.run([sys.executable, os.path.join(HERE, "core_freeze.py"),
                        "--verify", "--quiet"], capture_output=True, text=True, cwd=VAULT)
    return r.returncode == 0, (r.stdout + r.stderr)[-200:]


def check():
    layers = {}

    # 1 学术核心（core freeze）
    ok, detail = _freeze()
    layers["core"] = {"status": "READY" if ok else "BLOCKED",
                      "detail": ("core freeze 39/39 校验通过" if ok else detail),
                      "blocking": not ok}

    # 2 语料存储 / browse
    try:
        import browse_api as B
        avail = B.availability()
        n = B.corpus_total()
        ok = bool(avail["lexical_index"] and n > 0)
        layers["corpus_store"] = {
            "status": "READY" if ok else "BLOCKED",
            "detail": "passage store %d 段；lexical=%s；ontology=%s"
                      % (n, avail["lexical_index"], avail["ontology"]),
            "blocking": not ok}
        layers["browse"] = {
            "status": "READY" if ok else "BLOCKED",
            "detail": "dense=%s（%s）；retrieval=%s"
                      % (avail["dense_available"], avail["dense_reason"],
                         avail["retrieval_mode"]),
            "blocking": False,
            "note": ("dense 不可用是**已知限制**，不是产品故障："
                     "lexical browse 仍可用，UI 会如实提示。" if not avail[
                         "dense_available"] else None)}
    except Exception as exc:                                              # noqa: BLE001
        layers["corpus_store"] = {"status": "BLOCKED", "detail": str(exc)[:200],
                                  "blocking": True}
        layers["browse"] = {"status": "BLOCKED", "detail": str(exc)[:200],
                            "blocking": True}

    # 3 MCP
    try:
        from mcp_server.guard import verify_core_freeze
        ok, detail = verify_core_freeze()
        layers["mcp"] = {"status": "READY" if ok else "BLOCKED",
                         "detail": ("MCP 接口与 core freeze 一致" if ok
                                    else str(detail)[:200]),
                         "blocking": not ok}
    except Exception as exc:                                              # noqa: BLE001
        layers["mcp"] = {"status": "BLOCKED", "detail": str(exc)[:200],
                         "blocking": True}

    # 4 Workspace（HTTP 服务能力 + 历史目录可写）
    try:
        from scholarly_api import policy as POL
        from workspace_ui.server import config as C
        cls_hist = POL.classify(os.path.join(C.HISTORY_DIR, "x.json"))
        ok = cls_hist == "USER_WORKSPACE"
        layers["workspace"] = {"status": "READY" if ok else "DEGRADED",
                               "detail": "history dir = %s；workspace=%s"
                                         % (cls_hist, C.WORKSPACE_VERSION),
                               "blocking": not ok}
    except Exception as exc:                                              # noqa: BLE001
        layers["workspace"] = {"status": "BLOCKED", "detail": str(exc)[:200],
                               "blocking": True}

    # 5 Obsidian（vault 检测 + 工作区可写）
    try:
        from obsidian_adapter import adapter as OA
        from obsidian_adapter import vault as OV
        det = OV.detect()
        v = OV.Vault()
        ok = bool(det["is_obsidian_vault"]) and POL_classify_ok(v.root)
        layers["obsidian"] = {
            "status": "READY" if ok else "DEGRADED",
            "detail": "vault=%s；workspace root=%s；notes=%s"
                      % (det["is_obsidian_vault"], os.path.relpath(v.root, VAULT),
                         OA.vault_status().get("counts")),
            "blocking": False}
    except Exception as exc:                                              # noqa: BLE001
        layers["obsidian"] = {"status": "DEGRADED", "detail": str(exc)[:200],
                              "blocking": False}

    # 6 Exports（导出根可写）
    try:
        import export_system as EX
        root = EX.export_root()
        ok = os.path.isdir(root)
        layers["exports"] = {"status": "READY" if ok else "DEGRADED",
                             "detail": "export root = %s（%d 个工件）"
                                       % (os.path.relpath(root, VAULT),
                                          len(EX.list_exports()["items"])),
                             "blocking": not ok}
    except Exception as exc:                                              # noqa: BLE001
        layers["exports"] = {"status": "DEGRADED", "detail": str(exc)[:200],
                             "blocking": False}

    # 7 Projects
    try:
        import project_api as PA
        n = PA.list_projects()["total"]
        # ⚠️ 4D.7：真正的根在 `project_api.store.PROJECTS_DIR`（可被隔离探针替换），
        #    包级 `PA.PROJECTS_DIR` 是导入时的快照 —— 读它会报出**错的**根目录，
        #    验收时看起来像「隔离失效」（实测踩过）。
        root = os.path.join(VAULT, PA.PROJECTS_REL) if hasattr(PA, "PROJECTS_REL") \
            else PA.PROJECTS_DIR
        try:
            root = PA.store.PROJECTS_DIR
        except Exception:                                                 # noqa: BLE001
            pass
        layers["projects"] = {"status": "READY",
                              "detail": "%d 个项目；root=%s"
                                        % (n, os.path.relpath(root, VAULT)),
                              "blocking": False}
    except Exception as exc:                                              # noqa: BLE001
        layers["projects"] = {"status": "DEGRADED", "detail": str(exc)[:200],
                              "blocking": False}

    # 8 Provider（**与其他层分开**：缺凭据不影响离线产品可用性）
    try:
        from mcp_server import config as MC
        # ★ P5A-008：凭据探测必须与产品/核心**同一真相源**。
        #   历史缺陷：这里探的是 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY
        #   三个环境变量，而冻结核心只认 `DSH_SYNTHESIS_API_KEY` 或
        #   `~/.dsh/.credentials.yaml` 的 `DEEPSEEK_API_KEY:` 行 —— 于是用户按核心的
        #   真实机制配好凭据后，健康检查仍报 DEGRADED（假阴性），而 UI 报 READY，
        #   两个组件自相矛盾。这里**复用**产品层的同一个探针，不再各自维护一份。
        try:
            from workspace_ui.server.api import _provider_credentials_present as _probe
            has_key = bool(_probe())
        except Exception:                                                 # noqa: BLE001
            has_key = bool(os.environ.get("DSH_SYNTHESIS_API_KEY")) or os.path.isfile(
                os.path.expanduser("~/.dsh/.credentials.yaml"))
        layers["provider"] = {
            "status": "READY" if has_key else "DEGRADED",
            "detail": ("真实 LLM provider 凭据已配置" if has_key
                       else "真实 LLM provider 不可用（无凭据）—— "
                            "离线/mock 模式仍完全可用；系统**不会**用模型知识兜底"),
            "blocking": False,
            "default_provider": getattr(MC, "DEFAULT_PROVIDER", "mock")}
    except Exception as exc:                                              # noqa: BLE001
        layers["provider"] = {"status": "DEGRADED", "detail": str(exc)[:200],
                              "blocking": False}

    blocking = [k for k, v in layers.items() if v.get("blocking")]
    degraded = [k for k, v in layers.items()
                if v["status"] == "DEGRADED" and not v.get("blocking")]
    overall = "BLOCKED" if blocking else ("DEGRADED" if degraded else "READY")
    return {"kind": "product_health", "overall": overall, "layers": layers,
            "blocking_layers": blocking, "degraded_layers": degraded,
            "offline_capable": not blocking,
            "note": ("Provider 可用性与产品可用性分开判定：真实 LLM 缺凭据只会让"
                     "provider 层 DEGRADED，离线/mock 研究仍然可用。")}


def POL_classify_ok(root):
    try:
        from scholarly_api import policy as POL
        return POL.classify(os.path.join(root, "Research", "x.md")) == "USER_WORKSPACE"
    except Exception:                                                     # noqa: BLE001
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lacan Knowledge OS — product health")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = check()
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("Lacan Knowledge OS — health: %s" % out["overall"])
        for name, layer in out["layers"].items():
            print("  %-14s %-9s %s" % (name, layer["status"], layer["detail"]))
        if out["degraded_layers"]:
            print("  （DEGRADED 不阻塞：%s）" % ", ".join(out["degraded_layers"]))
    return {"READY": 0, "DEGRADED": 1, "BLOCKED": 2}[out["overall"]]


if __name__ == "__main__":
    raise SystemExit(main())
