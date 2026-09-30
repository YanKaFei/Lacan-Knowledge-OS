#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install-dsh-row.py — install the Lacan Knowledge OS MCP row into a DSH profile.

Why a script instead of just a YAML snippet: a row needs the **absolute path** of your
clone, and hand-editing paths is where installations rot. This writes an idempotent,
clearly delimited block into the profile's own patch file, so you can re-run it after
moving the repository and remove it cleanly.

What it touches (and nothing else):

    ${DSH_HOME:-~/.dsh}/profiles/<profile>/cordis.patch.yml

It never edits a shipped preset or the host composition — the row belongs to the profile
layer, which is the user's own. `dsh-mcp-client` contributes tools only and provides no
service, so the row needs no isolate realm.

Usage:
    python3 tools/install-dsh-row.py --profile web            # install / update
    python3 tools/install-dsh-row.py --profile web --remove   # uninstall
    python3 tools/install-dsh-row.py --profile web --print    # show the block only
    python3 tools/install-dsh-row.py --profile web --server-name lacan-kb --timeout 180000
"""
from __future__ import annotations

import argparse
import io
import os
import sys

BEGIN = "# >>> lacan-knowledge-os (managed block — edit via tools/install-dsh-row.py) >>>"
END = "# <<< lacan-knowledge-os (managed block) <<<"


def repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def dsh_home() -> str:
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def profile_patch(profile: str) -> str:
    return os.path.join(dsh_home(), "profiles", profile, "cordis.patch.yml")


def row_block(root: str, server_name: str, timeout: int, python: str) -> str:
    server = os.path.join(root, "_scripts", "_tools", "lacan-kb-mcp")
    return "\n".join([
        BEGIN,
        "# Installed by tools/install-dsh-row.py — remove with `--remove`.",
        "# Contributes tools only (no service) → no isolate realm needed.",
        "- insert:",
        "    - id: mcp-lacan-kb",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        serverName: %s" % server_name,
        "        transport: stdio",
        "        command: %s" % python,
        "        args:",
        "          - %s" % server,
        "        cwd: %s" % root,
        "        toolCallTimeoutMs: %d" % timeout,
        "        failOnStartupError: true",
        END,
        "",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", default="web", help="DSH profile name (default: web)")
    ap.add_argument("--server-name", default="lacan-kb",
                    help="MCP server name → tools appear as mcp__<name>__<tool>")
    ap.add_argument("--timeout", type=int, default=120000, help="tool call timeout (ms)")
    ap.add_argument("--python", default=sys.executable or "python3",
                    help="interpreter that runs the MCP server")
    ap.add_argument("--remove", action="store_true", help="remove the managed block")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="print the block instead of writing")
    ap.add_argument("--path", default=None, help="override the profile patch path")
    a = ap.parse_args(argv)

    root = repo_root()
    block = row_block(root, a.server_name, a.timeout, a.python)
    if a.print_only:
        print(block, end="")
        return 0

    path = a.path or profile_patch(a.profile)
    existed = os.path.isfile(path)
    text = ""
    if existed:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    if BEGIN in text:
        head = text[:text.index(BEGIN)]
        tail = text[text.index(END) + len(END):] if END in text else ""
        text = head + tail
    if not a.remove:
        if not text.endswith("\n") and text:
            text += "\n"
        text = text + ("\n" if text else "") + block
    elif not existed:
        print("nothing to remove: %s does not exist" % path)
        return 0

    # 移除后不留一串空行（否则每次 install/remove 都会长高）
    text = text.rstrip() + ("\n" if text.strip() else "")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("%s %s" % ("removed block from" if a.remove else "installed row into", path))
    print("server name: %s → tools: mcp__%s__<tool>" % (a.server_name, a.server_name))
    print("restart the profile for the row to take effect:")
    print("    dsh --profile %s" % a.profile)
    if not existed and not a.remove:
        print("\nnote: this created a new profile patch file. If the profile has not been")
        print("initialised yet, run `dsh plugin --profile %s add <plugin>` once first." % a.profile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
