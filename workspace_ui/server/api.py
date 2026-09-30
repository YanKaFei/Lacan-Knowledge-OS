#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workspace_ui.server.api — 产品 API 层（HTTP 处理器调用的纯函数）

路径（§5）：`UI → api → MCP → scholarly_api → FROZEN CORE`。
本模块**不** import 核心；每一次学术取数都经 MCP。
"""
from __future__ import annotations

import json
import os
import time

from . import config as C
from . import history as H
from . import provider_view as PV
from . import viewmodel as VM
from .mcp_client import McpUnavailable, shared_client

# 产品级请求缓存：同一冻结输入 → 同一输出（§21 性能；可重建的机器数据）
_CACHE = {}

# ★ 只有**基础设施类**失败才值得重发一次：端点抖动/超时/连不上。
#   学术判定类结果（VALIDATION_FAILED / ABSTAINED / INSUFFICIENT_EVIDENCE）
#   **永不重试** —— 重试一个判定不会让它变成证据，只会掩盖结论。
RETRYABLE_CODES = ("PROVIDER_UNAVAILABLE", "PROVIDER_CALL_FAILED")
MAX_ATTEMPTS = 2


def _cache_key(tool, args):
    return "%s::%s" % (tool, json.dumps(args, ensure_ascii=False, sort_keys=True))


def _unavailable_reason():
    """MCP 不可用时**如实**给出已知原因，返回 (code, error_body)。

    为什么需要（Phase 5A P5A-007，实测）：过去一律翻成 `INDEX_UNAVAILABLE`，
    用户读到的是「检索索引不可用，可从语料重建」——**与真因无关**，而且会误导
    用户去重建索引。真因通常就在手边：`status()["core_freeze"]["reason"]`
    （例如 `FREEZE_DRIFT`：冻结核心哈希对不上 → fail closed）。

    只用**已知的结构化状态**判定，不做文本猜测。
    """
    try:
        st = status()
    except Exception:                                                     # noqa: BLE001
        st = {}
    cf = st.get("core_freeze") or {}
    if st and not st.get("core_freeze_verified"):
        return ("CORE_FROZEN_MISMATCH",
                {"message": "Frozen scholarly core integrity check failed",
                 "detail": {"reason": cf.get("reason"),
                            "verify_output": (cf.get("stdout") or "")[:400]},
                 "resolution": ("先跑 `python3 _scripts/_tools/core_freeze.py --verify` "
                                "看差异；核心变更必须走 CORE_CHANGE_REQUEST + "
                                "新的补救阶段，产品层不得改核心。")})
    return ("INDEX_UNAVAILABLE",
            {"message": "MCP interface unavailable",
             "resolution": "启动 mcp_server/server.py 后重试"})


def _call(tool, args, use_cache=True, trace=None):
    key = _cache_key(tool, args)
    if use_cache and C.CACHE_ENABLED and key in _CACHE:
        if trace is not None:
            trace["cached"] = True
        return _CACHE[key]
    if trace is not None:
        trace["cached"] = False
    try:
        env = shared_client().call_tool(tool, args)
    except McpUnavailable as exc:
        code, body = _unavailable_reason()
        env = {"ok": False,
               "error": {"code": code,
                         "message": body["message"],
                         "detail": {"mcp": exc.detail,
                                    "reason": (body.get("detail") or {}).get("reason")},
                         "resolution": body["resolution"]},
               "meta": {}}
    if use_cache and C.CACHE_ENABLED and env and env.get("ok"):
        _CACHE[key] = env
    return env


def clear_cache():
    _CACHE.clear()


def status():
    try:
        return VM.status_view(shared_client().status())
    except McpUnavailable as exc:
        return VM.status_view({"connected": False, "core_freeze_verified": False,
                               "detail": exc.detail})


def _research_once(q, mode, provider, language, use_cache, trace):
    """一次真实的 MCP 研究往返，返回 (view, env)。"""
    args = {"question": q, "mode": (None if mode in (None, "auto") else mode),
            "provider": provider, "language": language}
    args = {k: v for k, v in args.items() if v is not None}
    env = _call("lacan.research", args, use_cache=use_cache, trace=trace)
    view = VM.answer_view(env)
    if view.get("code") == "INTERNAL_ERROR" and _is_provider_failure(env):
        view = {"kind": "error", "code": "PROVIDER_UNAVAILABLE",
                "title": C.ERROR_UX["PROVIDER_UNAVAILABLE"]["title"],
                "body": C.ERROR_UX["PROVIDER_UNAVAILABLE"]["body"],
                "research_disabled": False,
                "advanced": {"provider": provider,
                             "core_error": (env.get("error") or {}).get("code"),
                             "core_detail": str((env.get("error") or {}).get(
                                 "detail"))[:200]}}
    return view, env


def _provenance(provider, model, wall_ms, cached, attempts, retry_reason, fresh, tz=None):
    """产品层**实测**溯源：谁回答的、哪个模型、等了多久、命中缓存没有、发了几次。

    这些字段全部由产品层自己产生（计时/缓存/重试计数），
    冻结核心的 `advanced` 原字段**只增不改、不改语义**。
    """
    return {"provider": provider,
            "provider_model": (model if provider == "llm" else None),
            "provider_model_note": (None if provider == "llm"
                                    else "no model call (deterministic mock adapter)"),
            "wall_ms": wall_ms,
            "cached": bool(cached),
            "attempts": attempts,
            "retry_reason": retry_reason,
            "fresh_requested": bool(fresh)}


def research(question, mode="scholarly", provider=None, language=None,
             save_history=True, use_cache=True, retry=True):
    """→ {view, saved?, request}；research_disabled 时直接返回错误视图（fail closed）。

    ★ 相对冻结核心**只加不减**的产品层能力（全部可关，不改任何 scholarly 语义）：
      * `use_cache=False`（UI 的"强制新算"）→ 绕过产品缓存重跑一次；
      * `retry`：**只**对基础设施类失败（PROVIDER_UNAVAILABLE /
        PROVIDER_CALL_FAILED）**多试一次**，学术判定类结果永不重试；
      * `advanced` 里追加产品层实测溯源（模型名/耗时/是否缓存/尝试次数）。
    """
    st = status()
    if st.get("research_disabled"):
        # ★ P5A-007：研究被禁用时**如实**区分「核心冻结不符」与「MCP 离线」。
        if not st.get("core_freeze_verified"):
            code, body = "CORE_FROZEN_MISMATCH", None
        elif not st.get("mcp_connected"):
            code, body = None, {"title": "MCP research interface is offline.",
                                "body": "Start the MCP service to research the corpus."}
        else:
            code, body = "CORE_FROZEN_MISMATCH", None
        ux = C.ERROR_UX[code] if code else body
        return {"view": {"kind": "error", "code": code or "INDEX_UNAVAILABLE",
                         "title": ux["title"], "body": ux["body"],
                         "research_disabled": True, "advanced": {}},
                "saved": None, "status": st}
    provider = provider or C.DEFAULT_PROVIDER
    q = (question or "").strip()
    if len(q) < 4:
        return {"view": {"kind": "error", "code": "INVALID_REQUEST",
                         "title": C.ERROR_UX["INVALID_REQUEST"]["title"],
                         "body": C.ERROR_UX["INVALID_REQUEST"]["body"],
                         "research_disabled": False, "advanced": {}},
                "saved": None, "status": st}
    if len(q) > C.MAX_QUESTION_LEN:
        # 学术纪律：**绝不静默截断**问题（截断等于换了一个研究问题）。
        return {"view": {"kind": "error", "code": "INVALID_REQUEST",
                         "title": "The question is too long.",
                         "body": "Questions are limited to %d characters; "
                                 "nothing was truncated or sent to the core."
                                 % C.MAX_QUESTION_LEN,
                         "research_disabled": False,
                         "advanced": {"max_question_len": C.MAX_QUESTION_LEN}},
                "saved": None, "status": st}
    # ⚠️ 4D.7 验收发现：provider=llm 且没有凭据时，核心会拒绝合成并返回
    #    PROVIDER_CALL_FAILED，UI 层却显示 INTERNAL_ERROR —— 用户看到的应该是
    #    PRODUCT 自己 ERROR_UX 里那条「真实 LLM 不可用，且**不会**用模型知识兜底」。
    #    这里只做**错误码映射**（fail closed 语义不变；仍然不 fallback、不补答）。
    if provider == "llm" and not _provider_credentials_present():
        view = {"kind": "error", "code": "PROVIDER_UNAVAILABLE",
                "title": C.ERROR_UX["PROVIDER_UNAVAILABLE"]["title"],
                "body": C.ERROR_UX["PROVIDER_UNAVAILABLE"]["body"],
                "research_disabled": False,
                "advanced": {"provider": provider, "credentials": "absent"},
                "actions": [{"id": "provider_settings",
                             "label": "Open provider settings"}]}
        return {"view": view, "saved": None, "status": st}

    t0 = time.time()
    trace = {}
    view, env = _research_once(q, mode, provider, language, use_cache, trace)
    attempts, retry_reason = 1, None
    if (retry and use_cache and provider == "llm"
            and view.get("code") in RETRYABLE_CODES
            and _provider_credentials_present()):
        # 只重发一次，且第二次**绕过缓存**；重试的原因如实记在 retry_reason 里。
        retry_reason = view.get("code")
        attempts = 2
        view, env = _research_once(q, mode, provider, language, False, {})
    wall_ms = int((time.time() - t0) * 1000)
    adv = view.setdefault("advanced", {})
    adv.update(_provenance(provider, PV.effective()["model"], wall_ms,
                           trace.get("cached"), attempts, retry_reason,
                           not use_cache))
    if view.get("code") in RETRYABLE_CODES:
        # 失败后给出**可操作的下一步**（重试一次 / 去设置看模型与端点）。
        view.setdefault("actions", [])
        view["actions"] = ([{"id": "retry_once", "label": "Retry once"}]
                           + [a for a in view["actions"] if a.get("id") != "retry_once"]
                           + [{"id": "provider_settings",
                               "label": "Open provider settings"}])
    saved = None
    if save_history and view.get("kind") == "answer" and view.get("advanced", {}).get(
            "request_id"):
        try:
            saved = H.save(q, view, {"mode": mode, "provider": provider,
                                     "language": language})
        except Exception as exc:                            # noqa: BLE001
            saved = {"error": "HISTORY_SAVE_FAILED", "detail": str(exc)[:200]}
    if view.get("code") == "CORE_FROZEN_MISMATCH":
        view["research_disabled"] = True
    return {"view": view, "saved": saved, "status": st}



def _provider_credentials_present():
    """真实 provider 是否具备凭据（**只看有没有**，不验证有效性、不读取/不打印内容）。

    ⚠️ 4D.7 验收发现（产品层缺陷，已修）：原实现探测 `DEEPSEEK_API_KEY` /
    `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 三个环境变量，而**核心根本不读这三个**
    —— 冻结核心只认 `DSH_SYNTHESIS_API_KEY` 环境变量，或
    `~/.dsh/.credentials.yaml` 里的 `DEEPSEEK_API_KEY:` 行
    （`_scripts/_tools/run_synthesis_4c1d.py::load_dsh_key`）。
    探测错源会产生**假阴性**：用户按核心的真实机制配好了凭据，产品却以
    「provider 不可用」拒答。这里与核心实现**逐条对齐**，语义仍然是 fail closed
    （不 fallback、不用模型知识兜底），只是「有没有凭据」这一判断不再失真。
    """
    import os as _os                                                    # noqa: PLC0415
    import re as _re                                                    # noqa: PLC0415
    if _os.environ.get("DSH_SYNTHESIS_API_KEY"):
        return True
    path = _os.path.expanduser("~/.dsh/.credentials.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if _re.match(r"\s*DEEPSEEK_API_KEY:\s*\S+\s*$", line):
                    return True
    except OSError:
        return False
    return False


def _is_provider_failure(env):
    """核心把 provider 调用失败映射成 PROVIDER_CALL_FAILED（内部码）。"""
    err = (env or {}).get("error") or {}
    detail = err.get("detail") or {}
    api_code = (detail or {}).get("api_error_code") if isinstance(detail, dict) else None
    blob = json.dumps(err, ensure_ascii=False).lower()
    return api_code in ("PROVIDER_CALL_FAILED", "PROVIDER_UNAVAILABLE") \
        or "provider" in blob and ("credential" in blob or "unavailable" in blob
                                   or "调用失败" in blob)


def passage_panel(passage_id, before=C.DEFAULT_CONTEXT, after=C.DEFAULT_CONTEXT,
                  quoted_span=None):
    before = max(0, min(int(before or 0), C.MAX_CONTEXT_BEFORE))
    after = max(0, min(int(after or 0), C.MAX_CONTEXT_AFTER))
    p = _call("lacan.get_passage", {"passage_id": passage_id})
    v = VM.passage_panel_view(p, quoted_span=quoted_span)
    if v.get("kind") == "error":
        return v
    ctx = _call("lacan.get_context", {"passage_id": passage_id,
                                      "before": before, "after": after})
    tr = _call("lacan.trace_source", {"passage_id": passage_id})
    return VM.passage_panel_view(p, ctx, tr, quoted_span=quoted_span)


def context_window(passage_id, before, after):
    before = max(0, min(int(before or 0), C.MAX_CONTEXT_BEFORE))
    after = max(0, min(int(after or 0), C.MAX_CONTEXT_AFTER))
    env = _call("lacan.get_context", {"passage_id": passage_id,
                                     "before": before, "after": after})
    if not env.get("ok"):
        return VM.error_view(env)
    res = env.get("result") or {}
    return {"kind": "context", "passage_id": res.get("passage_id"),
            "before": res.get("before"), "after": res.get("after"),
            "items": [{"passage_id": i.get("passage_id"), "text": i.get("text"),
                       "language": i.get("language"), "seminar": i.get("seminar"),
                       "session": i.get("session")}
                      for i in (res.get("items") or [])]}


def search(query, limit=10):
    """§31：MVP 里放在 Advanced 的简易检索。"""
    env = _call("lacan.search_passages", {"query": query, "limit": limit})
    if not env.get("ok"):
        return VM.error_view(env)
    res = env.get("result") or {}
    meta = env.get("meta") or {}
    return {"kind": "search", "query": res.get("query"),
            "n": res.get("n"), "dense_available": meta.get("dense_available"),
            "results": [{"passage_id": e.get("passage_id"),
                         "label": VM.citation_label(e.get("passage_id")),
                         "snippet": (e.get("text") or "")[:220],
                         "seminar": e.get("seminar"), "language": e.get("language"),
                         "source_layer": e.get("source_layer"),
                         "provenance_status": e.get("provenance_status")}
                        for e in (res.get("evidence") or [])]}


def obsidian_status():
    """Obsidian 工作区状态（供 UI 显示 vault 与已保存数量）。

    ★ P5D-005-T2（实测缺陷）：首页 `Open Obsidian` 读的是 `vault_uri/open_uri/obsidian_uri`，
    而本接口从不返回它们 —— 于是按钮永远落到「未配置 URI」分支，还会打印 `unknown`。
    这里补上**打开 vault 本身**的 `obsidian://open?vault=<name>`（用既有适配器的命名规则，
    不做任何 shell 调用、不写入任何内容）。
    """
    try:
        from obsidian_adapter import adapter as OA                      # noqa: PLC0415
        from urllib.parse import quote                                  # noqa: PLC0415
        st = OA.vault_status()
        root = st.get("active_root") or (st.get("detection") or {}).get(
            "default_workspace_root")
        uri = ("obsidian://open?vault=%s" % quote(os.path.basename(root))
               if root else None)
        return {"kind": "obsidian_status", "ok": True, "vault_uri": uri,
                "open_uri": uri, "workspace_root": root, **st}
    except Exception as exc:                                            # noqa: BLE001
        return {"kind": "obsidian_status", "ok": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(exc)[:200]}}


def obsidian_save_research(question, mode="scholarly", provider=None, language=None):
    """研究 → Save to Obsidian（用**同一次**研究工作区的 ViewModel；不重跑 LLM）。"""
    out = research(question, mode=mode, provider=provider, language=language,
                   save_history=False)
    view = out["view"]
    if view.get("kind") != "answer":
        return {"ok": False, "error": "NOT_AN_ANSWER", "view_kind": view.get("kind")}
    try:
        from obsidian_adapter import adapter as OA                      # noqa: PLC0415
        res = OA.save_research(view)
    except Exception as exc:                                            # noqa: BLE001
        return {"ok": False, "error": "SAVE_FAILED", "detail": str(exc)[:200]}
    return {"kind": "obsidian_save", **res, "answer_state": view.get("state")}


def obsidian_save_passage(passage_id):
    try:
        from obsidian_adapter import adapter as OA                      # noqa: PLC0415
        res = OA.save_passage(passage_id)
    except Exception as exc:                                            # noqa: BLE001
        return {"ok": False, "error": "SAVE_FAILED", "detail": str(exc)[:200]}
    return {"kind": "obsidian_save", **res}


def obsidian_list():
    try:
        from obsidian_adapter import adapter as OA                      # noqa: PLC0415
        return {"kind": "obsidian_list", "ok": True, **OA.list_saved_research()}
    except Exception as exc:                                            # noqa: BLE001
        return {"ok": False, "error": {"code": "INTERNAL_ERROR",
                                       "message": str(exc)[:200]}}


def history_list(limit=50, offset=0):
    return H.list_items(limit=limit, offset=offset)


def history_get(file_name):
    rec = H.get(file_name)
    return rec or {"error": "HISTORY_NOT_FOUND"}
