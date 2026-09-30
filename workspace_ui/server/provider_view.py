#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.provider_view — 真实 provider 的**产品层**设置与连通性自检。

边界（不许越界）：
    * 冻结核心读的是环境变量 `DSH_SYNTHESIS_MODEL` / `DSH_SYNTHESIS_BASE_URL` /
      `DSH_SYNTHESIS_API_KEY`（或 `~/.dsh/.credentials.yaml`），本模块**只写前两个**；
    * **密钥永不经过产品 API**：既不读出来打印，也不接受前端传入，只报告"有没有"；
    * 每次模型调用的 120s 上限写死在冻结核心（`scholarly_api/core.py`），
      因此这里把它作为**只读**信息展示，不假装可调。

设置持久化在 `_workspace/settings/provider.json`（USER_WORKSPACE，可重建，不是 canonical）。
改动后在进程内更新 `os.environ` 并 `reset_shared_client()`，
使**下一次**研究会 spawn 出带新环境变量的 MCP 子进程。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

SETTINGS_PATH = os.path.join(VAULT, "_workspace", "settings", "provider.json")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
CORE_CALL_TIMEOUT_S = 120          # 冻结核心写死；只读展示
PROBE_TIMEOUT_S = 20
MODEL_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,80}$")
URL_RE = re.compile(r"^https://[A-Za-z0-9._\-]+(:\d+)?(/[A-Za-z0-9._\-/]*)?$")


def _credentials_present():
    """与冻结核心**逐条对齐**的凭据判断（只看有没有；不读取、不打印内容）。"""
    if os.environ.get("DSH_SYNTHESIS_API_KEY"):
        return True, "DSH_SYNTHESIS_API_KEY"
    path = os.path.expanduser("~/.dsh/.credentials.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if re.match(r"\s*DEEPSEEK_API_KEY:\s*\S+\s*$", line):
                    return True, "~/.dsh/.credentials.yaml"
    except OSError:
        return False, None
    return False, None


def _api_key():
    """供**自检**使用：与核心同一来源（绝不外传、绝不写日志）。"""
    key = os.environ.get("DSH_SYNTHESIS_API_KEY")
    if key:
        return key
    path = os.path.expanduser("~/.dsh/.credentials.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"\s*DEEPSEEK_API_KEY:\s*(\S+)\s*$", line)
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


def _load_file():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def effective():
    """当前**生效**的设置（文件 → 环境变量 → 默认）。"""
    d = _load_file()
    present, source = _credentials_present()
    return {
        "provider": d.get("provider") or os.environ.get("LACAN_UI_DEFAULT_PROVIDER") or "mock",
        "model": os.environ.get("DSH_SYNTHESIS_MODEL") or d.get("model") or DEFAULT_MODEL,
        "base_url": (os.environ.get("DSH_SYNTHESIS_BASE_URL")
                     or d.get("base_url") or DEFAULT_BASE_URL),
        "credentials_present": present,
        "credential_source": source,
        "call_timeout_s": CORE_CALL_TIMEOUT_S,
        "call_timeout_note": ("每次模型调用上限 120s 由冻结核心写死（产品层不可调）；"
                              "单次研究请求的 MCP 上限 900s。"),
        "settings_path": os.path.relpath(SETTINGS_PATH, VAULT),
        "persisted": bool(d),
    }


LAST_APPLY = {"applied": {}, "rejected": {}}


def apply_persisted():
    """UI 启动时调用：把持久化设置写进本进程环境，再由 MCP 子进程继承。

    只写 model / base_url；**不动**任何密钥。
    ★ P5D-005 加固：持久化文件可能被手工编辑坏（或由测试写过）。
      不合法就**不灌进环境**，并把它记在 `LAST_APPLY["rejected"]` 里 ——
      否则一个坏值会静默地让每一次研究都打到一个不存在的端点上，且界面看不出来。
    """
    d = _load_file()
    applied, rejected = {}, {}
    model = str(d.get("model") or "")
    if model:
        if MODEL_RE.match(model):
            os.environ["DSH_SYNTHESIS_MODEL"] = model
            applied["DSH_SYNTHESIS_MODEL"] = model
        else:
            rejected["model"] = model
    base_url = str(d.get("base_url") or "").rstrip("/")
    if base_url:
        if URL_RE.match(base_url):
            os.environ["DSH_SYNTHESIS_BASE_URL"] = base_url
            applied["DSH_SYNTHESIS_BASE_URL"] = base_url
        else:
            rejected["base_url"] = base_url
    LAST_APPLY.update({"applied": applied, "rejected": rejected})
    return applied


def save(payload):
    """保存设置并让下一次研究使用新值。返回 (ok, body)。"""
    model = (payload or {}).get("model")
    base_url = (payload or {}).get("base_url")
    provider = (payload or {}).get("provider")
    errs = {}
    if model is not None and not MODEL_RE.match(str(model)):
        errs["model"] = "模型名只允许 [A-Za-z0-9._:-]，≤80 字符"
    if base_url is not None and not URL_RE.match(str(base_url)):
        errs["base_url"] = "只接受 https:// 开头的 OpenAI 兼容端点"
    if provider is not None and provider not in ("mock", "llm"):
        errs["provider"] = "provider ∈ {mock, llm}"
    if errs:
        return False, {"kind": "error", "code": "INVALID_REQUEST",
                       "title": "Provider settings rejected", "body": "；".join(errs.values()),
                       "view": "error", "errors": errs}

    d = _load_file()
    if model is not None:
        d["model"] = str(model)
        os.environ["DSH_SYNTHESIS_MODEL"] = str(model)
    if base_url is not None:
        d["base_url"] = str(base_url).rstrip("/")
        os.environ["DSH_SYNTHESIS_BASE_URL"] = d["base_url"]
    if provider is not None:
        d["provider"] = provider
    d["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, SETTINGS_PATH)

    # 让新设置对**下一次**研究生效：重启共享 MCP 子进程（不触碰任何 scholarly 语义）
    restarted, restart_error = False, None
    try:
        from .mcp_client import reset_shared_client                      # noqa: PLC0415
        reset_shared_client()
        restarted = True
    except Exception as exc:                                              # noqa: BLE001
        restart_error = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    out = effective()
    out.update({"ok": True, "saved": True, "mcp_restarted": restarted,
                "restart_error": restart_error,
                "note": ("设置已保存；下一次研究请求会使用新的 MCP 子进程环境。"
                         "密钥不经产品 API，也不回显。")})
    return True, out


def test_connection(payload=None):
    """产品层连通性自检：真发一次**极小**的 chat/completions（不是假的"已配置"）。

    * 只看：HTTP 状态、耗时、返回的 model 字段、以及错误的**类型**（不回显内容/密钥）；
    * 不发研究问题、不写 history、不影响任何 scholarly 状态。
    """
    cfg = effective()
    model = (payload or {}).get("model") or cfg["model"]
    base_url = ((payload or {}).get("base_url") or cfg["base_url"]).rstrip("/")
    if not MODEL_RE.match(str(model)):
        return {"ok": False, "code": "INVALID_MODEL", "detail": "模型名不合法"}
    key = _api_key()
    if not key:
        return {"ok": False, "code": "NO_CREDENTIALS",
                "detail": ("未发现 DSH_SYNTHESIS_API_KEY 或 ~/.dsh/.credentials.yaml 中的 "
                           "DEEPSEEK_API_KEY。产品层不接收密钥输入。"),
                "credentials_present": False}
    body = json.dumps({"model": model, "temperature": 0, "max_tokens": 4,
                       "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8")
    req = urllib.request.Request(base_url + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer %s" % key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "code": "OK", "latency_s": round(time.time() - t0, 2),
                "http_status": resp.status, "model": doc.get("model") or model,
                "base_url": base_url,
                "usage": {k: (doc.get("usage") or {}).get(k)
                          for k in ("prompt_tokens", "completion_tokens", "total_tokens")}}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "code": "HTTP_%d" % exc.code,
                "http_status": exc.code, "latency_s": round(time.time() - t0, 2),
                "detail": ("端点可达但拒绝该请求（常见：key 无效/额度/模型名不对）"
                           if exc.code in (401, 402, 403, 404, 429) else "HTTP 错误"),
                "base_url": base_url}
    except Exception as exc:                                              # noqa: BLE001
        return {"ok": False, "code": type(exc).__name__,
                "latency_s": round(time.time() - t0, 2),
                "detail": "无法连上端点（网络/解析/超时）；本地功能不受影响",
                "base_url": base_url}
