<div align="center">

# Lacan Knowledge OS

**Eine korpusgestützte Forschungsumgebung für die lacanianische Psychoanalyse.**
Zuerst die Evidenz. Dann die Deutung. Nie die Erfindung.

[English](README.md) · [中文](README.zh.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [**Deutsch**](README.de.md) · [Italiano](README.it.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-6b4c2f?style=flat-square)](LICENSE)
[![Core](https://img.shields.io/badge/wissenschaftlicher%20Kern-eingefroren%20%C2%B7%2039%20Komponenten-43403b?style=flat-square)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/Regression-146%20Suiten%20%C2%B7%200%20Fehler-3f6b4a?style=flat-square)](docs/SCHOLARLY_REGRESSION_SPEC_V1.md)
[![MCP](https://img.shields.io/badge/MCP-10%20Werkzeuge%20%C2%B7%202025--11--25-6b4c2f?style=flat-square)](docs/MCP_TOOL_CONTRACTS.md)
[![Corpus](https://img.shields.io/badge/Korpus-Begleit--Repository%20%C2%B7%20nur%20Forschung-8a6d1f?style=flat-square)](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)
[![Built with](https://img.shields.io/badge/gebaut%20mit-DeepSeek%20Harness-4d6bfe?style=flat-square)](https://github.com/deepseek-ai)

</div>

---

> **Die eine Regel, um die dieses System gebaut ist**
>
> *Jede Aussage muss auf einer Passagennummer landen.*
>
> Kann das Korpus eine Frage nicht stützen, **enthält sich** das System der Antwort —
> es antwortet nicht aus Modellwissen. **Enthaltung ist ein Ergebnis, kein Fehler.**

---

## Inhalt

| | |
|---|---|
| [1. Was es ist](#1-was-es-ist) | [6. Architektur](#6-architektur) |
| [2. Für wen](#2-für-wen) | [7. Nutzung aus DSH / jedem MCP-Client](#7-nutzung-aus-dsh--jedem-mcp-client) |
| [3. Was es verweigert](#3-was-es-verweigert) | [8. Eigenes Korpus mitbringen](#8-eigenes-korpus-mitbringen-wichtig) |
| [4. Schnellstart](#4-schnellstart) | [9. Vorteile und Nachteile](#9-vorteile-und-nachteile) |
| [5. Bedienung](#5-bedienung) | [10. Status, Roadmap, Mitwirken](#10-status-roadmap-mitwirken) |

---

> ## ⚠️ Rechte und Nutzungsumfang — vor der Installation des Korpus lesen
>
> **Die Engine ist Open Source. Der Korpus ist es nicht.** Zwei Dinge, zwei Regelwerke:
>
> | | Lizenz / Status |
> |---|---|
> | **Engine-Quellcode** (dieses Repository) | Apache-2.0 — nutzen, ändern, weitergeben, in kommerzielle Produkte einbetten |
> | **Referenzkorpus** ([Begleit-Repository](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus)) | **urheberrechtlich geschützte Texte Dritter.** Öffentlich abrufbar, **nur für Forschung und Studium**; öffentliche Sichtbarkeit ist keine Lizenz — **keine** kommerzielle Lizenz, **keine** Weitergabe- oder Bereitstellungs-Lizenz. |
> | **Gemeinfreier Demo-Korpus** ([`corpus-demo-v1`](https://github.com/YanKaFei/Lacan-Knowledge-OS-corpus/releases/tag/corpus-demo-v1) · [`demo-corpus/`](demo-corpus)) | gemeinfrei (Falret 1890 · Binet 1892 · Janet 1909) — frei weitergebbar |
>
> **Klartext.** Der Korpus enthält französische **Arbeitstranskriptionen** der Seminare Lacans, eine
> **Textextraktion der Seuil-Druckausgabe** (S1–S5) und ein **chinesisches Übersetzungsprojekt einer
> Community**. **Keines dieser Rechte liegt bei diesem Projekt.** Es wird offen veröffentlicht, damit Forschende es erhalten können, und
> an Personen, die das Material für ihre eigene Forschung brauchen — und **Zugang ist keine Lizenz**:
> er erlaubt weder kommerzielle Nutzung noch Weitergabe, Spiegelung, Neuveröffentlichung, Bereitstellung
> für Dritte oder das Training eines veröffentlichten Modells.
>
> **Ob Ihre Nutzung zulässig ist, entscheiden Sie** — dieses Projekt kann das nicht für Sie beantworten
> und gibt keine Rechtsberatung. Vollständige Analyse: [`RIGHTS.md`](RIGHTS.md).

## 1. Was es ist

**Lacan Knowledge OS** ist ein lokales, offline-first Forschungsinstrument, um Lacan ernsthaft
zu lesen. Es verwandelt einen Bestand aus Seminar- und Écrits-Texten in einen **zitierfähigen
Evidenzspeicher** und setzt einen **eingefrorenen wissenschaftlichen Kern** zwischen Ihre Frage
und jede Antwort.

Sechs Fähigkeiten, ein System:

| | Fähigkeit | Was sie liefert |
|---|---|---|
| 🔎 | **Research** | Frage stellen → der Kern ruft Passagen ab, baut einen Evidenzvertrag und **erst dann** eine Antwort, deren jede Aussage Zitat- und Implikationsprüfung besteht |
| 📖 | **Explore** | Das Korpus direkt lesen: Passagen, Sitzungen, Seminare, Begriffe, Terminologie — ohne Modell |
| 🔬 | **Evidence Inspector** | `Antwort → Aussage → Passage → Sitzung → Seminar → Zeuge/Quelle`, mit der **exakt zitierten Stelle** und ihrem Kontextfenster |
| 🗂️ | **Projects** | Wiederholte Läufe zu einem Langzeitthema machen (Fragen, Hypothesen, Passagen, Personen, Fälle, Bibliographie) |
| 📚 | **Bibliographie & Zitate** | Prüfstatus, Metadaten-Vollständigkeit, Verfügbarkeit je Stil **und den Grund der Nichtverfügbarkeit** |
| ✍️ | **Obsidian-Brücke** | Evidenz und Validierung bleiben hier; Ihr Verständnis, Ihre Notizen und Ihr Schreiben leben in Ihrem Vault |

## 2. Für wen

- **Forschende und Doktorand:innen**, die Lacan präzise zitieren und zeigen müssen, *woher*
  eine Lesart stammt.
- **Lese Gruppen und Seminare**, die eine gemeinsame, prüfbare Evidenzbasis wollen.
- **Werkzeugentwickler**, die ein ausgearbeitetes Beispiel einer *eingefrorenen Kern*-Architektur
  suchen: eine semantische Schicht, die nicht driften kann, während das Produkt um sie wächst.
- **KI-Ingenieur:innen**, die geerdete Generierung mit explizitem Enthaltungsvertrag statt
  Konfidenzwert interessiert.

## 3. Was es verweigert

Diese Verweigerungen sind das Design, nicht Grenzen:

| Verweigerung | Grund |
|---|---|
| **Keine Antwort aus Modellwissen** | Die Synthese darf nur abgerufene Evidenz verwenden. Unzureichender Vertrag → `ABSTAINED`. |
| **Keine stille Quellenreparatur** | `SOURCE_TRACE_INCOMPLETE` bleibt sichtbar; Verbergen würde die Quelle verfälschen. |
| **Keine erfundenen bibliographischen Daten** | Verlag, Jahr, ISBN, Seitenzahlen werden nie geraten; ein unmöglicher Stil nennt den Grund. |
| **Keine automatische Kanonisierung** | Importiertes oder KI-erzeugtes Material kommt als *Kandidat* und bleibt es, bis ein Mensch es befördert. |
| **Keine undeklarierte Semantik** | Die 39 wissenschaftlichen Komponenten sind hash-fixiert; eine undeklarierte Änderung lässt die Prüfung scheitern — das System **startet nicht**. |

## 4. Schnellstart

> **Diese öffentliche Edition liefert die Engine, nicht das Korpus.** Siehe
> [§8](#8-eigenes-korpus-mitbringen-wichtig) und [`CORPUS.md`](CORPUS.md).

```bash
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS

# 1) Die Oberfläche startet ganz ohne Korpus — Help Center und UI sind voll nutzbar:
python3 -m workspace_ui.server.cli --port 3090
#    → http://127.0.0.1:3090/help        Help Center (13 Seiten)
#    → http://127.0.0.1:3090/research    Recherche-Oberfläche (Korpus für Antworten nötig)

# 2) Integritätsprüfungen (das ist der Vertrag, keine Dekoration):
python3 _scripts/_tools/core_freeze.py --verify      # 39 wissenschaftliche Komponenten
python3 _scripts/_tools/freeze_lineage.py --verify   # semantische Änderungen über Phasen
python3 _scripts/_tools/build_i18n.py --check        # UI-Texte ↔ Wörterbuch ↔ Aufrufstellen
python3 _scripts/_tools/build_help.py --check        # Help-Links, Anker, 0 Fiktion

# 3) Volle Regression (korpusabhängige Suiten brauchen ein Korpus; siehe CORPUS.md)
bash _scripts/run_all_tests.sh
```

**Voraussetzungen:** Python 3.9+ (Standardbibliothek für den Kernpfad), ein moderner Browser
und — nur für Vektorsuche oder ein echtes LLM — die optionalen Extras aus
[`docs/EMBEDDING_PROVIDER.md`](docs/EMBEDDING_PROVIDER.md). Kein Bundler, kein Build-Schritt:
`index.html` lädt ES-Module direkt.

## 5. Bedienung

### 5.1 Aufgabenorientierte Startseite

Beim Öffnen zeigt das System, **was Sie tun können**, nicht seine Innereien:

```
Hero      →  [Recherche starten]   [Zum ersten Mal hier?]
Aufgaben  →  Eine lacanianische Frage stellen · Text und Quellen finden
             Einen Begriff untersuchen · Personen und Fälle untersuchen
             Ein Langzeitprojekt aufbauen · Quellen und Zitate verwalten
Ablauf    →  ① Fragen → ② Evidenz prüfen → ③ Original lesen
             → ④ Material sichern → ⑤ Quellen ordnen → ⑥ Eigenes Wissen bilden
5 Minuten →  sechs Schritte bis zum ersten abgeschlossenen Lauf
```

Jeder Einstieg ist ein **echter Link** (`/research`, `/explore`, `/projects`,
`/bibliography`, `/persons`, `/cases`, `/zotero`, `/help/...`) — teilbar, speicherbar,
in neuem Tab zu öffnen.

### 5.2 Ein vollständiger Rechercheauftrag

1. **Fragen** — eine Frage pro Lauf.
2. **Status lesen** — `VALIDATED`, `VALIDATED_WITH_QUALIFICATIONS`, `PARTIALLY_SUPPORTED`,
   `VALIDATION_FAILED`, `INSUFFICIENT_EVIDENCE`, `ABSTAINED`. Wörtlich lesen.
3. **Prüfen** — Zitations-Chip anklicken: der Evidence Inspector zeigt die zitierte Stelle,
   ihr Kontextfenster und die Quellenkette. *Die Antwort ist die Schlussfolgerung des Kerns;
   der Inspector zeigt, was das Korpus tatsächlich sagt.*
4. **Vertiefen** — dieselbe Passage in Explore öffnen.
5. **Sichern** — `Add to Project` oder `Save to Obsidian`.

### 5.3 Help Center

`/help` ist ein Center mit 13 Seiten, Seitenleiste, Ankern, Vor/Zurück und Themensuche:
*Erste Schritte, Research, Evidenz, Explore, Research vs Explore, Projekte, Personen und Fälle,
Bibliographie, Zotero, Obsidian, Sprachen, Status, Fehlersuche*.

**Jeder Steuerelement-Name im Help wird aus der echten Oberfläche gerendert**, und jede
funktionale Behauptung ist maschinell geprüft
(`HELP_CLAIM_VERIFICATION.json`: **45/45 verifiziert, 0 Fiktion, 0 offen**).

### 5.4 Oberflächensprache vs. Recherchesprache

| Einstellung | Reichweite | Beispiel |
|---|---|---|
| **Language** (`English` / `中文`) | nur die Produktoberfläche | sofortiger Wechsel, kein Neuladen |
| **Research language** (`any` / `zh` / `fr` / `en`) | die *Fragesprache* der Rechercheanfrage | übersetzt die UI nicht, filtert die Suche nicht |

`Oberfläche = 中文` + `Research language = Français` ist völlig gültig. Lacans Originaltext,
zitierte Passagen und bibliographische Metadaten werden **nie** übersetzt.

## 6. Architektur

```
        Ihre Frage
              │
   ┌──────────▼───────────┐
   │  PRODUKTSCHICHT      │   workspace_ui/ · browse_api/ · project_api/
   │  (frei veränderbar)  │   export_system/ · bibliography/ · obsidian_adapter/
   └──────────┬───────────┘
              │  scholarly_api v1  (Produktgrenze — 3 fixierte Komponenten)
   ┌──────────▼───────────┐
   │  EINGEFRORENER KERN  │   39 hash-fixierte Komponenten
   │  (kann nicht driften)│   Abruf · Evidenzvertrag · Suffizienz ·
   └──────────┬───────────┘   Synthesegrenze · Zitat · Implikation · Enthaltung
              │
   ┌──────────▼───────────┐
   │  KORPUS              │   Passagenspeicher · Zeugen · Ontologie · Indizes
   │  (Ihr eigenes)       │   NICHT in diesem Repository
   └──────────────────────┘
```

- **Agenten sprechen MCP, nicht Python.** `mcp_server/` bietet **10 Werkzeuge** über stdio
  (Protokoll `2025-11-25`); die Weboberfläche ist nur ein Client dieses Vertrags.
- **Der Frost ist ausführbar.** `core_freeze.py --verify` berechnet 39 Hashes neu;
  `freeze_lineage.py --verify` beweist **null** semantische Änderung über sieben Phasen.
- **Ableitungen sind regenerierbar.** SQLite/FTS/Vektor-Indizes und der Speicher mit 249 105
  Passagen sind aus kanonischen Quellen + Manifesten rekonstruierbar. Der Vault ist die Wahrheit.

Mehr: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) ·
[`docs/HELP_SYSTEM_ARCHITECTURE.md`](docs/HELP_SYSTEM_ARCHITECTURE.md).

## 7. Nutzung aus DSH / jedem MCP-Client

Dieses Repository **ist** ein [DeepSeek Harness](https://github.com/deepseek-ai)-Plugin-Ziel:
es liefert einen MCP-Server, eine portable Zeile und ein installierbares DSH-Bundle.

```bash
# A. Als DSH-Plugin (schreibt die MCP-Zeile für Sie)
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS

# B. Oder die Zeile selbst einfügen — integrations/lacan-kb-mcp.row.yml
#    (Werkzeuge erscheinen dann als mcp__lacan-kb__search_passages, …)

# C. Oder den Server allein starten
python3 _scripts/_tools/lacan-kb-mcp
```

Bewiesen mit DSHs eigenem MCP-SDK (`_data/mcp/DSH_CLIENT_PROOF.json`, **14/14**):
stdio-Handshake, 10 Werkzeuge mit Schemata, `mcp__lacan-kb__<tool>`-Benennung, strukturierte
Evidenzrückgaben, unabhängige Nachprüfung zurückgegebener Passagen-IDs und ein Protokollfehler
— kein Absturz — bei unbekannten Werkzeugen.
Siehe [`docs/MCP_DSH_INTEGRATION.md`](docs/MCP_DSH_INTEGRATION.md).

## 8. Eigenes Korpus mitbringen (**wichtig**)

Dieses Repository enthält bewusst **keinen Quelltext**:

| Nicht enthalten | Grund |
|---|---|
| Volltext der Seminare/Écrits (fr + zh) | Urheberrecht der Rechteinhaber |
| Passagenspeicher (`passages.jsonl`, 249 105 Einträge, ~384 MB) | Korpustext |
| Zeugen und Realisierungen (~152 MB) | Korpustext |
| Vektor-/lexikalische Indizes | Groß, aus Ihrem Korpus rekonstruierbar |

**Enthalten** sind: Schemata, der Frost-Vertrag, die Builder, die Validatoren und die Tests —
also alles, um **Text einzuspielen, den Sie nutzen dürfen** (eigene Scans, lizenzierte
Ausgaben, gemeinfreies Material, Ihre eigenen Übersetzungen).

```bash
python3 _scripts/build.py --help               # Korpusinventar und Build-Einstiege
python3 _scripts/inventory_corpus.py --help    # kanonisches Inventar + Hashes
```

Die öffentliche Edition wird von
[`_scripts/_tools/build_public_edition.py`](_scripts/_tools/build_public_edition.py) erzeugt
und **negativ** verifiziert (Korpus-N-Gramm-Sonden, Secret-Scan, Absolutpfad-Scan,
Größenschwellen). Siehe [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md).

## 9. Vorteile und Nachteile

<table>
<tr><th width="50%">✅ Vorteile</th><th width="50%">⚠️ Nachteile / Grenzen</th></tr>
<tr valign="top"><td>

**Prüfbarkeit vor Flüssigkeit.** Jede Aussage hängt an einer Passagen-ID; Sie können die Kette
per Hand auditieren.

**Ehrliches Scheitern.** Enthaltung, `INSUFFICIENT_EVIDENCE` und explizite Nichtverfügbarkeit
sind vollwertige Ausgaben. Keine halluzinierte Füllung.

**Ein ausführbarer Vertrag.** Der 39-Komponenten-Frost und die Sieben-Segment-Lineage werden
von Code geprüft, nicht von einem Versprechen im Dokument.

**Offline-first.** `Offline / Mock` liefert deterministische Antworten ohne Zugangsdaten und Netz.

**Ein Vertrag, viele Clients.** Dieselbe MCP-Oberfläche dient Web-UI, DSH und jedem Editor
mit MCP-Client.

**Auditierbare Historie.** Jeder Lauf ist ein unveränderlicher Schnappschuss; erneutes Fragen
erzeugt einen neuen Eintrag statt den alten zu überschreiben.

**Zweisprachig von Konstruktion.** UI-Texte sind wörterbuchgetrieben (0 fehlende Schlüssel);
Quelltext wird bewusst nie übersetzt.

</td><td>

**Sie brauchen ein Korpus, das Sie nutzen dürfen.** Out of the box zeigt es Oberfläche,
Help Center und Verträge — Antworten gibt es erst mit eigenem Text.

**Der Umfang ist meinungsstark.** Es antwortet *über ein Korpus*. Fragen zu Verlagsgeschichte,
Teilnehmenden oder Daten enthalten sich — das Korpus trägt diese Metadaten nicht.

**Kein Qualitätswert.** Nirgends ein „Konfidenz-%“; die Qualität der Deutung bleibt Ihr Urteil.

**Schwer für Laptop-Maßstab.** Das Referenzkorpus belegt mit Indizes und Embeddings ~2,5 GB.

**Vektorsuche ist optional und partiell.** Ohne Embedding-Extras fällt der Abruf auf lexikalisch
zurück (die UI nennt die aktive Variante).

**Echte LLM-Synthese ist ein blockierender Aufruf.** Lange Läufe dauern 45–60 s; die UI zeigt
die echte Zeit, und „Warten beenden“ bricht den Serverlauf nicht ab.

**Schnelles Produkt, eingefrorener Kern.** Komfortfunktionen ändern sich oft; *Semantik* zu
ändern erfordert einen formellen Core Change Request.

**Setzt Vertrautheit mit dem Feld voraus.** Es bringt Ihnen Lacan nicht bei.

</td></tr>
</table>

## 10. Status, Roadmap, Mitwirken

- **Status:** wissenschaftlicher Kern auf v1 eingefroren (`SCHOLARLY_CORE_READY`); Produktschicht
  vollständig für den Alltag (Recherche, Explore, Evidenz, Projekte, Bibliographie,
  Zotero-Import, Obsidian-Brücke, Export, Help Center).
- **Zahlen der letzten Abnahme:** **20/20 blockierende Punkte**, **146 Regressions-Suiten /
  78 Validatoren / 0 Fehler / 0 übersprungen**, Kernfrost **PASS**, semantische Drift **0**.
- **Roadmap:** [`docs/ROADMAP.md`](docs/ROADMAP.md).
- **Mitwirken:** [`CONTRIBUTING.md`](CONTRIBUTING.md) — die eine nicht verhandelbare Regel:
  *keine Änderung wissenschaftlicher Semantik ohne Core Change Request*.
- **Sicherheit:** [`SECURITY.md`](SECURITY.md) — Zugangsdaten laufen nie über die Produkt-API.

<div align="center">

**Lizenz** — Code: [Apache-2.0](LICENSE) · Quelltexte: **nicht verteilt** ([NOTICE](NOTICE))

*Wenn dieses System Ihnen eine Woche Zitatprüfung erspart, hat es seinen Zweck erfüllt.*

</div>
