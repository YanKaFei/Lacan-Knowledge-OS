<div align="center">

# Lacan Knowledge OS

**Un environnement de recherche fondé sur corpus pour la psychanalyse lacanienne.**
D'abord la preuve. Ensuite l'interprétation. Jamais la fabrication.

[English](README.md) · [中文](README.zh.md) · [日本語](README.ja.md) · [**Français**](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-6b4c2f?style=flat-square)](LICENSE)
[![Core](https://img.shields.io/badge/noyau%20savant-gel%C3%A9%20%C2%B7%2039%20composants-43403b?style=flat-square)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/r%C3%A9gression-146%20suites%20%C2%B7%200%20%C3%A9chec-3f6b4a?style=flat-square)](docs/SCHOLARLY_REGRESSION_SPEC_V1.md)
[![MCP](https://img.shields.io/badge/MCP-10%20outils%20%C2%B7%202025--11--25-6b4c2f?style=flat-square)](docs/MCP_TOOL_CONTRACTS.md)
[![Corpus](https://img.shields.io/badge/corpus-d%C3%A9p%C3%B4t%20compagnon%20%C2%B7%20usage%20savant-8a6d1f?style=flat-square)](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)

</div>

---

> ### La règle unique autour de laquelle le système est bâti
>
> *Chaque assertion doit pouvoir être rattachée à un numéro de passage.*
>
> Si le corpus ne peut pas soutenir une question, le système **s'abstient** — il ne répond pas
> à partir des connaissances du modèle. **Une abstention est un résultat, pas une erreur.**

---

> ## ⚠️ Droits et périmètre d'usage — à lire avant d'installer le corpus
>
> **Le moteur est open source. Le corpus ne l'est pas.** Deux objets, deux régimes :
>
> | | Licence / statut |
> |---|---|
> | **Code du moteur** (ce dépôt) | Apache-2.0 — usage, modification, redistribution, intégration dans un produit commercial |
> | **Corpus de référence** ([dépôt compagnon](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)) | **textes protégés par des tiers.** Accessible publiquement, **à des fins de recherche et d'étude uniquement** ; la visibilité publique n'est pas une licence — **aucune** licence commerciale, de redistribution ou de mise à disposition. |
> | **Corpus de démonstration** ([`corpus-demo-v1`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/tag/corpus-demo-v1) · [`demo-corpus/`](demo-corpus)) | domaine public (Falret 1890 · Binet 1892 · Janet 1909) — librement redistribuable |
>
> **Dit simplement.** Le corpus contient des **transcriptions de travail** des séminaires de Lacan,
> une **extraction de l'édition imprimée au Seuil** (S1–S5), et un **projet communautaire de traduction
> en chinois**. **Aucun de ces droits n'appartient à ce projet.** Il est publié ouvertement pour que les chercheurs puissent l'obtenir, et
> personnes qui ont besoin de ces textes pour leur propre recherche ; et **l'accès n'est pas une
> licence** : il n'autorise ni l'usage commercial, ni la redistribution, ni la mise en miroir, ni la
> republication, ni la mise à disposition de tiers, ni l'entraînement d'un modèle publié.
>
> **Savoir si votre usage est licite vous appartient** — ce projet ne peut pas répondre à votre place
> et ne fournit pas de conseil juridique. Analyse complète : [`RIGHTS.md`](RIGHTS.md).
>
> **S'il vous faut quelque chose de publiable, partageable ou commercialisable, associez le moteur à un
> corpus que vous avez le droit d'utiliser** : la démonstration de domaine public, vos propres textes,
> ou une édition sous licence. Ce chemin est pleinement pris en charge : [`CORPUS.md`](CORPUS.md) ·
> [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md).

---

## Ce que c'est

**Lacan Knowledge OS** transforme un corpus de séminaires et d'écrits en **réserve de preuves
citable**, et place un **noyau savant gelé** entre votre question et toute réponse.

<img src="assets/diagrams/architecture.svg" alt="Architecture : les agents entrent par MCP ; une couche produit repose sur un noyau savant gelé de 39 composants ; le corpus est fourni séparément et ne fait pas partie du moteur open source." width="100%">

| | Capacité | Ce qu'elle vous donne |
|---|---|---|
| 🔎 | **Research** | Poser une question → le noyau récupère des passages, construit un contrat de preuve, et **alors seulement** synthétise une réponse dont chaque affirmation passe la validation de citation et d'implication |
| 📖 | **Explore** | Lire le corpus directement : passages, séances, séminaires, concepts, terminologie — sans aucun modèle |
| 🔬 | **Evidence Inspector** | `Réponse → affirmation → passage → séance → séminaire → témoin/source`, avec le **segment exact cité** et sa fenêtre de contexte |
| 🗂️ | **Projects** | Transformer des exécutions répétées en un sujet de long terme (questions, hypothèses, passages, personnes, cas, bibliographie) |
| 📚 | **Bibliographie et citations** | Statut de révision, complétude des métadonnées, disponibilité par style **et la raison de l'indisponibilité** |
| ✍️ | **Passerelle Obsidian** | Les preuves et la validation restent ici ; votre compréhension, vos notes et votre écriture vivent dans votre vault |

### La chaîne que vous pouvez toujours auditer

<img src="assets/diagrams/evidence-chain.svg" alt="Chaîne de preuve : réponse → affirmation → passage → séance → séminaire/document → témoin/source, et l'Evidence Inspector qui montre le segment cité, le contexte et la chaîne des sources." width="100%">

## Ce qu'il refuse de faire

Ces refus sont la conception, non des limites :

| Refus | Pourquoi |
|---|---|
| **Ne jamais répondre à partir des connaissances du modèle** | La synthèse ne peut utiliser que les preuves récupérées. Contrat insuffisant → `ABSTAINED`. |
| **Ne jamais réparer une source en silence** | `SOURCE_TRACE_INCOMPLETE` reste visible ; le masquer dénaturerait la source. |
| **N'inventer aucune donnée bibliographique** | Éditeur, année, ISBN, pages ne sont jamais devinés ; un style impossible dit pourquoi. |
| **Aucune promotion automatique en canonique** | Tout matériel importé ou produit par IA entre comme *candidat* et le reste jusqu'à validation humaine. |
| **Aucune sémantique non déclarée** | Les 39 composants savants sont figés par empreinte ; un changement non déclaré fait échouer le contrôle et le système **refuse de démarrer**. |

---

## Démarrage

**Vous êtes un agent IA ?** Exécutez d'abord ceci et suivez ce qui s'affiche — c'est ce qui décide
si la recherche peut fonctionner :

```sh
python3 tools/ensure_corpus.py --status      # code 0 = prêt · code 3 = prévenez l'utilisateur
python3 tools/ensure_corpus.py --json        # état lisible par machine
```

### 1 · Cloner le moteur

```sh
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS
python3 -m workspace_ui.server.cli --port 3090
# → http://127.0.0.1:3090/help    centre d'aide de 13 pages (utilisable sans aucun corpus)
```

### 2 · Fournir un corpus — trois voies

| Voie | Ce que vous obtenez | Comment |
|---|---|---|
| **A. Corpus de référence** (téléchargement public, usage savant) | le corpus complet des séminaires : 1 979 fichiers · 249 105 passages · index prêts à l'emploi | dépôt compagnon [`YanKaFei/Lacan-Knowledge-OS-corpus`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus) → `python3 tools/ensure_corpus.py --install --pack corpus-pack-v1.tar.gz --manifest corpus-pack-v1.manifest.json` |
| **B. Démonstration domaine public** | sources cliniques françaises du XIXᵉ siècle (Falret · Binet · Janet) — redistribuables | `python3 tools/build_demo_corpus.py .` |
| **C. Vos propres textes** | tout texte que vous avez le droit d'utiliser, ingéré par les outils du moteur | [`CORPUS.md`](CORPUS.md) · `python3 _scripts/inventory_corpus.py --help` |

**Voie A en détail.** Le dépôt compagnon fournit un **pack de corpus** : une archive à manifeste de
hachages que `tools/fetch-corpus.py` vérifie **fichier par fichier** avant installation — un
téléchargement partiel ou altéré ne peut pas passer.

```sh
curl -sLO https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/download/corpus-v1/corpus-pack-v1.tar.gz
curl -sLO https://raw.githubusercontent.com/YanKaFei/Lacan-Knowledge-OS-corpus/main/corpus-pack-v1.manifest.json
python3 tools/fetch-corpus.py --pack corpus-pack-v1.tar.gz \
    --manifest corpus-pack-v1.manifest.json --into .
python3 _scripts/_tools/core_freeze.py --verify      # → SCHOLARLY_CORE_READY
python3 -m workspace_ui.server.cli --port 3090       # la recherche répond désormais
```

L'accès à la voie A est accordé **personnellement** et **à des fins de recherche uniquement**
([`RIGHTS.md`](RIGHTS.md)). Sans accès, les voies B et C vous donnent un système fonctionnel
aujourd'hui même. Mécanique du pack (transmettre un corpus à un collègue sans le publier) :
[`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md).

### 3 · Vérifier le contrat (c'est le cœur du projet)

```sh
python3 _scripts/_tools/core_freeze.py --verify      # 39 composants savants
python3 _scripts/_tools/freeze_lineage.py --verify   # zéro dérive sémantique sur 7 segments
python3 _scripts/_tools/build_i18n.py --check        # copie UI ↔ dictionnaire ↔ appels
python3 _scripts/_tools/build_help.py --check        # liens, ancres, 0 fiction documentaire
bash _scripts/run_all_tests.sh                       # 146 suites · 78 validateurs
```

**Prérequis :** Python 3.9+ (bibliothèque standard pour le chemin du noyau) et un navigateur moderne.
**Aucun bundler, aucune étape de build** — `index.html` charge directement des modules ES. La recherche
vectorielle et un vrai LLM sont des extras optionnels ([`docs/EMBEDDING_PROVIDER.md`](docs/EMBEDDING_PROVIDER.md)).

---

## Comment l'utiliser

<img src="assets/diagrams/workflow.svg" alt="Une tâche de recherche : demander, vérifier la preuve, lire l'original, conserver le matériel, trier les sources, former votre savoir — l'abstention est un résultat de plein droit." width="100%">

1. **Demander** — une question par exécution.
2. **Lire l'état** — `VALIDATED`, `VALIDATED_WITH_QUALIFICATIONS`, `PARTIALLY_SUPPORTED`,
   `VALIDATION_FAILED`, `INSUFFICIENT_EVIDENCE`, `ABSTAINED`. À lire littéralement.
3. **Vérifier** — cliquez une puce de citation ; l'Evidence Inspector montre le segment cité, sa
   fenêtre de contexte et la chaîne de sources. *La réponse est la conclusion du noyau ; l'inspecteur,
   ce que le corpus dit réellement.*
4. **Approfondir** — ouvrez le même passage dans Explore.
5. **Conserver** — `Add to Project`, ou `Save to Obsidian`.

### L'interface

| Où | Quoi |
|---|---|
| **Accueil** | orienté tâches : *que voulez-vous faire ?* — six cartes de tâches, le parcours en six étapes, un démarrage en cinq minutes. Chaque entrée est un vrai lien. |
| **Research** | champ de question, mode / fournisseur / langue de recherche, et une provenance **mesurée** sur chaque réponse (fournisseur · modèle · temps réel · cache · tentatives) |
| **Explore** | passages, séances, séminaires, concepts, terminologie, personnes, cas — en lecture seule |
| **Evidence Inspector** | le panneau de droite : passage original, segment cité, réglages de contexte, chaîne des sources, traduction |
| **Centre d'aide** | `/help` — 13 rubriques, sommaire latéral, ancres, précédent/suivant, recherche par sujet, changement de langue instantané |
| **Langues** | langue de l'interface (EN/中文) et *langue de recherche* sont deux réglages indépendants |

Chaque nom de contrôle cité dans l'aide est rendu depuis l'interface réelle, et chaque affirmation
fonctionnelle est vérifiée par machine : **45/45 vérifiées · 0 fiction documentaire · 0 lien cassé**.

---

## L'utiliser depuis DSH / tout client MCP

Ce dépôt **est** une cible de plugin [DeepSeek Harness](https://github.com/deepseek-ai) : il fournit
un serveur MCP, une ligne portable, un bundle installable et un installeur idempotent.

```sh
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS
python3 tools/install-dsh-row.py --profile web     # lie le chemin du serveur à votre clone
python3 _scripts/_tools/lacan-kb-mcp               # ou lancez le serveur MCP seul
```

Les outils apparaissent sous `mcp__lacan-kb__search_passages`, `…get_passage`, `…get_context`,
`…resolve_entity`, `…list_concepts`, `…search_terminology`, `…compare_concepts`, `…find_relation`,
`…list_seminars`, `…get_sources` — **10 outils**, protocole `2025-11-25`. Prouvé avec le SDK MCP de
DSH lui-même (`_data/mcp/DSH_CLIENT_PROOF.json`, **14/14**).
Voir [`docs/DSH_PLUGIN.md`](docs/DSH_PLUGIN.md).

---

## Avantages et inconvénients

<table>
<tr><th width="50%">✅ Avantages</th><th width="50%">⚠️ Inconvénients / limites</th></tr>
<tr valign="top"><td>

**Vérifiabilité avant fluidité.** Chaque affirmation est liée à un identifiant de passage ; vous pouvez
auditer la chaîne à la main.

**Échec honnête.** Abstention, `INSUFFICIENT_EVIDENCE` et indisponibilité explicite sont des sorties de
première classe. Aucun remplissage halluciné.

**Un contrat exécutable.** Le gel à 39 composants et la lignée à sept segments sont vérifiés par du code,
non par une promesse.

**Offline-first.** `Offline / Mock` produit des réponses déterministes, sans identifiants ni réseau.

**Un contrat, plusieurs clients.** La même surface MCP sert l'interface web, DSH et tout éditeur doté
d'un client MCP.

**Historique auditable.** Chaque exécution est un instantané immuable ; relancer une question crée un
nouvel élément au lieu d'écraser l'ancien.

**Le corpus est séparable.** Moteur public (Apache-2.0), corpus tiers avec sa propre frontière ou le vôtre — les deux ne se mélangent jamais
dans un même dépôt, donc licencier l'un ne licencie pas l'autre.

</td><td>

**Il faut un corpus que vous avez le droit d'utiliser.** En l'état : interface, centre d'aide et contrats ;
il ne répond qu'une fois un corpus installé. Le pack de référence est téléchargeable publiquement mais reste un **matériel réservé à la recherche**.

**Le corpus de référence est du matériel de recherche, pas un actif produit.** Aucun usage commercial,
aucune redistribution — [`RIGHTS.md`](RIGHTS.md).

**Le périmètre est assumé.** Il répond *sur un corpus*. Les questions d'histoire éditoriale, de
participants ou de dates s'abstiennent : le corpus ne porte pas ces métadonnées.

**Aucun score de qualité.** Aucun « % de confiance » nulle part ; la qualité de l'interprétation reste
votre jugement.

**Lourd à l'échelle d'un ordinateur portable.** Le corpus de référence occupe ~2,5 Go avec les index dérivés.

**La recherche vectorielle est optionnelle.** Sans les extras d'embedding, la récupération retombe sur le
lexical (l'interface indique laquelle est active).

**La synthèse LLM réelle est un appel bloquant unique.** Les exécutions longues prennent 45–60 s ;
l'interface affiche le temps réel, et « stop waiting » n'annule pas la tâche serveur.

**Produit rapide, noyau gelé.** Les fonctionnalités de confort changent souvent ; modifier la
*sémantique* exige une Core Change Request formelle.

**Présuppose une familiarité avec le domaine.** Le système ne vous apprendra pas Lacan.

</td></tr>
</table>

---

## Carte de la documentation

| Document | Contenu |
|---|---|
| [`RIGHTS.md`](RIGHTS.md) | **droits et usages permis, en entier** — moteur vs corpus, ce que l'accès accorde et n'accorde pas |
| [`NOTICE`](NOTICE) | la même frontière, dans la forme dont un distributeur a besoin |
| [`AGENTS.md`](AGENTS.md) | les règles qu'un agent IA doit suivre ici — à commencer par le contrôle du corpus |
| [`corpus.json`](corpus.json) | référence de corpus lisible par machine : où il vit, comment l'installer, que faire s'il manque |
| [`CORPUS.md`](CORPUS.md) | apporter son propre corpus ; ce que les constructeurs attendent |
| [`docs/DEMO_CORPUS.md`](docs/DEMO_CORPUS.md) | le corpus de démonstration domaine public et l'étape ontologique restante |
| [`docs/CORPUS_PACK.md`](docs/CORPUS_PACK.md) | empaqueter et transmettre un corpus sans le publier |
| [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md) | comment ce dépôt public est dérivé et vérifié négativement |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) | le phasage et la surface MCP |
| [`docs/DAILY_USE_GUIDE.md`](docs/DAILY_USE_GUIDE.md) · [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | l'usage quotidien |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) · [`CHANGELOG.md`](CHANGELOG.md) | contribuer, discipline des identifiants, historique |

## État

- **Noyau savant :** gelé en v1 — `SCHOLARLY_CORE_READY`, 39 composants figés, dérive sémantique **0**.
- **Couche produit :** complète pour l'usage quotidien ; dernière campagne d'acceptation **20/20 éléments
  bloquants**, **146 suites de régression / 78 validateurs / 0 échec / 0 ignoré**.
- **Distribution :** moteur public (Apache-2.0) · corpus de référence public, **usage savant uniquement** ·
  corpus de démonstration domaine public en cours.
- **Feuille de route :** [`docs/ROADMAP.md`](docs/ROADMAP.md).

<div align="center">

Code : [Apache-2.0](LICENSE) · Textes sources : **non distribués, aucun usage commercial autorisé** ([`RIGHTS.md`](RIGHTS.md))

*Si ce système vous épargne une semaine de vérification de citations, il a fait son travail.*

</div>
