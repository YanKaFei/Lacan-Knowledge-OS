#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_obsidian_integration.py — 4D.3 契约自检（只读，供套件调用）"""
from __future__ import annotations
import os, re, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__)); VAULT=os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, VAULT)

def main():
    problems=[]
    from obsidian_adapter import adapter as A, vault as V, links as K
    from scholarly_api import policy as POL
    d=V.detect()
    if not d["is_obsidian_vault"]: problems.append("未检测到既有 Obsidian vault（应复用）")
    v=V.Vault()
    if not v.is_project_default: problems.append("默认工作区根不是项目工作区")
    if POL.classify(os.path.join(v.root,"Research","x.md"))!="USER_WORKSPACE":
        problems.append("工作区 note 不在 USER_WORKSPACE")
    for bad in ("../x.md","/etc/passwd"):
        try: v.resolve(bad); problems.append("路径策略未拒绝 %s"%bad)
        except V.VaultError: pass
    if K.wikilink("A|B.md")!="[[AB]]": problems.append("wikilink 未做安全化")
    # 工作区必须被学术校验器跳过（工作区 ≠ 知识节点）
    src=open(os.path.join(VAULT,"_scripts","_tools","validate_vault.py"),encoding="utf-8").read()
    if '"_workspace"' not in src: problems.append("validate_vault 未跳过 _workspace")
    # 适配层不得 import 核心
    core=("knowledge_api","research_answer","synthesis_entailment","eval_integrity","core_freeze")
    adir=os.path.join(VAULT,"obsidian_adapter")
    for fn in sorted(os.listdir(adir)):
        if not fn.endswith(".py"): continue
        s=open(os.path.join(adir,fn),encoding="utf-8").read()
        for mod in core:
            if re.search(r"^\s*(import|from)\s+%s\b"%mod, s, re.M):
                problems.append("%s 直接 import 核心 %s"%(fn,mod))
    # QA vault 与截图证据（报告在 vault 外 → 报告本身不进图谱）
    qa=os.path.join(VAULT,"_workspace","obsidian_qa")
    qv=os.path.join(qa,"vault")
    for rel in ("GRAPH_QA.md","vault/_System/mappings/entity_note_map.json"):
        if not os.path.isfile(os.path.join(qa,rel)): problems.append("缺 QA 工件：%s"%rel)
    if not os.path.isdir(os.path.join(qv,"Passages")): problems.append("QA vault 缺 Passages/")
    # QA vault 的链接纪律（现算；报告写死的内容会过期，实测踩过）
    if os.path.isdir(qv):
        from obsidian_adapter.frontmatter import parse_frontmatter
        md=["/".join(os.path.relpath(os.path.join(d,f),qv).split(os.sep))
            for d,_x,fs in os.walk(qv) for f in fs if f.endswith(".md")]
        present=set(md); dangling=[]; embeds=[]
        for rel in sorted(md):
            txt=open(os.path.join(qv,rel),encoding="utf-8").read()
            if "![[" in txt: embeds.append(rel)
            fm,_=parse_frontmatter(txt)
            if not (fm or {}).get("type"): problems.append("QA note 无 type：%s"%rel)
            for t in re.findall(r"!?\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", txt):
                t=t.strip(); t=t[:-3] if t.endswith(".md") else t
                if t+".md" not in present: dangling.append("%s→%s"%(rel,t))
        if not md: problems.append("QA vault 里没有 note")
        if dangling: problems.append("QA vault 有悬空 wikilink：%s"%dangling[:3])
        if embeds: problems.append("QA vault 有 corpus 资产 embed（破图）：%s"%embeds[:3])
    shots=os.path.join(VAULT,"_workspace","ui_qa")
    for s in ("E_saved_research.png","F_saved_abstention.png"):
        if not os.path.isfile(os.path.join(shots,s)): problems.append("缺 UI 保存截图：%s"%s)
    # 冻结
    r=subprocess.run([sys.executable, os.path.join(HERE,"core_freeze.py"),"--verify","--quiet"],
                     capture_output=True, text=True, cwd=VAULT)
    if r.returncode!=0: problems.append("core freeze 校验失败：%s"%(r.stdout+r.stderr)[-200:])
    if problems:
        print("FAIL Obsidian 集成契约自检未通过：")
        for p in problems[:10]: print("  - %s"%p)
        return 1
    print("Obsidian 集成契约自检通过：复用既有 vault / 工作区隔离 / 路径策略 / wikilink 安全 / "
          "QA vault 无悬空链与破图嵌入 / 适配层不 import 核心 / QA 工件与截图齐备 / core freeze OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
