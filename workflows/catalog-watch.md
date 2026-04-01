---
name: catalog-watch
description: Workflow del Source Observatory per osservare fonti in modalità catalog-watch e produrre un report locale di intelligence senza aprire issue o avviare pipeline. Usare quando serve capire se un catalogo ha esposto segnali nuovi o strutturalmente rilevanti.
license: TBD public repo license
metadata:
  version: "1.2"
  owner: "DataCivicLab"
  tags: [source-observatory, catalog-watch, monitoring, scouting]
---

# Workflow: catalog-watch

Workflow per l'osservazione periodica delle fonti in modalità `catalog-watch` nel Source Observatory.
Versione: 1.2 - 2026-03-30

---

## Obiettivo di fase

Controllare le fonti classificate come `catalog-watch` in `sources_registry.yaml` e produrre
un report strutturato di intelligence. Non apre issue, non esegue source-check, non avvia
pipeline. Risponde a: "questo catalogo ha esposto qualcosa di nuovo o strutturalmente rilevante?"

## Definition of done

Il workflow è completo quando:

- tutte le fonti `catalog-watch` nel registry sono state controllate con tool reali
- il report `CATALOG_WATCH_REPORT.md` è stato aggiornato
- `last_probed` è stato aggiornato nel registry, ma non la baseline
- ogni segnale ha un'azione suggerita chiara
- non sono state aperte issue, source-check o pipeline in automatico

---

## Input

File canonico: `source-observatory/data/radar/sources_registry.yaml`

Leggere il file e filtrare le fonti con `observation_mode: catalog-watch`.
Se presente, leggere anche `catalog_baseline`.

## Perimetro corretto

`catalog-watch` è un layer sopra il dataset-level.

Serve a osservare:

- inventario del catalogo
- drift strutturale
- segnali che meritano follow-up

Non serve a:

- fare source-check automatici
- aprire issue
- monitorare in modo diffuso il singolo dataset o file

## Protocolli core

Trattare come protocolli core, in questo ordine:

1. `ckan`
2. `sdmx`
3. `rest_json` quando il catalogo è davvero inventory-like
4. `xlsx_direct` o `html` solo se inevitabili e con aspettativa di maggior rumore

Se il protocollo è fragile e il segnale non è chiaramente rilevante, preferire `[DATO MANCANTE]`
o `nessuna conclusione` a una lettura forzata.

---

## Tool disponibili per protocollo

| Protocollo | Tool |
|---|---|
| `sdmx` | `mcp__istat-sdmx__istat_list_dataflows` |
| `ckan` | `mcp__fetch__fetch_json` su `/api/3/action/package_list` e `package_search` |
| `rest_json` | `mcp__fetch__fetch_json` sull'endpoint base |
| `xlsx_direct` | `mcp__fetch__fetch_readable` o `mcp__fetch__fetch_html` sulla pagina catalogo |

Per CKAN: il `base_url` nel registry punta già all'endpoint di probe corretto.
Usare quello come punto di partenza, non costruire URL da zero.

---

## Workflow

### Step 1 - Leggi il registry

Leggere `sources_registry.yaml`. Per ogni fonte con `observation_mode: catalog-watch`:
- estrarre `protocol`, `base_url`, `last_probed`, `note`, `datasets_in_use`, `catalog_baseline`

### Step 2 - Controlla ciascuna fonte

Per ogni fonte, eseguire il check appropriato al protocollo:

**SDMX**
- Chiamare `istat_list_dataflows`
- Contare i dataflow totali
- Verificare se i dataflow correlati a `datasets_in_use` sono ancora presenti
- Se esiste `catalog_baseline.metric = dataflow_count`, confrontare il conteggio con `catalog_baseline.value`
- Se il conteggio è cambiato, segnalarlo esplicitamente nel report

**CKAN**
- Chiamare `fetch_json` su `{base_url}`
- Chiamare `fetch_json` su `/api/3/action/package_search?rows=0` per il conteggio totale
- Se esiste `catalog_baseline.metric = package_count`, confrontare il totale con `catalog_baseline.value`
- Se ci sono `datasets_in_use`, verificare che i package noti siano ancora presenti

**REST JSON**
- Chiamare `fetch_json` sull'endpoint base
- Verificare disponibilità e struttura di massima
- Segnalare cambi di schema o endpoint irraggiungibili

**XLSX direct / HTML**
- Chiamare `fetch_readable` o `fetch_html` sulla pagina catalogo
- Verificare raggiungibilità
- Segnalare se la struttura dei link di download è cambiata
- Se `catalog_baseline.metric = qualitative_signal`, confrontare il segnale attuale con la baseline testuale disponibile

### Step 3 - Produci il report

Scrivere il report in:
`source-observatory/data/catalog/CATALOG_WATCH_REPORT.md`

Usare questa tassonomia dei segnali:

- `no signal`
  - nessuna novità affidabile
- `health`
  - il problema osservato è soprattutto di raggiungibilità o affidabilità della fonte
- `inventory change`
  - cambia il conteggio o l'inventario del catalogo
- `structural drift`
  - cambia la struttura, il pattern di naming o il layout del catalogo
- `follow-up candidate`
  - emerge un segnale che giustifica un follow-up umano, di solito `source-check`
- `[DATO MANCANTE]`
  - non c'è abbastanza evidenza per classificare il segnale in modo affidabile

### Step 4 - Aggiorna il registry

Per ogni fonte controllata, aggiornare il campo `last_probed` in `sources_registry.yaml`
con la data corrente.

Non modificare `catalog_baseline` senza istruzione esplicita.
La baseline va aggiornata solo quando Gabri decide che il nuovo stato osservato diventa il nuovo riferimento.

---

## STOP POINT

Fermarsi qui. Il report è pronto per revisione di Gabri.

- Non aprire issue
- Non eseguire source-check autonomamente
- Non modificare candidate o dataset

Se un segnale sembra urgente, segnalarlo
chiaramente nel report con `[ATTENZIONE]` e aspettare istruzioni.

---

## Vincoli

- Solo dati reali dai tool. Non stimare conteggi o inventare stati.
- Se un endpoint non risponde, segnalarlo come `errore` nel report, non come `nessuna novità`.
- Scrivere `[DATO MANCANTE]` se non riesci a ottenere un confronto affidabile.
- Non trasformare delta numerici grezzi in decisioni automatiche: il follow-up umano resta separato.
- Niente emoji, niente em dash.

---

## Riferimenti

- Registry: `source-observatory/data/radar/sources_registry.yaml`
- Output: `source-observatory/data/catalog/CATALOG_WATCH_REPORT.md`
- Architettura: `source-observatory/docs/architecture.md`
- Runbook: `source-observatory/docs/runbook.md`
