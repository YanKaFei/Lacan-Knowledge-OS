#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_wheelhouse.py — Phase 3B.1 §5/§6 离线 wheelhouse 构建与校验

设计纪律
────────
* **平台 tag 不猜**：从目标解释器自己的 `pip._internal.utils.compatibility_tags`
  取 supported tags，去重出平台字符串，再逐个传给 `pip download --platform`。
 comparable：§2 已证明 `sysconfig.get_platform()` 报 `macosx-10.9-universal2`，
  但机器是 arm64 / macOS 26.2 —— **只按 "macOS" 选 wheel 会选错**。
* **只收 binary wheel**：`--only-binary=:all:`。任何包没有本平台 wheel → 命令失败，
  **绝不静默退回 sdist**（sdist 就等于放弃「离线 wheelhouse」这个保证）。
* 版本**由 .lock 固定**，不重新解析最新版本；解析结果必须等于 .lock，
  否则 manifest 报 `lock_mismatch` 而不是悄悄换版本。
* manifest 记录每个 wheel 的 filename / package / version / wheel_tags /
  sha256 / size / source_url，并给出 `wheelhouse_hash`（对排序后的
  (filename, sha256) 列表取哈希）—— 让「这堆 wheel 有没有被换过」可判定。

用法
────
    python3 build_wheelhouse.py --build          # 下载 + 写 manifest
    python3 build_wheelhouse.py --verify         # 只校验现有 wheelhouse 与 manifest 一致
    python3 build_wheelhouse.py --print-tags      # 打印将从 RUNTIME_TARGET 推导的平台 tag
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.dirname(os.path.dirname(HERE))

WHEELHOUSE = os.path.join(VAULT, "wheelhouse")
MANIFEST = os.path.join(VAULT, "WHEELHOUSE_MANIFEST.json")
LOCK = os.path.join(VAULT, "embedding-runtime-requirements.lock")
RUNTIME_TARGET = os.path.join(VAULT, "RUNTIME_TARGET.json")
TARGET_VENV_PY = os.path.join(VAULT, ".venv-embedding", "bin", "python")

SCHEMA_VERSION = "wheelhouse-manifest/v1"

# .lock 里这些是**工具自身**，不是 embedding runtime 的依赖。
# 仍然下载（离线引导 venv 需要 pip），但 manifest 里标注 purpose 以便区分。
TOOLING = {"pip", "setuptools", "wheel"}


# ────────────────────────────────────────────────────────────── 目标平台 tag

def supported_platforms(python_exe):
    """返回目标解释器支持的 wheel **平台** 字符串（去重、保序）。"""
    code = (
        "from pip._internal.utils.compatibility_tags import get_supported;"
        "import sys;"
        "tags=[]\n"
        "for t in get_supported():\n"
        "    p=getattr(t,'platform',None)\n"
        "    if p and p!='any': tags.append(p)\n"
        "seen=[]\n"
        "for p in tags:\n"
        "    if p not in seen: seen.append(p)\n"
        "print('\\n'.join(seen))"
    )
    out = subprocess.run([python_exe, "-c", code], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("无法从 %s 取 supported tags:\n%s" % (python_exe, out.stderr))
    plats = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    # 只保留 arm64 / universal2 —— 本机 interpreter 是 universal2 且实际跑 arm64；
    # intel/x86_64 tag 不参与（避免把不能用的 wheel 拉进来）。
    keep = [p for p in plats if p.endswith(("_arm64", "_universal2"))]
    return keep or plats


def python_version_args(python_exe):
    code = "import sys;print('%d.%d'%sys.version_info[:2])"
    v = subprocess.run([python_exe, "-c", code], capture_output=True, text=True).stdout.strip()
    major, minor = v.split(".")
    return ["--python-version", "%s%s" % (major, minor), "--implementation", "cp"]


# ────────────────────────────────────────────────────────────── wheel 解析

WHEEL_NAME_RE = re.compile(
    r"^(?P<name>[^-]+)-(?P<ver>[^-]+)"
    r"(?:-(?P<build>[0-9][^-]*))?"
    r"-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$"
)


def parse_wheel(filename):
    m = WHEEL_NAME_RE.match(filename)
    if not m:
        return None
    d = m.groupdict()
    d["wheel_tags"] = "%s-%s-%s" % (d["py"], d["abi"], d["plat"])
    return d


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def wheel_metadata_inner(path):
    """从 .whl 的 *.dist-info/METADATA 读真实 Name/Version（不靠文件名反推）。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
            if not names:
                return None, None
            text = z.read(names[0]).decode("utf-8", "replace")
    except zipfile.BadZipFile:
        return None, None
    name = version = None
    for line in text.splitlines():
        if line.startswith("Name: ") and name is None:
            name = line[6:].strip()
        elif line.startswith("Version: ") and version is None:
            version = line[9:].strip()
        if name and version:
            break
    return name, version


def read_lock():
    """→ ordered list of (name, version, spec_line)"""
    out = []
    with open(LOCK, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)==(.+)$", line)
            if not m:
                raise SystemExit("lock 行无法解析: %r" % line)
            out.append((m.group(1), m.group(2), line))
    return out


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


# ────────────────────────────────────────────────────────────── build

def cmd_build(python_exe, force=False, index_url=None):
    if os.path.isdir(WHEELHOUSE) and force:
        shutil.rmtree(WHEELHOUSE)
    os.makedirs(WHEELHOUSE, exist_ok=True)
    if os.listdir(WHEELHOUSE) and not force:
        raise SystemExit("wheelhouse/ 非空；加 --force 重建（不静默混入旧 wheel）")

    plats = supported_platforms(python_exe)
    pyargs = python_version_args(python_exe)

    cmd = [python_exe, "-m", "pip", "download",
           "--only-binary=:all:",
           "--dest", WHEELHOUSE,
           "--no-cache-dir",
           "-r", LOCK]
    if index_url:
        cmd += ["--index-url", index_url]
    for p in plats:
        cmd += ["--platform", p]
    cmd += pyargs

    print("[build] 目标平台 tag 数 = %d（来自解释器自身 supported tags）" % len(plats))
    print("[build] index = %s" % (index_url or "默认 (pypi.org)"))
    print("[build] %s" % " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        return {"status": "RUNTIME_WHEEL_INCOMPATIBLE",
                "reason": "pip download 失败：有包在本平台没有 binary wheel。见上方输出。",
                "download_command": " ".join(cmd)}

    return write_manifest(plats, pyargs, cmd, index_url)


def write_manifest(plats, pyargs, cmd, index_url=None):
    files = sorted(f for f in os.listdir(WHEELHOUSE) if f.endswith(".whl"))
    entries = []
    for fn in files:
        path = os.path.join(WHEELHOUSE, fn)
        parsed = parse_wheel(fn) or {}
        name, version = wheel_metadata_inner(path)
        entries.append({
            "filename": fn,
            "package": name or parsed.get("name"),
            "version": version or parsed.get("ver"),
            "wheel_tags": parsed.get("wheel_tags"),
            "sha256": sha256_file(path),
            "size_bytes": os.path.getsize(path),
            "source": "pypi",
            "source_index_url": index_url or "https://pypi.org/simple/",
            # ⚠️ 不要在这里塞 `platforms_offered` —— 40 个平台 tag × 34 个 wheel
            # 会把 manifest 从 20KB 吹到 136KB，而且是纯重复。
            # 平台集合记在 built_from.platform_tags_offered 一处即可。
            "target_compatibility": {
                "python_version": pyargs[1],
                "implementation": pyargs[3],
                "matched_platform": parsed.get("plat"),
            },
            "purpose": "tooling" if canonical(name or "") in
                       {canonical(t) for t in TOOLING} else "embedding_runtime",
        })

    entries.sort(key=lambda e: (e["package"] or "", e["filename"]))
    lock = read_lock()
    locked = {canonical(n): v for n, v, _ in lock}
    got = {canonical(e["package"]): e["version"] for e in entries if e["package"]}
    missing = sorted(set(locked) - set(got))
    extra = sorted(set(got) - set(locked))
    mismatch = sorted(k for k in set(locked) & set(got) if locked[k] != got[k])

    h = hashlib.sha256()
    for e in entries:
        h.update(("%s %s\n" % (e["filename"], e["sha256"])).encode())
    wheelhouse_hash = h.hexdigest()

    # ⚠️ `cmd` 可能是 list（正常构建路径）也可能是**已经拼好的字符串**
    #    （重写 manifest 时传入）。旧代码无条件 `" ".join(cmd)` ——
    #    对字符串会**逐字符** join，产出 `/ U s e r s / c o f f e e …` 这种废命令。
    #    实测踩过：WHEELHOUSE_MANIFEST 里的复现命令一度不可用。
    cmd_str = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
    if "--only-binary=:all:" not in cmd_str or "pip" not in cmd_str:
        raise SystemExit("download_command 形态异常（缺 --only-binary 或 pip）：%r"
                         % cmd_str[:200])

    total = sum(e["size_bytes"] for e in entries)
    man = {
        "schema_version": SCHEMA_VERSION,
        "wheelhouse_path": os.path.relpath(WHEELHOUSE, VAULT) + "/",
        "wheel_count": len(entries),
        "total_bytes": total,
        "wheelhouse_hash": wheelhouse_hash,
        "hash_rule": "sha256 over 排序后的 '<filename> <sha256>\\n' 串联",
        "built_from": {
            "lock": os.path.basename(LOCK),
            "runtime_target": os.path.basename(RUNTIME_TARGET),
            "download_command": cmd_str,
            "index_url": index_url or "https://pypi.org/simple/",
            "platform_tags_offered": plats,
            "python_version": pyargs[1],
            "implementation": "cp",
            "only_binary": True,
            "note": ("平台 tag 取自目标解释器自身 supported tags，不是手写平台名。"
                     "index 若为镜像，见 INDEX_MIRROR_NOTE：直连 pypi.org 实测约 4–5 kB/s，"
                     "镜像服务的是同一批 wheel，完整性由每个 wheel 的 sha256 锚定。"),
        },
        "lock_consistency": {
            "lock_entries": len(lock),
            "matched": len(set(locked) & set(got)),
            "missing_from_wheelhouse": missing,
            "extra_in_wheelhouse": extra,
            "version_mismatch": mismatch,
            "consistent": not (missing or extra or mismatch),
        },
        "wheels": entries,
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("[build] %d wheels / %.1f MB / hash %s" % (len(entries), total / 1e6, wheelhouse_hash[:16]))
    if not man["lock_consistency"]["consistent"]:
        print("[build] ⚠️ lock 不一致: %s" % json.dumps(man["lock_consistency"], ensure_ascii=False))
    return man


def cmd_offline_test(python_exe, keep=False):
    """**证明**离线可复现：干净 venv + `--no-index --find-links wheelhouse` 装一遍。

    这是 §5/§6 的核心证据 —— 不是「wheelhouse 里有文件」，而是「断网也能装出来」。
    """
    if not os.path.isdir(WHEELHOUSE) or not any(
            f.endswith(".whl") for f in os.listdir(WHEELHOUSE)):
        return {"status": "FAIL", "reason": "wheelhouse 为空"}
    test_venv = os.path.join(VAULT, ".venv-offline-test")
    if os.path.isdir(test_venv):
        shutil.rmtree(test_venv)
    r = subprocess.run([python_exe, "-m", "venv", test_venv],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"status": "FAIL", "reason": "创建测试 venv 失败: %s" % r.stderr[-500:]}
    vpy = os.path.join(test_venv, "bin", "python")
    # 关键：--no-index 断掉索引，只能从 wheelhouse 取包
    cmd = [vpy, "-m", "pip", "install", "--no-index",
           "--find-links", WHEELHOUSE, "--no-input", "--disable-pip-version-check",
           "-r", LOCK]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    result = {
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "test_venv": test_venv,
        "command": " ".join(cmd),
        "network_used": False,
        "note": "--no-index 使索引不可用；只允许 wheelhouse 里的 wheel。",
    }
    if proc.returncode != 0:
        result["stderr_tail"] = proc.stderr[-2000:]
        result["stdout_tail"] = proc.stdout[-2000:]
    else:
        # 装完再核一遍版本，并真的 import 一次
        # ⚠️ 用 `pip list --format=json`，**不要**用 `pip freeze`：
        # freeze 默认不列 pip/setuptools/wheel，会误报「版本不符」。
        lst = subprocess.run([vpy, "-m", "pip", "list", "--format=json",
                              "--disable-pip-version-check"],
                             capture_output=True, text=True)
        installed = {}
        for e in json.loads(lst.stdout or "[]"):
            installed[canonical(e["name"])] = e["version"]
        lock = read_lock()
        mism = {n: {"lock": v, "offline": installed.get(canonical(n))}
                for n, v, _ in lock if installed.get(canonical(n)) != v}
        result["packages_installed"] = len(installed)
        result["version_mismatch_vs_lock"] = mism
        imp = subprocess.run(
            [vpy, "-c", "import numpy, onnxruntime, tokenizers;"
                        "print('numpy=%s onnxruntime=%s tokenizers=%s' % ("
                        "numpy.__version__, onnxruntime.__version__, tokenizers.__version__))"],
            capture_output=True, text=True)
        result["import_check_returncode"] = imp.returncode
        result["import_check_stdout"] = imp.stdout.strip()
        result["import_check_stderr"] = imp.stderr.strip()[-500:]
        if mism or imp.returncode != 0:
            result["status"] = "FAIL"
    if not keep:
        shutil.rmtree(test_venv, ignore_errors=True)
        result["test_venv_removed"] = True

    # 写回 manifest
    if os.path.isfile(MANIFEST):
        man = json.load(open(MANIFEST, encoding="utf-8"))
        man["offline_install_test"] = result
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return result


# ────────────────────────────────────────────────────────────── verify

def cmd_verify():
    if not os.path.isfile(MANIFEST):
        return {"status": "FAIL", "reason": "WHEELHOUSE_MANIFEST.json 不存在"}
    with open(MANIFEST, encoding="utf-8") as f:
        man = json.load(f)
    problems = []
    on_disk = sorted(f for f in os.listdir(WHEELHOUSE) if f.endswith(".whl")) \
        if os.path.isdir(WHEELHOUSE) else []
    declared = sorted(e["filename"] for e in man["wheels"])
    for fn in declared:
        if fn not in on_disk:
            problems.append("缺失 wheel: %s" % fn)
            continue
        e = next(x for x in man["wheels"] if x["filename"] == fn)
        p = os.path.join(WHEELHOUSE, fn)
        if os.path.getsize(p) != e["size_bytes"]:
            problems.append("大小不符: %s" % fn)
        if sha256_file(p) != e["sha256"]:
            problems.append("sha256 不符: %s" % fn)
    for fn in on_disk:
        if fn not in declared:
            problems.append("未登记 wheel（凭空多出来的）: %s" % fn)

    # 复现命令必须是可用的形态（曾经被逐字符 join 破坏过）
    dc = (man.get("built_from") or {}).get("download_command") or ""
    if "--only-binary=:all:" not in dc or "pip" not in dc or "  " in dc:
        problems.append("built_from.download_command 形态异常，复现命令不可用: %r"
                        % dc[:120])

    h = hashlib.sha256()
    for e in sorted(man["wheels"], key=lambda e: (e["package"] or "", e["filename"])):
        h.update(("%s %s\n" % (e["filename"], e["sha256"])).encode())
    if h.hexdigest() != man["wheelhouse_hash"]:
        problems.append("wheelhouse_hash 与逐条 (filename, sha256) 重算不一致")

    return {
        "status": "PASS" if not problems else "FAIL",
        "wheel_count": len(declared),
        "wheelhouse_hash": man["wheelhouse_hash"],
        "recomputed_hash": h.hexdigest(),
        "problems": problems,
        "lock_consistent": man["lock_consistency"]["consistent"],
    }


def cmd_print_tags(python_exe):
    for p in supported_platforms(python_exe):
        print(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase 3B.1 §5/§6 离线 wheelhouse")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--print-tags", action="store_true")
    g.add_argument("--offline-test", action="store_true",
                   help="干净 venv + --no-index 从 wheelhouse 离线装一遍（§5/§6 核心证据）")
    ap.add_argument("--keep-venv", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--index-url", default="https://pypi.tuna.tsinghua.edu.cn/simple",
                    help="wheel 来源 index；默认用清华镜像（直连 pypi.org 实测约 4–5 kB/s）")
    ap.add_argument("--python", default=TARGET_VENV_PY if os.path.exists(TARGET_VENV_PY) else sys.executable)
    a = ap.parse_args(argv)

    if a.print_tags:
        cmd_print_tags(a.python)
        return 0
    if a.build:
        r = cmd_build(a.python, force=a.force, index_url=a.index_url)
    elif a.offline_test:
        r = cmd_offline_test(a.python, keep=a.keep_venv)
    else:
        r = cmd_verify()
    print(json.dumps(r, ensure_ascii=False, indent=2)[:4000])
    if r.get("status") in ("RUNTIME_WHEEL_INCOMPATIBLE", "FAIL"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
