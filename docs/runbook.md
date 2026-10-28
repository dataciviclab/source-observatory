# Runbook

Guida operativa breve per la v0 attuale.

## Radar

```bash
python scripts/radar_check.py --dry-run
python scripts/radar_check.py
```

Usa `radar` quando la domanda è:

- la fonte risponde?
- ci sono problemi di timeout, SSL, DNS o HTTP?
- il registry è sano?

Output:

- [STATUS.md](../data/radar/STATUS.md)

Scheduling:

- `radar.yml`: run **daily** 03:15 — health check, aggiorna `STATUS.md`, `radar_summary.json`, `radar_history.json`, `sources_registry.yaml`
- `observatory.yml`: run **weekly** (lunedì) 03:20 — inventory, catalog signals, source-check, upload GCS
- `workflow_dispatch` disponibile per entrambi i workflow per run manuali

Comportamento probe:

- non-SDMX portals con timeout/connection error (http_code="-", status YELLOW): retry automatico 1x. Se il retry è GREEN, lo usa; altrimenti annota "Retry timeout/connection: ..." e mantiene YELLOW.
- exception isolation: un portal che esplode non ferma il loop — ritorna ProbeResult(RED) e il probe continua con le fonti successive.

Manutenzione del Registry:

- Se una fonte è stabilmente giù, verificare manualmente l'URL.
- Se l'URL è cambiato, aggiornare `data/radar/sources_registry.yaml`.
- Se la fonte è definitivamente rimossa, valutare la disattivazione o rimozione nel registry.

Boundary:

- Se il problema è di contenuto (non infrastrutturale) -> [source-check.md](../skills/source-check.md)
- Se il catalogo è cambiato ma la fonte è viva -> [inventory-triage.md](../skills/inventory-triage.md)

## Catalog-watch

Output correnti:

- [sources_dashboard.json](../data/reports/sources_dashboard.json) (KPI riassuntivi)
- [catalog_signals.json](../data/catalog/catalog_signals.json)

Usa `catalog-watch` quando la domanda è:

- l'inventario è cambiato?
- c'è drift strutturale?
- c'è un follow-up candidate che merita revisione umana?

Modello v0:

- i segnali vengono prodotti automaticamente dal workflow schedulato `observatory.yml` (ogni lunedì 03:20)
- il follow-up resta `human-run`: il report non sostituisce la review umana sui cambi rilevanti
- il run manuale va usato quando serve un check metodologicamente difendibile fuori schedule
- gli output canonici sono `catalog_signals.json` e i source report in `data/reports/`
- problemi di connessione/HTTP vanno letti in `radar_summary.json`, non in `catalog_signals.json`
- **Issue automatiche**: in caso di variazioni rilevanti nel catalogo, `observatory.yml` crea o aggiorna una issue `catalog-alert` su GitHub

### Catalog per-repo e `pattern_probes`

Ogni repo dati che dichiara `[tool.observatory]` nel proprio `pyproject.toml`
genera il catalog in-repo (`registry/catalog.json`) con `so-catalog` — engine
condiviso, zero secrets (vedi `catalog-reusable.yml`).

Per le fonti **senza catalogo enumerabile ma con URL deterministici** si
dichiarano sentinelle in `pattern_probes`: se una passa da non disponibile ad
available, il verdict riceve il trigger `new_content_available`.

```toml
[tool.observatory]
source_id = "mef_finanze"
protocol = "html"
base_url = "https://www1.finanze.gov.it/finanze/analisi_stat/"

[[tool.observatory.pattern_probes]]
name = "iva-regionale-2026"
url = "https://www1.finanze.gov.it/finanze/analisi_stat/public/index.php?tree=2026CIVATOT0201&export=3"
min_bytes = 200
```

- `min_bytes` (opzionale): sotto quella soglia una risposta 2xx **non** conta
  come disponibile. Serve per le fonti che rispondono 200 con corpo vuoto
  quando il dato non esiste ancora (es. MEF `analisi_stat`): senza soglia il
  trigger "nuovo contenuto" scatterebbe a ogni run, per sempre.

**Drift degli URL consumati**: per gli upstream di tipo `url` (connector
`http_file`) l'inventario della fonte **non è autorevole** — può descrivere un
altro endpoint dello stesso dato (AGID: `catalogocloud.agid.gov.it` vs
`indicepa.gov.it`) o una sola distribuzione per item (Consip: un resource per
package, mentre il repo consuma più anni). Quando l'inventario non conferma,
`so-catalog` verifica l'URL consumato via HTTP: 2xx → `matched`, risposta di
errore → `missing` (drift reale), errore di rete → `unknown` (nessun falso
drift). **401/403/407/429 sono `unknown`, non drift**: un blocco WAF o un rate
limit non prova che la risorsa sia stata rimossa. I ref **templati**
(`{year}`) non si verificano via HTTP: l'URL concreto lo genera la pipeline,
quindi resta l'esito dell'inventario. Con inventario vuoto (fonti radar-only)
il check funziona **solo** grazie a questa verifica. L'UA usato è quello di
`[tool.observatory]`, per le fonti dietro WAF.

**Regola della prova di assenza** (vale per ogni `kind`): il drift dichiara
`missing` **solo** se ha una prova positiva che l'item esatto non c'è più.
La prova richiesta è dichiarata in `drift.ABSENCE_EVIDENCE`:

| `kind` | Prova | Perché |
|---|---|---|
| `dataflow` | `inventory` | una riga per dataflow nel catalogo SDMX |
| `ckan_dataset` | `inventory` | una riga per package (il nome è l'identità) |
| `ckan_resource` | `probe` | l'inventario tiene **una** distribuzione per item, ma un package ne ha decine → verifica con `resource_show` sulla fonte |
| `url` | `probe` | l'inventario può descrivere un altro endpoint |
| `script_type` | `inventory` | ID logico: match per token sull'area della fonte |

Un `kind` non dichiarato non può dichiarare `missing`: al massimo `unknown`.
Il gate è `tests/test_catalog_drift.py::TestAbsenceEvidence`.

**Query-string negli artifact**: l'URL che va al probe è quello intero, query
inclusa (è l'identità della risorsa per molte fonti), quindi la query finisce
nei parquet tracciati — `data/pipeline/validated.parquet` in questo repo e
`out/so/validated.parquet` nei repo dati. Oggi i parametri osservati sono
`format`, `d`, `t`: nessuna credenziale. **Prima di onboardare una fonte con
URL firmati/tokenizzati** (`?token=`, `?sig=`, `?api_key=`, …) va aggiunta la
redazione dei parametri sensibili (#436), altrimenti il valore viene persistito
in chiaro nel parquet committato.

## Catalog inventory

```bash
python scripts/build_catalog_inventory.py
python scripts/build_catalog_inventory.py --workers 3  # parallelo, sperimentale
```

Usa `catalog inventory` quando la domanda è:

- quali item sono oggi enumerabili nei cataloghi osservati?
- quali fonti `catalog-watch` producono un inventario riusabile per scouting?
- il perimetro pubblico resta coerente con le esclusioni dichiarate?

Output (non versionati nel repo):

- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- `data/catalog_inventory/generated/catalog_inventory_report.json`

Per ottenere l'ultimo output senza rieseguire: artifact del workflow `observatory` su GitHub Actions, oppure GCS se configurato.

Disciplina:

- il perimetro segue le fonti `catalog-watch` del registry
- una fonte può restare osservata in SO ma non essere inventariabile
- `anac` oggi resta escluso dall'inventory automatico per vincoli WAF
- l'upload su GCS richiede WIF org-level (GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_SERVICE_ACCOUNT) e il prefix hardcoded nella workflow (CATALOG_INVENTORY_GCS_PREFIX)
- in assenza di GCS il workflow resta valido: usa baseline locale vuota e salta i passaggi opzionali di storage/diff
- il workflow gira ogni lunedì (schedule) ed è disponibile anche via `workflow_dispatch`
- `--skip-red-sources` usato in CI per evitare tentativi su fonti già RED (timeout, WAF)
- `sync_datasets_in_use.py` viene eseguito nel workflow `radar.yml` per allineare il catalogo DI

## Ordine consigliato

1. esegui `radar`
2. leggi `catalog-watch`
3. decidi se esiste davvero un follow-up umano giustificato

## Disciplina

- tieni l'universo piccolo
- preferisci segnali leggibili alla copertura larga
