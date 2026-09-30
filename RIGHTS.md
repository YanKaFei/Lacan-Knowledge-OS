# RIGHTS.md — rights, permitted use, and the questions only you can answer

> **This page is deliberately serious.** It separates two things that are easy to confuse:
> the **engine**, which is open source, and the **corpus**, which is other people's work.
> It states what we know, what we do not know, and what we cannot decide for you.
>
> It is **not legal advice**. No one at this project is your lawyer, and no statement here
> creates a licence that the rights holders have not granted. Where your situation is unclear,
> the determination — and the risk — are yours.

---

## 1. Two artifacts, two different legal situations

| Artifact | Where it lives | Rights status | What you may do |
|---|---|---|---|
| **Engine** — all code in this repository | `github.com/YanKaFei/Lacan-Knowledge-OS` (public) | © the project contributors, released under **Apache-2.0** | use, modify, redistribute, embed, build commercial products on it, subject to the licence's notice requirements |
| **Reference corpus** — Lacan seminar texts, passage store, derived indexes | `github.com/YanKaFei/Lacan-Knowledge-OS-corpus` (**public**) | **third-party copyright.** The project holds **no** rights in it and grants none | **research and study only.** Public visibility is not a licence: **not** licensed for commercial use, redistribution, mirroring, repackaging, or serving to third parties. The determination is the user’s. |
| **Demo corpus** — public-domain clinical texts | this repository, `demo-corpus/` | **public domain** (Falret d. 1902 · Binet d. 1911 · Janet d. 1947, France/EU term expired) | use, modify, redistribute freely |

The Apache-2.0 licence on the engine **does not extend to any corpus text**. Reading the licence
and concluding "therefore I may redistribute the seminars" is the single most likely mistake.

---

## 2. What is actually inside the reference corpus

The corpus aggregates three independent sources, each with its own rights holder. The project's own
registry records them in `_data/passage_store/corpus_sources.jsonl`:

| Source id | What it is | Position |
|---|---|---|
| `corpus-source.staferla` | a publicly readable French **working transcription** of the seminars (S1–S27) | being readable online is **not** a licence to redistribute. The transcription site's own legal position is not documented here, and we do not assert one. |
| `corpus-source.seuil-print` | text extracted from the **Seuil print edition** (S1–S5), with page numbers | an in-copyright commercial edition. Extracting, storing and redistributing its text engages the publisher's and the author's estate's rights. |
| `corpus-source.zh-translation-project` | a **community Chinese translation** project (the surviving copy) | a translation is a **derivative work**: it carries the translator's rights *and* the underlying author's rights. Holding the only copy is not the same as holding the rights. |

Lacan died in 1981. In France and the EU, rights run for 70 years after death, so the underlying
texts remain in copyright for decades. In the United States the analysis differs (publication date,
renewal, fair use), but **nothing in this project asserts that any part of this corpus is freely
redistributable anywhere**.

---

## 3. Three arguments we hear, and why they do not settle the question

**"Someone else transcribed or scanned it, so it is derivative work, not the original."**
Derivation adds a rights holder; it does not remove one. A transcription or a scan of a protected
work is still a reproduction of that work, and publishing it engages the original rights.

**"I am not using it commercially."**
Non-commerciality is relevant to *private study* and can weigh in a fair-use analysis. It is not a
licence, and it does not convert **public distribution of an entire protected work** into a
permitted act. Distributing a full corpus to the public is a different act from reading it at home.

**"Nothing happened to anyone else who did it."**
Enforcement is uneven, not absent. French publishers and the relevant estates have pursued
unauthorised circulation of these texts, and hosting platforms act on notices with takedowns and
account sanctions. A takedown is a bad week; it also removes the repository that other people may
depend on.

None of this means you personally are doing something wrong by **reading** material you obtained
lawfully for your own study. It does mean that the decision to **publish, mirror, or build a
commercial product on** that material is not one this project can make for you — or on your behalf.

---

## 4. What public availability is, and is not

The companion corpus repository is **public** — anyone can download the pack. That is a hosting
decision made to let researchers obtain the material; it transfers no rights. Concretely:

| Permitted | Not permitted |
|---|---|
| download and keep it on your own machine | commercial use of any kind, including consulting deliverables or paid products |
| use it for your own academic research and study | redistribute, mirror, repackage or bundle the corpus or a corpus pack |
| cite passages in your own scholarly writing, with attribution to the sources as registered | serve corpus text to third parties (an API, a website, an app, a dataset release) |
| build your own derived indexes locally | present the corpus, or a derivative, as your own licensed material |
| pack it for a colleague so they can install it themselves | use it as training data for a model you distribute or deploy publicly |

If you need any item in the right-hand column, you must obtain the rights yourself from the
relevant rights holders. That conversation is between you and them.

---

## 5. What this project does to keep the boundary real

These are enforced practices, not intentions:

1. **The public repository contains no corpus text.** Its production is scripted
   (`_scripts/_tools/build_public_edition.py`) and then **negatively verified**: fragments sampled
   from the reference corpus are searched for across the published tree; a single hit rejects the
   build. See [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md).
2. **The corpus repository is public for research access, and its boundary is stated in its own
   README**, with a warning banner rather than a footnote. The pack it serves is hash-manifested so an
   altered or partial copy cannot pass verification (`tools/fetch-corpus.py`).
3. **Packs are made, not published.** `tools/pack-corpus.py` produces a corpus pack for a channel
   *you* control; nothing in this project distributes it for you.
4. **Agents are instructed not to cross the line.** [`AGENTS.md`](AGENTS.md) tells any AI working
   in this repository: never make the corpus repository public, never copy corpus text into the
   engine, never fabricate an answer that the corpus cannot support.
5. **The engine's scholarly core is frozen.** Correcting the record never means editing a hash by
   hand — semantic change goes through a Core Change Request with evidence.

---

## 6. If you need something you can publish, share or sell

Use the **engine** with a corpus you have the right to use. All three routes are fully supported:

| Route | Start here |
|---|---|
| **Public-domain material** — the demo corpus ships Falret 1890, Binet 1892, Janet 1909 | [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md) · `python3 tools/build_demo_corpus.py .` |
| **Your own texts** — your writing, your scans of works you hold rights in, your own translations of public-domain works | [`CORPUS.md`](CORPUS.md) |
| **Licensed editions** — a publisher, library or database licence that permits derived text stores | [`CORPUS.md`](CORPUS.md) — keep the licence text alongside the corpus |

The engine is corpus-agnostic: the builders, validators, retrieval, evidence contract and
abstention discipline all work the same on any corpus you supply.

---

## 7. Rights concerns and contact

If you hold rights in any material that appears in this project or in the companion corpus
repository and you want it removed, clarified, attributed differently, or access reviewed:

- open an issue on the engine repository (no corpus text in the issue, please), or
- contact the maintainer through the repository profile.

We will act on a substantiated request. Removing material on request is not an admission about
anything; it is the only responsible default.

---

## 中文要点（同一页的中文摘要）

- **引擎与语料是两件事。** 本公开仓库的**代码**是 Apache-2.0，你可以自由使用、修改、再分发；
  它**不包含**任何语料文本，Apache-2.0 **也不覆盖**任何语料文本。
- **参考语料库是私有的**（`Lacan-Knowledge-OS-corpus`），集合了三种第三方来源：
  Staferla 法语工作转录、**瑟伊版印刷本**（S1–S5）的文本抽取、以及**社区中译项目**。
  这三者的权利都不属于本项目 —— 所以本项目**无权**把它们公开。
- **拿到访问权 ≠ 拿到授权。** 私自访问许可只允许**你本人、非商业的学术研究**：
  可以本地克隆、可以用来自已研究、可以在自己的学术写作里引用并注明来源；
  **不可以**公开仓库或任何 fork、**不可以**商用、**不可以**再分发/镜像/打包外传、
  **不可以**把语料做成对外提供的内容（网站/API/App）、**不可以**当作公开模型的训练数据。
- **"不是我扫描/转录的"、"我没商用"这两条都不构成再分发许可。**
  演绎或扫描只是**叠加**了一层权利，不会让原作品的权利消失；非商业性对**私人研读**有意义，
  但**把整部作品的全文公开分发**是另一个行为。
- **判断权在你。** 本页只陈述本项目掌握的事实与边界，**不构成法律意见**，也不能替你决定
  你的使用是否合法。若不确定，就只走下面这条安全路径。
- **需要能公开/商用的版本？** 用引擎 + **你有权使用的语料**：公有领域 demo 语料
  （Falret 1890 / Binet 1892 / Janet 1909，可自由分发）、你自己的文本、或已获授权的版本 ——
  见 [`CORPUS.md`](CORPUS.md) 与 [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md)。
- **权利人联系与下架请求**：见本页 §7（在本项目仓库提 issue / 通过仓库资料联系维护者）。
