#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_corpus.py — 只读语料盘点引擎 (Lacanian Knowledge OS, Phase 1)

设计约束（不可违反）:
  * 只读: 源目录以 'rb' 打开, 永不写回, 永不移动, 永不删除任何源文件。
  * 幂等: 同一输入重复运行产出 byte-identical 结果 (除 generated_at)。
  * 容错: 任一文件解析失败不中断整体, 记入 parse_status / anomalies。

产出:
  corpus_inventory.json   每条 record 含 28 个字段（见 CSV_FIELDS + format_meta 等）
  corpus_inventory.csv    同上，表格形式；含 brief 逐条点名的全部字段
  corpus_report.md        人类可读报告（总览/重复/异常/研讨班覆盖率/权威分层）

关键字段:
  document_id             逻辑文档归并 id —— 把「4 组字节级重复 + 5 组同书分卷」
                          机械地桥接到 vault 的 document 层（143 文件 → 133 逻辑文档）。
                          只做逻辑归并，物理文件一律不动。
  sha256                  字节级内容锚点，用于溯源与防篡改
  parse_status            PARSED / NEEDS_OCR / PARSED_PARTIAL / IMAGE_NO_TEXT / …
  duplicate_group_ids     该文件所属的全部重复组

用法:
  python3 inventory_corpus.py                      # 默认源目录
  python3 inventory_corpus.py --source <DIR> --out <DIR>
  python3 inventory_corpus.py --no-hash            # 只做快速结构盘点
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tools"))
from deterministic import apply_stamp, add_stamp_flag  # noqa: E402

DEFAULT_SOURCE = os.path.expanduser("<HOME>")
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_data")

SCHEMA_VERSION = "corpus-inventory/v1"
HASH_CHUNK = 1 << 20  # 1 MiB

# 这些 parse_status 一律要进入 anomalies 清单（可读性/可处理性问题）
PROBLEM_STATUSES = {
    "UNPARSED", "UNDECODABLE", "UNSUPPORTED_FORMAT", "EMPTY_TEXT",
    "NEEDS_OCR", "PARSED_PARTIAL",
}

# ---------------------------------------------------------------- 可选依赖
try:
    import yaml  # noqa: F401
    HAS_YAML = True
except Exception:
    HAS_YAML = False

try:
    import docx as _docx
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except Exception:
    try:
        from PyPDF2 import PdfReader  # type: ignore
        HAS_PYPDF = True
    except Exception:
        HAS_PYPDF = False

try:
    from ebooklib import epub as _epub
    import warnings as _warnings
    _warnings.filterwarnings("ignore")
    HAS_EPUBLIB = True
except Exception:
    HAS_EPUBLIB = False

try:
    from langdetect import detect as _langdetect  # noqa: F401
    HAS_LANGDETECT = True
except Exception:
    HAS_LANGDETECT = False

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False


# ================================================================ 语言判定
# 纯字符谱统计, 不依赖任何模型: 对"中/英/法/德"混合的语料比统计模型可靠。
_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN = re.compile(r"[A-Za-z]")
_FR_DIACRITICS = re.compile(r"[àâäéèêëïîôöùûüÿçœæ]", re.I)
_DE_DIACRITICS = re.compile(r"[äöüß]", re.I)
_CYR = re.compile(r"[\u0400-\u04ff]")
_GREEK = re.compile(r"[\u0370-\u03ff]")
_ARABIC = re.compile(r"[\u0600-\u06ff]")


def detect_language(text: str) -> str:
    """返回 'zh' | 'fr' | 'en' | 'de' | 'ru' | 'el' | 'ar' | 'und'。"""
    if not text:
        return "und"
    sample = text[:40000]
    total = len(sample)
    n_cjk = len(_CJK.findall(sample))
    n_lat = len(_LATIN.findall(sample))
    n_cyr = len(_CYR.findall(sample))
    n_grk = len(_GREEK.findall(sample))
    n_ara = len(_ARABIC.findall(sample))
    n_fr = len(_FR_DIACRITICS.findall(sample))
    n_de = len(_DE_DIACRITICS.findall(sample))

    if n_cjk / total > 0.05:
        return "zh"
    if n_cyr / total > 0.10:
        return "ru"
    if n_grk / total > 0.10:
        return "el"
    if n_ara / total > 0.10:
        return "ar"
    if n_lat / total > 0.20:
        # 法语/德语的判别只看变音符号密度 —— 这两语言的变音符号在
        # 长文本中稳定出现, 而英语几乎没有。
        if n_de >= 3 and n_de / max(n_lat, 1) > 0.004 and n_fr / max(n_lat, 1) < 0.002:
            return "de"
        if n_fr >= 3 and n_fr / max(n_lat, 1) > 0.003:
            return "fr"
        return "en"
    return "und"


# ================================================================ 文件名解析
_KNOWN_AUTHORS = [
    # (匹配模式, 规范名, 角色)
    (r"lacan|拉康", "Jacques Lacan", "psychoanalyst"),
    (r"freud|弗洛伊德|佛洛依德", "Sigmund Freud", "psychoanalyst"),
    (r"miller", "Jacques-Alain Miller", "psychoanalyst"),
    (r"maleval", "Jean-Claude Maleval", "psychoanalyst"),
    (r"soler", "Colette Soler", "psychoanalyst"),
    (r"žizek|zizek|齐泽克|⻬泽克", "Slavoj Žižek", "philosopher"),
    (r"fink", "Bruce Fink", "psychoanalyst"),
    (r"克莱朗博|clérambault|clerambault", "Gaëtan Gatian de Clérambault", "psychiatrist"),
    (r"沈志中", "沈志中", "scholar"),
    (r"吴琼", "吴琼", "scholar"),
    (r"霍默|homer", "Sean Homer", "scholar"),
    (r"埃文斯|evans", "Dylan Evans", "scholar"),
    (r"jaspers", "Karl Jaspers", "psychiatrist"),
    (r"henri ey|henri_ey", "Henri Ey", "psychiatrist"),
    (r"程抱一", "François Cheng", "scholar"),
    (r"redmond", "Jonathan D. Redmond", "psychoanalyst"),
    (r"rogers", "Annie G. Rogers", "scholar"),
    (r"hook", "Derek Hook", "scholar"),
    (r"vanheule", "Stijn Vanheule", "scholar"),
    (r"mills", "Jon Mills", "psychoanalyst"),
    (r"downing", "David L. Downing", "psychoanalyst"),
    (r"片岡一竹", "片岡一竹", "scholar"),
    (r"荣格|jung", "Carl Gustav Jung", "psychoanalyst"),
    (r"coffman", "Chris Coffman", "scholar"),
    (r"blom", "Jan Dirk Blom", "psychiatrist"),
    (r"若埃尔·多|joël dor", "Joël Dor", "psychoanalyst"),
    (r"laplanche|拉普朗拾", "Laplanche", "psychoanalyst"),
    (r"pontalis|彭塔利斯", "Pontalis", "psychoanalyst"),
]

# 拉康研讨班期号 (罗马数字 ↔ 阿拉伯数字)
_ROMAN = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20, "xxi": 21,
    "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25, "xxvi": 26, "xxvii": 27,
}
_SEMINAR_TITLES = {
    1: "Les écrits techniques de Freud",
    2: "Le moi dans la théorie de Freud et dans la technique de la psychanalyse",
    3: "Les psychoses",
    4: "La relation d'objet",
    5: "Les formations de l'inconscient",
    6: "Le désir et son interprétation",
    7: "L'éthique de la psychanalyse",
    8: "Le transfert",
    9: "L'identification",
    10: "L'angoisse",
    11: "Les quatre concepts fondamentaux de la psychanalyse",
    12: "Problèmes cruciaux pour la psychanalyse",
    13: "L'objet de la psychanalyse",
    14: "La logique du fantasme",
    15: "L'acte psychanalytique",
    16: "D'un Autre à l'autre",
    17: "L'envers de la psychanalyse",
    18: "D'un discours qui ne serait pas du semblant",
    19: "...ou pire",
    20: "Encore",
    21: "Les non-dupes errent",
    22: "R.S.I.",
    23: "Le sinthome",
    24: "L'insu que sait de l'une-bévue s'aile à mourir",
    25: "Le moment de conclure",
    26: "La topologie et le temps",
    27: "Dissolution",
}

# 文件名中需要剥离的"站点/打包"噪声
_SITE_NOISE = re.compile(
    r"\((?:z-library|1lib|z-lib|libgen)[^)]*\)|\[Z-Library\]|\(Z-Library\)|"
    r"\(z-library\.sk[^)]*\)|z-library\.sk|1lib\.sk|z-lib\.sk|libgen\.li|z-lib\.io",
    re.I,
)
_PART_NOISE = re.compile(r"[-_ ]?part[-_ ]?0?\d+[-_ ]?pages?[-_ ]?[\d\-]+", re.I)


def parse_filename(stem: str) -> dict:
    """从文件名推断 作者 / 标题 / 期号 / 版本语言 / 分卷。纯启发式, 全部标注推断。"""
    raw = stem
    s = _SITE_NOISE.sub(" ", stem)
    s = _PART_NOISE.sub(" ", s)
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -_.")

    info = {
        "possible_author": None,
        "possible_title": None,
        "seminar_number": None,
        "seminar_title": None,
        "edition_languages": [],
        "split_part": None,
        "parse_confidence": "low",
        "parse_method": "filename-heuristic",
    }

    # --- 分卷 (part-01-pages-1-104)
    m = re.search(r"part[-_ ]?(\d+)[-_ ]?pages?[-_ ]?(\d+)[-_ ]?(\d+)", raw, re.I)
    if m:
        info["split_part"] = {
            "part": int(m.group(1)),
            "page_from": int(m.group(2)),
            "page_to": int(m.group(3)),
        }

    # --- 研讨班期号: 【中英】23圣状 / 研讨班01期 / Seminar X / S3 / 05 Lacan
    #     / 讲座1（法文15）—— 这批法文讲座按讲座序号计，与研讨班共用一个号段
    # 按「明确程度」降序匹配。这一点很关键：
    # 书名里的罗马数字（`… Book X (Z-lib.io)`）比文件名里显式的「23期」弱得多，
    # 所以 `Book <roman>` 必须排在最后 —— 否则 S23 的中英对照本会被劫持成 S10
    # （实测发生过的假阳性，见 test_23）。
    for pat, conv in [
        (r"研讨班\s*(\d{1,2})\s*期", lambda x: int(x)),
        (r"第\s*([0-9]{1,2})\s*期", lambda x: int(x)),
        (r"第([一二三四五六七八九十百零]+)期", None),
        (r"讲座\s*(\d{1,2})", lambda x: int(x)),
        (r"^\s*【[^】]*】\s*(\d{1,2})\s*(?=[\u4e00-\u9fffA-Za-z])", lambda x: int(x)),
        (r"\bS(\d{1,2})\b", lambda x: int(x)),
        (r"^(\d{2})\s+[Ll]acan\b", lambda x: int(x)),
        # —— 最弱：书名/丛书名里的期号，只在以上都没命中时才用
        (r"[Ss]eminar\s*(?:of\s*Jacques\s*Lacan,?\s*)?(?:Book\s*)?([IVXLC]{1,6})\b", None),
        (r"\bBook\s*([IVXLC]{1,6}|\d{1,2})\b", None),
    ]:
        m = re.search(pat, s)
        if not m:
            continue
        tok = m.group(1)
        if tok.isdigit():
            info["seminar_number"] = int(tok)
        elif tok.lower() in _ROMAN:
            info["seminar_number"] = _ROMAN[tok.lower()]
        else:
            _cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                   "七": 7, "八": 8, "九": 9, "十": 10, "二十": 20,
                   "二十三": 23}
            info["seminar_number"] = _cn.get(tok)
        if info["seminar_number"]:
            break

    if info["seminar_number"] in _SEMINAR_TITLES:
        info["seminar_title"] = _SEMINAR_TITLES[info["seminar_number"]]

    # --- 版本语言标记
    if "中英" in raw:
        info["edition_languages"] = ["zh", "en"]
    elif "中法" in raw or "法文" in raw:
        info["edition_languages"] = ["zh", "fr"]
    elif "双语" in raw:
        info["edition_languages"] = ["zh", "en"]
    elif re.match(r"^【中】", raw) or "中文版" in raw or "中译" in raw or "中文文字版" in raw:
        info["edition_languages"] = ["zh"]
    elif "汉化版" in raw:
        info["edition_languages"] = ["zh"]
    elif "translated_en_to_zh" in raw or "_中文精修版" in raw:
        info["edition_languages"] = ["zh"]

    # --- 作者
    lower = s.lower()
    for pat, name, _role in _KNOWN_AUTHORS:
        if re.search(pat, lower):
            info["possible_author"] = name
            break

    # --- 标题
    title = None
    m = re.search(r"[《【]([^》】]{2,60})[》】]", s)
    if m:
        title = m.group(1)
    if not title:
        t = re.sub(r"^[【\[(][^】\])]*[】\])]\s*", "", s).strip()
        t = re.sub(r"\s*[（(]\s*(?:z-library|1lib|z-lib)[^)]*\)\s*$", "", t, flags=re.I)
        t = re.sub(r"^\d{1,3}[-\s]+", "", t)
        if t and len(t) >= 4:
            title = t.strip(" -_·")
    if title:
        info["possible_title"] = re.sub(r"\s{2,}", " ", title).strip()

    # --- 置信度
    score = 0
    score += 2 if info["possible_author"] else 0
    score += 2 if info["possible_title"] else 0
    score += 1 if info["seminar_number"] else 0
    score += 1 if info["edition_languages"] else 0
    info["parse_confidence"] = "high" if score >= 4 else ("medium" if score >= 2 else "low")
    return info


# ================================================================ 源类型判定
def classify_source_type(rel_parts, ext, seminar_number=None, stem=""):
    """按目录上下文 + 文件名给出源类型。

    注意：rel_parts 只包含文件所在的中间目录（不含文件名），顶层目录里的文件
    rel_parts 可能为空 —— 因此必须用 join 后的整串做子串判断，不能逐段等值比较。
    """
    joined = "/".join(rel_parts)
    name = stem or ""
    is_note_name = bool(re.search(r"想法|笔记|整理|记录|討論|讨论", name))

    if "研讨班" in joined or "讲座" in joined:
        return "seminar_primary"
    if seminar_number and re.search(r"研讨班|seminar|讲座", name, re.I):
        return "seminar_primary"
    if "Écrits" in joined or "ecrits" in joined.lower():
        return "ecrits_primary"
    if "卡特尔" in joined or "卡特尔" in name:
        return "case_meeting"
    if "想法" in joined:
        if is_note_name or ext in (".docx", ".doc"):
            return "research_note"
    if "原版文本文献" in joined:
        return "secondary_source"
    if "精神病" in joined:
        # 该目录里既有拉康派二手研究，也有中文研究笔记/翻译稿
        if "拉康论精神病" in name:
            return "secondary_source"
        if is_note_name:
            return "research_note"
        if ext in (".doc", ".docx"):
            return "research_note"
        return "secondary_source"
    if "相关书籍" in joined:
        if is_note_name:
            return "research_note"
        if ext in (".docx",):
            return "research_note"
        return "secondary_book"
    if "图片" in joined:
        return "image_asset"
    if ext == ".md":
        return "note"
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"):
        return "image_asset"
    return "unknown"


# ================================================================ 文本抽取
def _read_zip_text(path, names_filter, limit=200000):
    """从 docx/epub 这类 zip 容器里抽纯文本。"""
    chunks = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if not names_filter(n):
                continue
            try:
                data = z.read(n)
            except Exception:
                continue
            txt = data.decode("utf-8", "ignore")
            txt = re.sub(r"<[^>]+>", " ", txt)
            txt = re.sub(r"&[a-z]+;", " ", txt)
            chunks.append(txt)
            if sum(len(c) for c in chunks) > limit:
                break
    return " ".join(chunks)[:limit]


def extract_pdf(path):
    meta = {"page_count": None, "pdf_meta": {}, "encrypted": False}
    text = ""
    if not HAS_PYPDF:
        meta["error"] = "pypdf-unavailable"
        return text, meta, "UNPARSED"
    try:
        reader = PdfReader(path, strict=False)
        meta["encrypted"] = bool(reader.is_encrypted)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return "", meta, "ENCRYPTED"
        try:
            meta["page_count"] = len(reader.pages)
        except Exception:
            meta["page_count"] = None
        try:
            im = reader.metadata or {}
            for k in ("/Title", "/Author", "/Producer", "/Creator", "/Subject"):
                v = im.get(k)
                if v:
                    meta["pdf_meta"][k.lstrip("/").lower()] = str(v)[:300]
        except Exception:
            pass
        n = meta["page_count"] or 0
        idxs = []
        if n:
            # 均匀抽样至多 12 页：只看开头几页会把"正文有文字层、前几页是图版"
            # 的书误判成扫描件；均匀抽样能显著降低这种假阳性。
            k = min(12, n)
            idxs = sorted({int(round(i * (n - 1) / (k - 1))) if k > 1 else 0
                           for i in range(k)})
        n_sampled = 0
        n_with_text = 0
        for i in idxs:
            try:
                t = reader.pages[i].extract_text() or ""
            except Exception:
                continue
            n_sampled += 1
            if len(t.strip()) > 20:
                n_with_text += 1
            text += t + "\n"
        meta["pages_sampled"] = n_sampled
        meta["pages_sampled_with_text"] = n_with_text
        text = text[:400000]
        if not text.strip():
            # 一页文字都没抽到
            if (n or 0) > 3:
                return text, meta, "NEEDS_OCR"
            return text, meta, "EMPTY_TEXT"
        if n_sampled and n_with_text == 0:
            return text, meta, "NEEDS_OCR"
        # 抽到的文字量按抽样页数折算，低于阈值视为文字层不可用
        if n_sampled and len(text.strip()) / max(n_sampled, 1) < 120 and (n or 0) > 20:
            return text, meta, "NEEDS_OCR"
        return text, meta, "PARSED"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"[:200]
        return "", meta, "UNPARSED"


def extract_docx(path):
    meta = {}
    text = ""
    if HAS_DOCX:
        try:
            d = _docx.Document(path)
            cp = d.core_properties
            # ⚠️ 只在 docx **真的带** docProps/core.xml 时才记录核心属性。
            # 否则 python-docx 会用当前时间**合成** created/modified、并给一个
            # 占位 title（"Word Document"）—— 那描述的是「扫描时刻」而不是文档，
            # 记下来既破坏幂等性（两次扫描结果不同），也是不诚实的元数据。
            with zipfile.ZipFile(path) as _z:
                _has_core = any(n.endswith("core.xml") for n in _z.namelist())
            if _has_core:
                meta["docx_meta"] = {
                    k: str(getattr(cp, k))
                    for k in ("title", "author", "subject", "created", "modified")
                    if getattr(cp, k, None)
                }
            else:
                meta["docx_meta"] = {}
                meta["docx_meta_note"] = "无 docProps/core.xml，未记录核心属性（避免合成值）"
            meta["paragraph_count"] = len(d.paragraphs)
            text = "\n".join(p.text for p in d.paragraphs)[:200000]
            if text.strip():
                return text, meta, "PARSED"
        except Exception as e:
            meta["docx_error"] = f"{type(e).__name__}: {e}"[:200]
    # 回退: 直接读 zip 里的 document.xml
    try:
        text = _read_zip_text(path, lambda n: n.startswith("word/") and n.endswith(".xml"))
        if text.strip():
            return text, meta, "PARSED_FALLBACK"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"[:200]
    return text, meta, "UNPARSED"


def extract_epub(path):
    meta = {}
    text = ""
    if HAS_EPUBLIB:
        try:
            book = _epub.read_epub(path, options={"ignore_ncx": True})
            meta["epub_title"] = book.get_metadata("DC", "title")
            meta["epub_creator"] = book.get_metadata("DC", "creator")
            meta["epub_language"] = book.get_metadata("DC", "language")
            parts = []
            for it in book.get_items():
                if it.get_type() == 9:  # ITEM_DOCUMENT
                    try:
                        parts.append(it.get_content().decode("utf-8", "ignore"))
                    except Exception:
                        continue
                if sum(len(p) for p in parts) > 200000:
                    break
            raw = " ".join(parts)
            text = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"&[a-z]+;", " ", text)
            text = re.sub(r"\s{2,}", " ", text)[:200000]
            if text.strip():
                return text, meta, "PARSED"
        except Exception as e:
            meta["epub_error"] = f"{type(e).__name__}: {e}"[:200]
    try:
        text = _read_zip_text(path, lambda n: n.endswith((".xhtml", ".html", ".htm")))
        if text.strip():
            return text, meta, "PARSED_FALLBACK"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"[:200]
    return text, meta, "UNPARSED"


def extract_doc(path):
    """老式 .doc (OLE2). 无非标准库解析器, 尽力抽取可见 ASCII/CJK 片段。"""
    meta = {"note": "legacy .doc — run `textutil -convert txt` for full fidelity"}
    try:
        with open(path, "rb") as f:
            raw = f.read(4_000_000)
        txt = raw.decode("utf-16-le", "ignore")
        if len(_CJK.findall(txt)) < 20:
            txt = raw.decode("utf-8", "ignore")
        txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", txt)
        txt = re.sub(r"\s{2,}", " ", txt).strip()
        if len(txt) > 200:
            return txt[:200000], meta, "PARSED_PARTIAL"
        return txt, meta, "UNPARSED"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"[:200]
        return "", meta, "UNPARSED"


def extract_text_file(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                t = f.read(400000)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as e:
            return "", {"error": f"{type(e).__name__}: {e}"[:200]}, "UNPARSED"
        if not t.strip():
            # 解码成功但没有任何内容 → 不是解析失败, 是空文件
            return t, {"text_encoding": enc}, "EMPTY_TEXT"
        return t, {"text_encoding": enc}, "PARSED"
    return "", {"error": "undecodable"}, "UNDECODABLE"


def extract_binary_unsupported(path):
    """已知但不支持解析的二进制格式（音视频/压缩包/OLE 等）。"""
    return "", {"note": "known binary format — parsing not in scope for this phase"}, \
        "UNSUPPORTED_FORMAT"


def extract_image(path):
    meta = {}
    if not HAS_PIL:
        meta["note"] = "image — Pillow 未安装, 未读取尺寸; 本阶段不做 OCR"
        return "", meta, "IMAGE_NO_TEXT"
    try:
        with Image.open(path) as im:
            meta["image"] = {"width": im.width, "height": im.height,
                             "mode": im.mode, "format": im.format}
            meta["note"] = "image — no OCR in this phase"
        return "", meta, "IMAGE_NO_TEXT"
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"[:200]
        return "", meta, "UNPARSED"


# ================================================================ 重复检测
def normalize_name(stem: str) -> str:
    s = unicodedata.normalize("NFKC", stem).lower()
    s = _SITE_NOISE.sub("", s)
    s = re.sub(r"[\s_\-–—·,，。.()（）\[\]【】《》'\"’”“]+", "", s)
    return s


def build_duplicate_groups(records):
    """三路重复检测: 内容同一 / 文件名归一同一 / 同书分卷。"""
    groups = []

    # 1) sha256 精确同一
    by_hash = defaultdict(list)
    for r in records:
        if r.get("sha256"):
            by_hash[r["sha256"]].append(r["rel_path"])
    for h, paths in by_hash.items():
        if len(paths) > 1:
            groups.append({
                "group_id": f"dup.sha256.{h[:12]}",
                "kind": "IDENTICAL_CONTENT",
                "confidence": "high",
                "reason": "sha256 完全相同 —— 字节级重复",
                "members": sorted(paths),
                "action": "KEEP_ALL_DO_NOT_DELETE (用户明确要求不删除重复)",
            })

    # 2) 归一化文件名同一 (内容可能不同: 重排版/OCR 差异)
    by_name = defaultdict(list)
    for r in records:
        if r["extension"] in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            continue
        by_name[normalize_name(r["stem"])].append(r["rel_path"])
    for n, paths in by_name.items():
        if len(paths) > 1 and not any(
            set(paths) <= set(g["members"]) for g in groups
        ):
            groups.append({
                "group_id": f"dup.name.{hashlib.sha1(n.encode()).hexdigest()[:12]}",
                "kind": "SAME_NAME_DIFFERENT_BYTES",
                "confidence": "medium",
                "reason": "归一化文件名相同但 sha256 不同 —— 需人工比对版本/OCR 质量",
                "members": sorted(paths),
                "action": "REVIEW_MANUALLY",
            })

    # 3) 同书分卷: 去掉 part-N-pages 后书名相同
    by_book = defaultdict(list)
    for r in records:
        if not r.get("split_part"):
            continue
        base = _PART_NOISE.sub("", r["stem"])
        base = normalize_name(base)
        by_book[base].append(r["rel_path"])
    for b, paths in by_book.items():
        if len(paths) > 1:
            groups.append({
                "group_id": f"dup.split.{hashlib.sha1(b.encode()).hexdigest()[:12]}",
                "kind": "SAME_BOOK_SPLIT_PARTS",
                "confidence": "high",
                "reason": "同一本书被切成多个 part-*-pages-* 文件 —— 逻辑上是同一 Document",
                "members": sorted(paths),
                "action": "MERGE_AT_DOCUMENT_LEVEL (物理文件保持不动)",
            })

    return sorted(groups, key=lambda g: (g["kind"], g["group_id"]))


# ============================================================ 逻辑文档归并
def assign_document_ids(records, dup_groups):
    """为每条 record 计算逻辑 document_id。

    为什么需要：inventory 里的「4 组字节级重复 + 5 组同书分卷」不能只是报告中的
    一段文字 —— 下游（vault 的 document 层、溯源链、去重）必须能机械消费它。
    document_id 就是 inventory 与 document 层之间的桥。

    规则（确定性、可重跑）：
      1. 字节级重复（sha256 相同）→ 同一个 document_id（`doc.dup-<hash12>`）
      2. 同书分卷（同一作品切成的 part-N-pages-M-K）→ 同一个 document_id
         （`doc.work-<规范书名hash12>`）
      3. 其余 → 由「规范化文件名 + 内容 hash 前 8 位」派生
         （不同文件不会碰撞；同名不同内容也不会被误合并）

    注意：只做**逻辑**归并。物理文件一律不动、不重命名、不删除。
    """
    by_rel = {r["rel_path"]: r for r in records}
    doc_of = {}

    # 1) 字节级重复
    for g in dup_groups:
        if g["kind"] != "IDENTICAL_CONTENT":
            continue
        h = g["group_id"].rsplit(".", 1)[-1]
        did = f"doc.dup-{h}"
        for m in g["members"]:
            doc_of[m] = did

    # 2) 同书分卷（以「去掉 part-*-pages-* 的规范名」为键）
    def work_key(r):
        base = _PART_NOISE.sub("", r["stem"])
        base = _SITE_NOISE.sub("", base)
        base = re.sub(r"[\s_]+", " ", base).strip(" -_.")
        return normalize_name(base)

    split_key_doc = {}
    for r in records:
        if not r.get("split_part"):
            continue
        k = work_key(r)
        did = split_key_doc.setdefault(
            k, "doc.work-%s" % hashlib.sha1(k.encode("utf-8")).hexdigest()[:12])
        # 分卷优先归到作品层；若该文件本身也在字节级重复组里，作品层更具解释力
        doc_of[r["rel_path"]] = did

    # 3) 其余
    for r in records:
        if r["rel_path"] in doc_of:
            continue
        key = normalize_name(r["stem"]) or r["stem"]
        digest = (r.get("sha256") or "")[:8] or "nohash"
        did = "doc.%s-%s" % (
            re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:60] or "unnamed",
            digest,
        )
        doc_of[r["rel_path"]] = did

    for r in records:
        r["document_id"] = doc_of[r["rel_path"]]
    return doc_of


# ================================================================ 主流程
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(HASH_CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def run_inventory(source: str, out_dir: str, do_hash: bool = True,
                  max_files: int = 0) -> dict:
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"[FATAL] 源目录不存在或不是目录: {src}")

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    files = []
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        if p.name in (".DS_Store", "Thumbs.db", "desktop.ini"):
            continue
        if p.name.startswith("._"):
            continue
        files.append(p)
    files.sort(key=lambda p: str(p.relative_to(src)))
    if max_files:
        files = files[:max_files]

    records = []
    anomalies = []
    total_bytes = 0
    t0 = datetime.now(timezone.utc)

    for i, p in enumerate(files, 1):
        rel = str(p.relative_to(src))
        rel_parts = rel.split(os.sep)
        ext = p.suffix.lower()
        try:
            st = p.stat()
            size = st.st_size
            total_bytes += size
        except Exception as e:
            anomalies.append({"rel_path": rel, "kind": "STAT_FAILED", "detail": str(e)[:200]})
            continue

        rec = {
            "rel_path": rel,
            "path": str(p),
            "filename": p.name,
            "stem": p.stem,
            "extension": ext,
            "size": size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                     .isoformat(timespec="seconds"),
            "sha256": None,
            "parse_status": "NOT_ATTEMPTED",
            "text_chars_sampled": 0,
            "estimated_language": "und",
            "language_confidence": "none",
            "page_count": None,
            "word_count": None,
        }

        if do_hash:
            try:
                rec["sha256"] = sha256_of(p)
            except Exception as e:
                anomalies.append({"rel_path": rel, "kind": "HASH_FAILED",
                                  "detail": f"{type(e).__name__}: {e}"[:200]})

        # ---- 内容抽取
        fmt_meta = {}
        text = ""
        try:
            if ext == ".pdf":
                text, fmt_meta, status = extract_pdf(p)
            elif ext == ".docx":
                text, fmt_meta, status = extract_docx(p)
            elif ext == ".doc":
                text, fmt_meta, status = extract_doc(p)
            elif ext == ".epub":
                text, fmt_meta, status = extract_epub(p)
            elif ext in (".txt", ".md", ".markdown", ".html", ".htm", ".json", ".csv"):
                text, fmt_meta, status = extract_text_file(p)
            elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"):
                text, fmt_meta, status = extract_image(p)
            else:
                text, fmt_meta, status = "", {"note": "unknown extension"}, "UNSUPPORTED_FORMAT"
        except Exception as e:
            text, fmt_meta, status = "", {}, "UNPARSED"
            fmt_meta["error"] = f"{type(e).__name__}: {e}"[:200]

        rec["parse_status"] = status
        rec["text_chars_sampled"] = len(text or "")
        rec["format_meta"] = fmt_meta
        if fmt_meta.get("page_count"):
            rec["page_count"] = fmt_meta["page_count"]

        if text and text.strip():
            rec["estimated_language"] = detect_language(text)
            rec["language_confidence"] = "sampled" if len(text) > 2000 else "weak"
            rec["word_count"] = len(re.findall(r"[\w\u4e00-\u9fff]+", text))
        elif ext in (".txt", ".md", ".csv", ".json"):
            rec["estimated_language"] = "und"

        # ---- 文件名启发式
        rec.update(parse_filename(p.stem))
        rec["source_type"] = classify_source_type(
            rel_parts, ext, rec.get("seminar_number"), p.stem)

        # ---- 文件名语言提示（当内容抽不出来时用文件名兜底）
        if rec["estimated_language"] == "und":
            fn_lang = detect_language(p.stem)
            if fn_lang != "und":
                rec["estimated_language"] = fn_lang
                rec["language_confidence"] = "filename-only"

        # ---- 异常收集
        if size == 0:
            anomalies.append({"rel_path": rel, "kind": "ZERO_BYTE", "detail": "0 字节文件"})
        if status == "NEEDS_OCR":
            anomalies.append({"rel_path": rel, "kind": "NEEDS_OCR",
                              "detail": f"抽样 {rec['text_chars_sampled']} 字符 / "
                                        f"{rec['page_count']} 页 —— 疑为扫描件"})
        if status in PROBLEM_STATUSES:
            anomalies.append({
                "rel_path": rel, "kind": status,
                "detail": str(fmt_meta.get("error")
                              or fmt_meta.get("note")
                              or f"parse_status={status}")[:200],
            })
        if status == "PARSED_PARTIAL":
            anomalies.append({"rel_path": rel, "kind": "LEGACY_DOC_PARTIAL",
                              "detail": "老式 .doc 仅抽到部分文本, 建议 textutil 转换"})
        if "要重新ocr" in p.name or "要重新OCR" in p.name:
            anomalies.append({"rel_path": rel, "kind": "USER_MARKED_NEEDS_OCR",
                              "detail": "文件名中用户已标注「要重新ocr」"})

        records.append(rec)
        if i % 25 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}] {rel[:70]}", file=sys.stderr)

    # ---- 重复检测
    dup_groups = build_duplicate_groups(records)
    assign_document_ids(records, dup_groups)
    dup_index = {}
    for g in dup_groups:
        for m in g["members"]:
            dup_index.setdefault(m, []).append(g["group_id"])
    for r in records:
        ids = dup_index.get(r["rel_path"], [])
        r["duplicate_group_ids"] = ids
        r["duplicate_group"] = ids[0] if ids else None
        r["is_duplicate"] = bool(ids)

    # ---- 汇总
    ext_counter = Counter(r["extension"] for r in records)
    status_counter = Counter(r["parse_status"] for r in records)
    lang_counter = Counter(r["estimated_language"] for r in records)
    type_counter = Counter(r["source_type"] for r in records)
    dir_counter = Counter(r["rel_path"].split(os.sep)[0] for r in records)

    payload = {
        "schema": SCHEMA_VERSION,
        "generated_at": t0.isoformat(timespec="seconds"),
        "source_root": str(src),
        "source_readonly": True,
        "hash_enabled": do_hash,
        "totals": {
            "files": len(records),
            "bytes": total_bytes,
            "gib": round(total_bytes / (1024 ** 3), 3),
        },
        "by_extension": dict(sorted(ext_counter.items(), key=lambda kv: -kv[1])),
        "by_parse_status": dict(sorted(status_counter.items(), key=lambda kv: -kv[1])),
        "by_language": dict(sorted(lang_counter.items(), key=lambda kv: -kv[1])),
        "by_source_type": dict(sorted(type_counter.items(), key=lambda kv: -kv[1])),
        "by_top_dir": dict(sorted(dir_counter.items(), key=lambda kv: -kv[1])),
        "toolchain": {
            "python": sys.version.split()[0],
            "pypdf": HAS_PYPDF, "python_docx": HAS_DOCX,
            "ebooklib": HAS_EPUBLIB, "pillow": HAS_PIL,
            "yaml": HAS_YAML, "langdetect": HAS_LANGDETECT,
        },
        "duplicate_groups": dup_groups,
        "anomalies": anomalies,
        "records": records,
    }
    return payload


# ================================================================ 输出
CSV_FIELDS = [
    "rel_path", "path", "filename", "extension", "size", "sha256",
    "estimated_language", "language_confidence", "possible_author", "possible_title",
    "source_type", "parse_status", "page_count", "word_count", "text_chars_sampled",
    "seminar_number", "seminar_title", "edition_languages", "split_part",
    "parse_confidence", "document_id", "duplicate_group", "duplicate_group_ids",
    "is_duplicate", "mtime",
]


def write_csv(payload, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in payload["records"]:
            row = dict(r)
            row["edition_languages"] = "|".join(r.get("edition_languages") or [])
            row["duplicate_group_ids"] = "|".join(r.get("duplicate_group_ids") or [])
            sp = r.get("split_part")
            row["split_part"] = f"{sp['part']}:{sp['page_from']}-{sp['page_to']}" if sp else ""
            w.writerow(row)


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def write_report(payload, path):
    R = payload["records"]
    L = []
    a = L.append
    a("# Corpus Inventory Report — 拉康派精神分析项目内容")
    a("")
    a(f"> 生成时间 `{payload['generated_at']}`　·　schema `{payload['schema']}`")
    a(f"> 源目录 `{payload['source_root']}`　·　**只读扫描，未修改任何源文件**")
    a("")

    # 1 总览
    a("## 1. 总览")
    a("")
    a(f"- 文件总数 **{payload['totals']['files']}**")
    a(f"- 总体积 **{_fmt_bytes(payload['totals']['bytes'])}**")
    a(f"- 重复组 **{len(payload['duplicate_groups'])}**")
    a(f"- 异常项 **{len(payload['anomalies'])}**")
    a("")
    a("### 1.1 按扩展名")
    a("")
    a("| 扩展名 | 数量 | 占比 |")
    a("|---|---:|---:|")
    tot = max(payload["totals"]["files"], 1)
    for k, v in payload["by_extension"].items():
        a(f"| `{k}` | {v} | {v / tot * 100:.1f}% |")
    a("")
    a("### 1.2 按顶层目录")
    a("")
    a("| 目录 | 文件数 |")
    a("|---|---:|")
    for k, v in payload["by_top_dir"].items():
        a(f"| `{k}` | {v} |")
    a("")
    a("### 1.3 按解析状态")
    a("")
    a("| parse_status | 数量 | 含义 |")
    a("|---|---:|---|")
    _meaning = {
        "PARSED": "文本成功抽出",
        "PARSED_FALLBACK": "用回退路径抽出（非原生解析器）",
        "PARSED_PARTIAL": "只抽到部分文本（老式 .doc）",
        "NEEDS_OCR": "疑似扫描件，需 OCR",
        "EMPTY_TEXT": "有页面但无文字层",
        "IMAGE_NO_TEXT": "图片，本阶段不做 OCR",
        "UNSUPPORTED_FORMAT": "格式本阶段不支持",
        "UNPARSED": "解析失败",
        "UNDECODABLE": "无法判定编码",
        "NOT_ATTEMPTED": "未尝试",
    }
    for k, v in payload["by_parse_status"].items():
        a(f"| `{k}` | {v} | {_meaning.get(k, '')} |")
    a("")
    a("### 1.4 按语言")
    a("")
    a("| 语言 | 数量 |")
    a("|---|---:|")
    _langname = {"zh": "中文", "en": "英文", "fr": "法文", "de": "德文",
                 "ru": "俄文", "el": "希腊文", "ar": "阿拉伯文", "und": "未判定"}
    for k, v in payload["by_language"].items():
        a(f"| {k} ({_langname.get(k, k)}) | {v} |")
    a("")
    a("### 1.5 按 source_type")
    a("")
    a("| source_type | 数量 |")
    a("|---|---:|")
    for k, v in payload["by_source_type"].items():
        a(f"| `{k}` | {v} |")
    a("")

    # 2 重复
    a("## 2. 重复检测（仅标记，不删除）")
    a("")
    if not payload["duplicate_groups"]:
        a("未检测到重复。")
    else:
        for g in payload["duplicate_groups"]:
            a(f"### `{g['group_id']}` — {g['kind']} ({g['confidence']})")
            a("")
            a(f"{g['reason']}")
            a("")
            for m in g["members"]:
                sz = next((r["size"] for r in R if r["rel_path"] == m), 0)
                h = next((r["sha256"] for r in R if r["rel_path"] == m), None)
                a(f"- `{m}`  · {_fmt_bytes(sz)} · sha256 `{(h or 'n/a')[:16]}`")
            a("")
            a(f"**建议处置**：`{g['action']}`")
            a("")

    # 3 异常
    a("## 3. 异常与待处理")
    a("")
    kinds = Counter(x["kind"] for x in payload["anomalies"])
    if not kinds:
        a("无异常。")
    else:
        a("| kind | 数量 |")
        a("|---|---:|")
        for k, v in kinds.most_common():
            a(f"| `{k}` | {v} |")
        a("")
        for k, _ in kinds.most_common():
            a(f"### 3.x `{k}`")
            a("")
            for x in payload["anomalies"]:
                if x["kind"] == k:
                    a(f"- `{x['rel_path']}` — {x['detail']}")
            a("")

    # 4 研讨班矩阵
    a("## 4. 拉康研讨班覆盖率矩阵")
    a("")
    a("| 期号 | 法文标题 | 本地文件数 | 语言版本 |")
    a("|---|---|---:|---|")
    sem = defaultdict(list)
    for r in R:
        if r.get("seminar_number"):
            sem[r["seminar_number"]].append(r)
    for n in sorted(sem):
        langs = set()
        for r in sem[n]:
            langs.update(r.get("edition_languages") or [])
            if not r.get("edition_languages"):
                langs.add(r.get("estimated_language", "und"))
        a(f"| S{n} | {_SEMINAR_TITLES.get(n, '?')} | {len(sem[n])} | "
          f"{', '.join(sorted(langs))} |")
    if not sem:
        a("| — | 启发式未能识别出期号 | 0 | — |")
    a("")
    a(f"**覆盖率：{len(sem)} / 27 期**（S1–S27 中本地有文件的期数）")
    a("")

    # 5 top 文件
    a("## 5. 主要资料清单（按体积降序，前 40）")
    a("")
    a("| 文件 | 体积 | 语言 | 解析 | 作者推断 | 标题推断 |")
    a("|---|---:|---|---|---|---|")
    for r in sorted(R, key=lambda x: -x["size"])[:40]:
        a(f"| `{r['filename'][:58]}` | {_fmt_bytes(r['size'])} | "
          f"{r['estimated_language']} | {r['parse_status']} | "
          f"{(r.get('possible_author') or '—')[:22]} | "
          f"{(r.get('possible_title') or '—')[:40]} |")
    a("")

    # 6 证据分层建议
    a("## 6. Source Authority 分层建议（基于实测）")
    a("")
    auth = defaultdict(list)
    for r in R:
        st = r["source_type"]
        if st == "seminar_primary":
            auth["L1 PRIMARY"].append(r)
        elif st == "ecrits_primary":
            auth["L1 PRIMARY"].append(r)
        elif st in ("secondary_source", "secondary_book"):
            auth["L2 SECONDARY"].append(r)
        elif st in ("research_note", "case_meeting"):
            auth["L3 RESEARCH NOTE"].append(r)
        else:
            auth["L0 RAW / 未判"].append(r)
    for k in sorted(auth):
        a(f"- **{k}** — {len(auth[k])} 个文件")
    a("")

    # 7 工具链
    a("## 7. 扫描工具链")
    a("")
    a("```json")
    a(json.dumps(payload["toolchain"], ensure_ascii=False, indent=2))
    a("```")
    a("")
    a("---")
    a("")
    a("*本报告由 `_scripts/inventory_corpus.py` 生成。源目录全程只读。*")
    a("")
    Path(path).write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="只读语料盘点 (Lacanian Knowledge OS)")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--no-hash", action="store_true", help="跳过 sha256 (快速模式)")
    ap.add_argument("--max-files", type=int, default=0)
    add_stamp_flag(ap)
    args = ap.parse_args()

    print(f"[inventory] source = {args.source}", file=sys.stderr)
    payload = run_inventory(args.source, args.out,
                            do_hash=not args.no_hash,
                            max_files=args.max_files)

    out = Path(args.out).expanduser().resolve()
    jp = out / "corpus_inventory.json"
    cp = out / "corpus_inventory.csv"
    rp = out / "corpus_report.md"

    # 确定性时间戳：默认由内容推导（重跑无 diff），--stamp 才写真实时间
    apply_stamp(payload, stamp=args.stamp)
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(payload, cp)
    write_report(payload, rp)

    print(f"[inventory] files={payload['totals']['files']} "
          f"size={payload['totals']['gib']} GiB "
          f"dups={len(payload['duplicate_groups'])} "
          f"anomalies={len(payload['anomalies'])}", file=sys.stderr)
    print(f"[inventory] -> {jp}", file=sys.stderr)
    print(f"[inventory] -> {cp}", file=sys.stderr)
    print(f"[inventory] -> {rp}", file=sys.stderr)


if __name__ == "__main__":
    main()
