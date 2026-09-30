#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.tools — Phase 4D.1 工具执行层（10 个只读工具）

每个工具的执行链（§20，fail closed）：

    input schema validate  →  scholarly_api  →  output schema validate
                           ↘  失败即返回结构化 ApiError（绝不 best-effort 输出）

硬不变式（§7/§25）：

    core final answer == api final answer == MCP envelope.result 中的学术载荷

因此本层**不改写**任何 scholarly 字段；transport 信息只进 `meta`。
"""
from __future__ import annotations

import concurrent.futures as _fut
import os
import re
import sys
import time

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if VAULT not in sys.path:
    sys.path.insert(0, VAULT)

import scholarly_api as api                       # noqa: E402  （唯一允许的依赖）

from . import audit as A                          # noqa: E402
from . import config as C                         # noqa: E402
from . import schemas as S                        # noqa: E402
from . import serializers as SZ                   # noqa: E402
from .errors import McpError, ProtocolError, from_api_error  # noqa: E402
from .guard import assert_core_frozen, verify_core_freeze     # noqa: E402

# 禁止出现在任何输入里的键名（§30：不暴露文件/SQL/命令/表达式面）
_FORBIDDEN_KEYS = ("path", "file", "filename", "filepath", "sql", "command", "cmd",
                   "shell", "exec", "execute", "python", "script", "eval",
                   "code", "glob", "regex", "urllib", "url", "http")
_DANGEROUS_SUBSTR = ("../", "..\\", "\x00", "$(", "`", "&&", "||", ";--", "\r")
# SQL 注入样式：本服务**没有** SQL 面，这里只做纵深防御式拒绝（不假装它在做参数化）
_SQLISH = re.compile(
    r"(\bDROP\s+TABLE\b|\bUNION\s+SELECT\b|\bINSERT\s+INTO\b|"
    r"\bDELETE\s+FROM\b|\bUPDATE\s+\w+\s+SET\b|OR\s+1\s*=\s*1|;\s*--)",
    re.IGNORECASE)


def _assert_safe_args(tool, args):
    """纵深防御：拒绝路径穿越 / 命令拼接 / 控制字符（$30）。"""
    for k, v in (args or {}).items():
        if k.lower() in _FORBIDDEN_KEYS:
            raise McpError("POLICY_DENIED",
                           "参数 %r 不被接受：本服务只接受领域参数" % k,
                           detail={"tool": tool, "argument": k},
                           resolution="只传 passage_id / concept_id / seminar_id / "
                                      "query / 领域过滤器")
        for s in ([v] if isinstance(v, str) else
                  ([x for x in v if isinstance(x, str)] if isinstance(v, list) else
                   ([x for x in v.values() if isinstance(x, str)]
                    if isinstance(v, dict) else []))):
            if any(t in s for t in _DANGEROUS_SUBSTR) or _SQLISH.search(s):
                raise McpError("POLICY_DENIED",
                               "参数 %r 含被禁止的字符序列" % k,
                               detail={"tool": tool, "argument": k},
                               resolution="输入应为纯领域文本，不含路径/命令/控制字符")
            if s.startswith("/") and len(s) > 1:
                raise McpError("POLICY_DENIED",
                               "参数 %r 不接受绝对路径" % k,
                               detail={"tool": tool, "argument": k},
                               resolution="使用领域 id（passage.* / concept.* / seminar.*）")


def _timeout_for(tool, args):
    t = S.tool_by_name(tool)
    cls = (t or {}).get("timeout_class")
    if cls == "lookup":
        return C.LOOKUP_TIMEOUT_S
    if cls == "search":
        return C.SEARCH_TIMEOUT_S
    provider = (args or {}).get("provider") or C.DEFAULT_PROVIDER
    return (C.RESEARCH_TIMEOUT_MOCK_S if provider == "mock"
            else C.RESEARCH_TIMEOUT_LLM_S)


def _run_with_timeout(fn, timeout_s, tool):
    """§28/§29：分类超时 + 串行执行。超时返回 TIMEOUT（不 kill 线程，如实说明）。"""
    with _fut.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except _fut.TimeoutError:
            raise McpError("TIMEOUT",
                           "工具 %s 超过 %ss 未返回" % (tool, timeout_s),
                           detail={"tool": tool, "timeout_s": timeout_s,
                                   "note": "底层调用可能仍在运行；本服务不杀线程"},
                           resolution="缩小问题范围 / 提高 LACAN_MCP_*_TIMEOUT_S / "
                                      "使用 provider=mock 做离线验证")


# ────────────────────────────────────────────────────────────── 各工具实现
def _impl_research(tool, args):
    if tool in ("lacan.compare_terms", "lacan.research_diachronic",
                "lacan.research_translation"):
        t = S.tool_by_name(tool)
        question = t["question_from_args"](args)
    else:
        question = args["question"]
    options = {
        "mode": args.get("mode") or "scholarly",
        "language": args.get("language") or "any",
        "provider": args.get("provider") or C.DEFAULT_PROVIDER,
        "judge": args.get("judge"),
        "task_id": args.get("task_id"),
        "constraints": args.get("constraints"),
        "requested_source_layers": args.get("requested_source_layers"),
        "requested_output_depth": args.get("requested_output_depth"),
        "budget": args.get("budget"),
    }
    res = api.research(question, options)
    if res.get("ok") is False:
        raise from_api_error(res)
    meta_extra = {"answer_state": res.get("answer_state"),
                  "answer_permission": res.get("answer_permission"),
                  "citation_count": len(res.get("citations") or []),
                  "validated_claims_n": len(res.get("validated_claims") or [])}
    return res, meta_extra


def _impl_search_passages(tool, args):
    filters = {
        "language": args.get("language") or "any",
        "seminar": args.get("seminar"),
        "period": None,
        "top_k": args.get("limit") or C.DEFAULT_SEARCH_LIMIT,
    }
    post = {k: args.get(k) for k in ("session", "source_layer", "date_range",
                                     "concept", "formalism")
            if args.get(k) is not None}
    over = bool(post)
    if over:                       # 需要后置过滤时先多取一些（并如实报告）
        filters["top_k"] = min(C.MAX_SEARCH_LIMIT * C.POST_FILTER_OVERFETCH,
                               (args.get("limit") or C.DEFAULT_SEARCH_LIMIT)
                               * C.POST_FILTER_OVERFETCH)
    res = api.search_passages(args["query"], filters)
    if res.get("ok") is False:
        raise from_api_error(res)

    retrieved_n = res.get("n") or 0
    ev = list(res.get("evidence") or [])
    if post:
        ev = [e for e in ev if _match_post_filters(e, post)]
    limit = args.get("limit") or C.DEFAULT_SEARCH_LIMIT
    ev = ev[:limit]
    out = {"query": args["query"],
           "filters": {k: v for k, v in dict(filters, **post).items() if v is not None},
           "evidence": ev, "n": len(ev)}
    if res.get("warnings"):
        out["warnings"] = res["warnings"]
    warnings = res.get("warnings") or []
    dense_unavailable = any((w.get("code") if isinstance(w, dict) else str(w))
                            == "VECTOR_UNAVAILABLE" for w in warnings)
    meta_extra = {"retrieved_n": retrieved_n, "n": len(ev), "limit": limit,
                  "post_filtered": over, "dense_available": not dense_unavailable,
                  "filters_applied": sorted([k for k, v in post.items() if v is not None])}
    return out, meta_extra


def _match_post_filters(ev, post):
    if post.get("session") and ev.get("session") != post["session"]:
        return False
    if post.get("source_layer") and ev.get("source_layer") != post["source_layer"]:
        return False
    if post.get("concept"):
        blob = "%s %s" % (ev.get("text") or "", ev.get("terminology_metadata") or "")
        if post["concept"].lower() not in blob.lower():
            return False
    if post.get("formalism"):
        blob = "%s %s" % (ev.get("text") or "", ev.get("formalism_metadata") or "")
        if post["formalism"].lower() not in blob.lower():
            return False
    dr = post.get("date_range") or {}
    if dr:
        y0, y1 = _as_int(dr.get("from")), _as_int(dr.get("to"))
        ey0, ey1 = _as_int(ev.get("year_from")), _as_int(ev.get("year_to"))
        if y0 is not None and ey1 is not None and ey1 < y0:
            return False
        if y1 is not None and ey0 is not None and ey0 > y1:
            return False
    return True


def _as_int(v):
    try:
        return int(str(v)[:4]) if v is not None else None
    except (TypeError, ValueError):
        return None


def _impl_get_passage(tool, args):
    res = api.get_passage(args["passage_id"])
    if res.get("ok") is False:
        raise from_api_error(res)
    return res, {"trace_status": res.get("trace_status"),
                 "source_layer": res.get("source_layer")}


def _impl_get_context(tool, args):
    before = args.get("before", 3)
    after = args.get("after", 3)
    res = api.get_context(args["passage_id"], before=before, after=after)
    if res.get("ok") is False:
        raise from_api_error(res)
    return res, {"before": before, "after": after,
                 "items_n": len(res.get("items") or [])}


def _impl_get_concept(tool, args):
    res = api.get_concept(args["concept_id"])
    if res.get("ok") is False:
        raise from_api_error(res)
    return res, {"evidence_n": len(res.get("evidence_ids") or [])}


def _impl_get_seminar(tool, args):
    res = api.get_seminar(args["seminar_id"])
    if res.get("ok") is False:
        raise from_api_error(res)
    return res, {"sessions_n": len(res.get("sessions") or []),
                 "passage_count": res.get("passage_count")}


def _impl_trace_source(tool, args):
    res = api.trace_source(args["passage_id"])
    if res.get("ok") is False:
        raise from_api_error(res)
    return res, {"trace_status": res.get("trace_status"),
                 "witness": res.get("witness"),
                 "source_layer": res.get("source_layer")}


_IMPL = {
    "lacan.research": _impl_research,
    "lacan.compare_terms": _impl_research,
    "lacan.research_diachronic": _impl_research,
    "lacan.research_translation": _impl_research,
    "lacan.search_passages": _impl_search_passages,
    "lacan.get_passage": _impl_get_passage,
    "lacan.get_context": _impl_get_context,
    "lacan.get_concept": _impl_get_concept,
    "lacan.get_seminar": _impl_get_seminar,
    "lacan.trace_source": _impl_trace_source,
}


# ────────────────────────────────────────────────────────────── 统一执行入口
def _sha256_prefix(text, n=16):
    """问题的不可逆指纹：关掉全文日志时仍可对账（§45）。"""
    import hashlib                                                    # noqa: PLC0415
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:n]


def call_tool(name, args, freeze_state=None, request_id=None, audit=True):
    """→ MCP envelope（`{ok, result, meta}` 或 `{ok:false, error, meta}`）。

    永不抛裸异常给 client；永不返回 traceback（§17）。
    """
    request_id = request_id or SZ.new_request_id()
    t0 = time.time()
    tool = S.tool_by_name(name)
    if tool is None:
        raise ProtocolError(-32602, "unknown tool: %r" % (name,),
                            {"code": "UNKNOWN_TOOL", "tool": name,
                             "available": S.TOOL_NAMES})


    def _fail(code, message, detail=None, resolution=""):
        err = McpError(code, message, detail, resolution)
        meta = SZ.base_meta(name, request_id, (time.time() - t0) * 1000)
        if audit:
            A.record(name, request_id, False, (time.time() - t0) * 1000,
                     provider=(args or {}).get("provider"),
                     error_code=err.code, question=(args or {}).get("question"),
                     required_schema=S.input_schema_id(name))
        return SZ.envelope_err(err.to_dict(), meta)

    ok, errs, filled = S.validate_input(name, args)
    if not ok:
        return _fail("SCHEMA_VALIDATION_FAILED",
                     "输入不符合 %s 的 v1 schema" % name,
                     detail={"schema_errors": errs[:5]},
                     resolution="修正参数类型/取值/上限后重试")

    try:
        _assert_safe_args(name, filled)
    except McpError as e:
        return _fail(e.code, e.message, e.detail, e.resolution)

    guard = None
    try:
        guard = assert_core_frozen(freeze_state)      # §27 fail closed
    except McpError as e:
        return _fail(e.code, e.message, e.detail, e.resolution)

    try:
        result, meta_extra = _run_with_timeout(
            lambda: _IMPL[name](name, filled), _timeout_for(name, filled), name)
    except McpError as e:
        return _fail(e.code, e.message, e.detail, e.resolution)
    except Exception as exc:                          # noqa: BLE001
        return _fail("INTERNAL_ERROR", "工具执行失败：%s" % type(exc).__name__,
                     detail={"message": str(exc)[:300]},
                     resolution="查看服务端审计日志（含完整 traceback）后重试")

    ok, errs = S.validate_output(name, result)
    if not ok:
        return _fail("SCHEMA_VALIDATION_FAILED",
                     "输出不符合 %s 的稳定对象 schema" % tool["output_object"],
                     detail={"schema_errors": errs[:5]},
                     resolution="这是核心/边界缺陷：请提交 Core Change Request，"
                                "不要放宽 schema")

    duration = (time.time() - t0) * 1000
    provider = (filled.get("provider") if name.startswith("lacan.research")
                or name in ("lacan.compare_terms", "lacan.research_diachronic",
                            "lacan.research_translation") else None)
    meta = SZ.base_meta(name, request_id, duration, provider, meta_extra)
    meta["core_guard"] = guard
    # ★ Phase 5A（P5A-001 / §13）：校验器诊断属 AUDIT_DIAGNOSTIC，**不进 result 正文**，
    #   但审计者必须拿得到 → 作为 transport 信息附加在 meta（result schema 不变）。
    if isinstance(result, dict):
        if isinstance(result.get("audit_diagnostics"), dict):
            meta["audit_diagnostics"] = result["audit_diagnostics"]
            meta["presentation_taxonomy_version"] = "presentation-taxonomy/v1"
        if result.get("schema_version"):
            meta["answer_schema_version"] = result["schema_version"]
    if audit:
        A.record(name, request_id, True, duration, provider=provider,
                 answer_state=(result.get("answer_state")
                               if isinstance(result, dict) else None),
                 citation_count=(len(result.get("citations") or [])
                                 if isinstance(result, dict) else None),
                 # §45：问题全文日志**可配置**。默认保留（既有审计轨迹不变）；
                 #   设 LACAN_AUDIT_LOG_QUESTION=0 → 只记 sha256 前缀，不落问题原文。
                 question=(filled.get("question") if os.environ.get(
                     "LACAN_AUDIT_LOG_QUESTION", "1") not in ("0", "false", "False")
                     else None),
                 question_sha256=(None if os.environ.get(
                     "LACAN_AUDIT_LOG_QUESTION", "1") not in ("0", "false", "False")
                     else _sha256_prefix(filled.get("question"))),
                 required_schema=S.input_schema_id(name),
                 extra={"post_filtered": meta_extra.get("post_filtered"),
                        "dense_available": meta_extra.get("dense_available")})
    return SZ.envelope_ok(result, meta)


def audit_tool_inventory():
    """→ 供测试/报告使用的工具清单。"""
    return [{"name": t["name"], "output_object": t["output_object"],
             "timeout_class": t["timeout_class"]} for t in S.TOOLS]
