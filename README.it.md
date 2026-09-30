<div align="center">

# Lacan Knowledge OS

**Un ambiente di ricerca fondato sul corpus per la psicoanalisi lacaniana.**
Prima la prova. Poi l'interpretazione. Mai l'invenzione.

[English](README.md) · [中文](README.zh.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [**Italiano**](README.it.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-6b4c2f?style=flat-square)](LICENSE)
[![Core](https://img.shields.io/badge/nucleo%20scientifico-congelato%20%C2%B7%2039%20componenti-43403b?style=flat-square)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/regressione-146%20suite%20%C2%B7%200%20fallimenti-3f6b4a?style=flat-square)](docs/SCHOLARLY_REGRESSION_SPEC_V1.md)
[![MCP](https://img.shields.io/badge/MCP-10%20strumenti%20%C2%B7%202025--11--25-6b4c2f?style=flat-square)](docs/MCP_TOOL_CONTRACTS.md)
[![Built with](https://img.shields.io/badge/costruito%20con-DeepSeek%20Harness-4d6bfe?style=flat-square)](https://github.com/deepseek-ai)

</div>

---

> **L'unica regola su cui il sistema è costruito**
>
> *Ogni asserzione deve atterrare su un numero di passaggio.*
>
> Se il corpus non può sostenere una domanda, il sistema **si astiene** — non risponde
> con la conoscenza del modello. **L'astensione è un risultato, non un errore.**

---

## Indice

| | |
|---|---|
| [1. Che cos'è](#1-che-cosè) | [6. Architettura](#6-architettura) |
| [2. Per chi](#2-per-chi) | [7. Usarlo da DSH / qualsiasi client MCP](#7-usarlo-da-dsh--qualsiasi-client-mcp) |
| [3. Ciò che rifiuta di fare](#3-ciò-che-rifiuta-di-fare) | [8. Porta il tuo corpus](#8-porta-il-tuo-corpus-importante) |
| [4. Avvio rapido](#4-avvio-rapido) | [9. Vantaggi e svantaggi](#9-vantaggi-e-svantaggi) |
| [5. Come si usa](#5-come-si-usa) | [10. Stato, roadmap, contribuire](#10-stato-roadmap-contribuire) |

---

## 1. Che cos'è

**Lacan Knowledge OS** è uno strumento di ricerca locale, offline-first, per leggere Lacan
seriamente. Trasforma un corpus di seminari e scritti in un **archivio di prove citabile** e
colloca un **nucleo scientifico congelato** fra la tua domanda e qualunque risposta.

Sei capacità, un solo sistema:

| | Capacità | Che cosa offre |
|---|---|---|
| 🔎 | **Research** | Poni una domanda → il nucleo recupera passaggi, costruisce un contratto di prova e **solo allora** sintetizza una risposta in cui ogni affermazione supera la validazione di citazione e implicazione |
| 📖 | **Explore** | Leggere il corpus direttamente: passaggi, sedute, seminari, concetti, terminologia — senza alcun modello |
| 🔬 | **Evidence Inspector** | `Risposta → affermazione → passaggio → seduta → seminario → testimone/fonte`, con il **segmento esatto citato** e la sua finestra di contesto |
| 🗂️ | **Projects** | Trasformare esecuzioni ripetute in un tema di lungo periodo (domande, ipotesi, passaggi, persone, casi, bibliografia) |
| 📚 | **Bibliografia e citazioni** | Stato di revisione, completezza dei metadati, disponibilità per stile **e la ragione dell'indisponibilità** |
| ✍️ | **Ponte Obsidian** | Prove e validazione restano qui; la tua comprensione, le note e la scrittura vivono nel tuo vault |

## 2. Per chi

- **Ricercatori e dottorandi** che devono citare Lacan con precisione e mostrare *da dove*
  viene una lettura.
- **Gruppi di lettura e seminari** che vogliono una base di prove condivisa e ispezionabile.
- **Sviluppatori di strumenti** che cercano un esempio compiuto di architettura a *nucleo
  congelato*: uno strato semantico che non può derivare mentre il prodotto evolve attorno.
- **Ingegneri IA** interessati alla generazione ancorata con un contratto di astensione
  esplicito, invece di un punteggio di confidenza.

## 3. Ciò che rifiuta di fare

Questi rifiuti sono il progetto, non dei limiti:

| Rifiuto | Perché |
|---|---|
| **Nessuna risposta dalla conoscenza del modello** | La sintesi può usare solo le prove recuperate. Contratto insufficiente → `ABSTAINED`. |
| **Nessuna riparazione silenziosa delle fonti** | `SOURCE_TRACE_INCOMPLETE` resta visibile; nasconderlo falserebbe la fonte. |
| **Nessun dato bibliografico inventato** | Editore, anno, ISBN, pagine non vengono mai indovinati; uno stile impossibile ne dice il motivo. |
| **Nessuna promozione automatica a canonico** | Il materiale importato o prodotto da IA entra come *candidato* e resta tale finché un umano non lo promuove. |
| **Nessuna semantica non dichiarata** | I 39 componenti scientifici sono fissati da hash; una modifica non dichiarata fa fallire il controllo e il sistema **rifiuta di avviarsi**. |

## 4. Avvio rapido

> **Questa edizione pubblica fornisce il motore, non il corpus.** Vedi
> [§8](#8-porta-il-tuo-corpus-importante) e [`CORPUS.md`](CORPUS.md).

```bash
git clone https://github.com/YanKaFei/Lacan-Knowledge-OS.git
cd Lacan-Knowledge-OS

# 1) L'interfaccia si avvia senza alcun corpus — Help Center e UI sono pienamente usabili:
python3 -m workspace_ui.server.cli --port 3090
#    → http://127.0.0.1:3090/help        Help Center (13 pagine)
#    → http://127.0.0.1:3090/research    superficie di ricerca (serve un corpus per rispondere)

# 2) Controlli di integrità (è il contratto, non decorazione):
python3 _scripts/_tools/core_freeze.py --verify      # 39 componenti scientifici
python3 _scripts/_tools/freeze_lineage.py --verify   # cambi semantici fra le fasi
python3 _scripts/_tools/build_i18n.py --check        # testi UI ↔ dizionario ↔ punti di chiamata
python3 _scripts/_tools/build_help.py --check        # link, ancore, 0 finzione

# 3) Regressione completa (le suite dipendenti richiedono un corpus; vedi CORPUS.md)
bash _scripts/run_all_tests.sh
```

**Requisiti:** Python 3.9+ (solo libreria standard per il percorso del nucleo), un browser
moderno e — solo per la ricerca vettoriale o un LLM reale — gli extra opzionali in
[`docs/EMBEDDING_PROVIDER.md`](docs/EMBEDDING_PROVIDER.md). Nessun bundler, nessuna fase di
build: `index.html` carica direttamente moduli ES.

## 5. Come si usa

### 5.1 Home page orientata ai compiti

All'apertura il sistema mostra **che cosa puoi fare**, non le sue viscere:

```
Hero      →  [Inizia una ricerca]   [Prima volta qui?]
Compiti   →  Porre una domanda lacaniana · Trovare testo e fonti
             Studiare un concetto · Studiare persone e casi
             Costruire un progetto lungo · Gestire fonti e citazioni
Percorso  →  ① Chiedere → ② Verificare la prova → ③ Leggere l'originale
             → ④ Conservare il materiale → ⑤ Ordinare le fonti → ⑥ Formare il tuo sapere
5 minuti  →  sei passi fino alla prima ricerca conclusa
```

Ogni ingresso è un **link reale** (`/research`, `/explore`, `/projects`, `/bibliography`,
`/persons`, `/cases`, `/zotero`, `/help/...`) — condivisibile, salvabile, apribile in una
nuova scheda.

### 5.2 Un compito di ricerca completo

1. **Chiedere** — una domanda per esecuzione.
2. **Leggere lo stato** — `VALIDATED`, `VALIDATED_WITH_QUALIFICATIONS`, `PARTIALLY_SUPPORTED`,
   `VALIDATION_FAILED`, `INSUFFICIENT_EVIDENCE`, `ABSTAINED`. Leggilo alla lettera.
3. **Verificare** — clicca un chip di citazione: l'Evidence Inspector mostra il segmento
   citato, la finestra di contesto e la catena delle fonti. *La risposta è la conclusione del
   nucleo; l'inspector è ciò che il corpus dice davvero.*
4. **Approfondire** — apri lo stesso passaggio in Explore.
5. **Conservare** — `Add to Project`, oppure `Save to Obsidian`.

### 5.3 Help Center

`/help` è un centro di 13 pagine con barra laterale, ancore, precedente/successivo e ricerca
per argomento: *primi passi, research, prova, explore, research vs explore, progetti, persone
e casi, bibliografia, zotero, obsidian, lingue, stati, risoluzione problemi*.

**Ogni nome di controllo nell'Help è reso dall'interfaccia reale** e ogni affermazione
funzionale è verificata a macchina
(`HELP_CLAIM_VERIFICATION.json`: **42/42 verificate, 0 finzione, 0 in sospeso**).

### 5.4 Lingua dell'interfaccia vs lingua di ricerca

| Impostazione | Ambito | Esempio |
|---|---|---|
| **Language** (`English` / `中文`) | solo l'interfaccia del prodotto | cambio istantaneo, senza ricarica |
| **Research language** (`any` / `zh` / `fr` / `en`) | la *lingua della domanda* inviata con la richiesta | non traduce l'interfaccia, non filtra la ricerca |

`Interfaccia = 中文` + `Research language = Français` è del tutto valido. Il testo originale di
Lacan, i passaggi citati e i metadati bibliografici **non** vengono mai tradotti.

## 6. Architettura

```
        la tua domanda
              │
   ┌──────────▼───────────┐
   │  STRATO PRODOTTO     │   workspace_ui/ · browse_api/ · project_api/
   │  (evolve liberamente)│   export_system/ · bibliography/ · obsidian_adapter/
   └──────────┬───────────┘
              │  scholarly_api v1  (confine di prodotto — 3 componenti fissati)
   ┌──────────▼───────────┐
   │  NUCLEO CONGELATO    │   39 componenti fissati da hash
   │  (non può derivare)  │   recupero · contratto di prova · sufficienza ·
   └──────────┬───────────┘   confine di sintesi · citazione · implicazione · astensione
              │
   ┌──────────▼───────────┐
   │  CORPUS              │   archivio passaggi · testimoni · ontologia · indici
   │  (il tuo)            │   NON incluso in questo repository
   └──────────────────────┘
```

- **Gli agenti parlano MCP, non Python.** `mcp_server/` espone **10 strumenti** su stdio
  (protocollo `2025-11-25`); l'interfaccia web è solo un client di quello stesso contratto.
- **Il congelamento è eseguibile.** `core_freeze.py --verify` ricalcola 39 hash;
  `freeze_lineage.py --verify` prova **zero** cambi semantici su sette fasi.
- **I derivati sono rigenerabili.** Indici SQLite/FTS/vettoriali e l'archivio di 249 105
  passaggi si ricostruiscono da fonti canoniche + manifest. Il vault è la fonte di verità.

Approfondisci: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) ·
[`docs/HELP_SYSTEM_ARCHITECTURE.md`](docs/HELP_SYSTEM_ARCHITECTURE.md).

## 7. Usarlo da DSH / qualsiasi client MCP

Questo repository **è** un target di plugin [DeepSeek Harness](https://github.com/deepseek-ai):
fornisce un server MCP, una riga portabile e un bundle DSH installabile.

```bash
# A. Come plugin DSH (installa la riga MCP al posto tuo)
dsh plugin --profile web add github:YanKaFei/Lacan-Knowledge-OS

# B. Oppure incolla la riga tu stesso — integrations/lacan-kb-mcp.row.yml
#    (gli strumenti appaiono come mcp__lacan-kb__search_passages, …)

# C. Oppure avvia il server da solo
python3 _scripts/_tools/lacan-kb-mcp
```

Dimostrato con l'SDK MCP di DSH stesso (`_data/mcp/DSH_CLIENT_PROOF.json`, **14/14**):
handshake stdio, 10 strumenti con schema, denominazione `mcp__lacan-kb__<tool>`, ritorni di
prove strutturate, riverifica indipendente degli id di passaggio restituiti e un errore di
protocollo — non un crash — per strumenti sconosciuti.
Vedi [`docs/MCP_DSH_INTEGRATION.md`](docs/MCP_DSH_INTEGRATION.md).

## 8. Porta il tuo corpus (**importante**)

Questo repository non contiene deliberatamente **alcun testo sorgente**:

| Non incluso | Perché |
|---|---|
| Testo integrale di seminari/scritti (fr + zh) | Diritto d'autore dei titolari |
| Archivio passaggi (`passages.jsonl`, 249 105 record, ~384 MB) | Testo del corpus |
| Testimoni e realizzazioni (~152 MB) | Testo del corpus |
| Indici vettoriali/lessicali | Grandi, ricostruibili dal tuo corpus |

Ciò che **è** incluso: gli schemi, il contratto di congelamento, i builder, i validatori e i
test — tutto ciò che serve per inserire **testo che hai il diritto di usare** (tue scansioni,
edizioni licenziate, pubblico dominio, tue traduzioni).

```bash
python3 _scripts/build.py --help               # inventario del corpus e punti di build
python3 _scripts/inventory_corpus.py --help    # inventario canonico + hash
```

L'edizione pubblica è prodotta e verificata da
[`_scripts/_tools/build_public_edition.py`](_scripts/_tools/build_public_edition.py):
copia per lista bianca, poi verifica **negativa** (sonde N-gramma del corpus, scansione di
segreti, scansione di percorsi assoluti, soglie di dimensione).
Vedi [`docs/PUBLIC_EDITION.md`](docs/PUBLIC_EDITION.md).

## 9. Vantaggi e svantaggi

<table>
<tr><th width="50%">✅ Vantaggi</th><th width="50%">⚠️ Svantaggi / limiti</th></tr>
<tr valign="top"><td>

**Verificabilità prima della fluidità.** Ogni affermazione è legata a un id di passaggio;
puoi controllare la catena a mano.

**Fallimento onesto.** Astensione, `INSUFFICIENT_EVIDENCE` e indisponibilità esplicita sono
output di prima classe. Nessun riempitivo allucinato.

**Un contratto eseguibile.** Il congelamento a 39 componenti e la discendenza a sette segmenti
sono verificati dal codice, non da una promessa in un documento.

**Offline-first.** `Offline / Mock` produce risposte deterministiche senza credenziali né rete.

**Un contratto, molti client.** La stessa superficie MCP serve UI web, DSH e ogni editor con
client MCP.

**Storia verificabile.** Ogni esecuzione è un'istantanea immutabile; rifare una domanda crea un
nuovo elemento invece di sovrascrivere il vecchio.

**Bilingue per costruzione.** I testi UI sono guidati da dizionario (0 chiavi mancanti); il
testo sorgente non è mai tradotto, per scelta.

</td><td>

**Serve un corpus che hai il diritto di usare.** Di base mostra interfaccia, Help Center e
contratti — ma non può rispondere finché non fornisci il testo.

**L'ambito è dichiarato.** Risponde *su un corpus*. Domande su storia editoriale, partecipanti
o date si asterranno: il corpus non porta quei metadati.

**Nessun punteggio di qualità.** Nessuna "confidenza %" da nessuna parte; la qualità
dell'interpretazione resta il tuo giudizio.

**Pesante per un uso da laptop.** Il corpus di riferimento occupa ~2,5 GB con indici ed embedding.

**La ricerca vettoriale è opzionale e parziale.** Senza gli extra di embedding il recupero
ricade sul lessicale (l'interfaccia dice quale è attivo).

**La sintesi LLM reale è una singola chiamata bloccante.** Le esecuzioni lunghe richiedono
45–60 s; l'interfaccia mostra il tempo reale e "stop waiting" non annulla il job sul server.

**Prodotto rapido, nucleo congelato.** Le funzioni di comodo cambiano spesso; modificare la
*semantica* richiede una Core Change Request formale.

**Presuppone familiarità con il campo.** Non ti insegnerà Lacan.

</td></tr>
</table>

## 10. Stato, roadmap, contribuire

- **Stato:** nucleo scientifico congelato alla v1 (`SCHOLARLY_CORE_READY`); strato prodotto
  completo per l'uso quotidiano (ricerca, explore, prove, progetti, bibliografia, import
  Zotero, ponte Obsidian, export, Help Center).
- **Numeri dell'ultima accettazione:** **20/20 elementi bloccanti**, **146 suite di
  regressione / 78 validatori / 0 fallimenti / 0 saltati**, congelamento del nucleo **PASS**,
  deriva semantica **0**.
- **Roadmap:** [`docs/ROADMAP.md`](docs/ROADMAP.md).
- **Contribuire:** [`CONTRIBUTING.md`](CONTRIBUTING.md) — l'unica regola non negoziabile:
  *non modificare la semantica scientifica senza una Core Change Request*.
- **Sicurezza:** [`SECURITY.md`](SECURITY.md) — le credenziali non passano mai dall'API di prodotto.

<div align="center">

**Licenza** — codice: [Apache-2.0](LICENSE) · testi sorgente: **non distribuiti** ([NOTICE](NOTICE))

*Se questo sistema ti risparmia una settimana di controllo citazioni, ha fatto il suo lavoro.*

</div>
