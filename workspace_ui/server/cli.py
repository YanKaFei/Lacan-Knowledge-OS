#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workspace_ui.server.cli — 启动 Workspace（stdlib http.server）。"""
from __future__ import annotations

import argparse
import json
import sys

from . import api as A
from . import config as C
from .httpserver import serve_forever


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lacan Research Workspace MVP")
    ap.add_argument("--host", default=C.DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=C.DEFAULT_PORT)
    ap.add_argument("--selftest", action="store_true",
                    help="打印状态并退出（供套件调用）")
    a = ap.parse_args(argv)
    if a.selftest:
        st = A.status()
        print(json.dumps({"workspace_version": C.WORKSPACE_VERSION,
                          "mcp_connected": st.get("mcp_connected"),
                          "core_freeze_verified": st.get("core_freeze_verified"),
                          "research_disabled": st.get("research_disabled"),
                          "history_dir": C.HISTORY_DIR,
                          "static_dir": C.STATIC_DIR}, ensure_ascii=False, indent=1))
        return 0 if st.get("core_freeze_verified") else 3
    return serve_forever(a.host, a.port)


if __name__ == "__main__":
    sys.exit(main())
