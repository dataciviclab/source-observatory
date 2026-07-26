# Source Observatory — Guida Architettura

## Struttura scripts/

```
scripts/
  collectors/          # package: logica di inventory e validazione per protocollo
    base.py            # utility condivise: CollectorResult, strip_query
    ckan.py            # collector + validatore CKAN
    sdmx.py            # collector + validatore SDMX
    sparql.py          # collector + validatore SPARQL
    html.py            # collector HTML (scraping pagine con link a dati)
    _validate_base.py  # validazione comune: HEAD probe + sniff CSV + readiness_score
  pipeline/
    run_pipeline.py    # orchestrazione: merge → validate in sequenza
    _merge_utils.py    # merge/dedup: normalizzazione titoli, dataset_group, slug
  build_catalog_inventory.py   # entry point: enumera fonti → parquet
  build_source_reports.py      # entry point: produce report per fonte + dashboard
  source_report.py             # logica di aggregazione e scoring
  radar_check.py               # health check HTTP su tutte le fonti (radar)
  sync_datasets_in_use.py      # sincronizza datasets_in_use dal catalogo DI
  _constants.py                # costanti condivise tra script
  gha/                         # helper per CI (gcs upload, publish summary)
```

## Funnel attuale

```
Radar (daily)
  │ HEAD probe su ogni fonte
  │ → radar_summary.json, radar_history.json
  ▼
Gate (embedded in radar)
  │ radar GREEN? → catalog-watch o radar-only
  ▼
Catalog inventory (weekly)
  │ Enumera item per protocollo (CKAN, SDMX, SPARQL, HTML)
  │ → catalog_inventory_latest.parquet
  ▼
Pipeline: merge + validate (weekly)
  │ 1. MERGE: raggruppa item in dataset logici (normalizzazione titoli)
  │ 2. VALIDATE: per ogni gruppo, scegli URL migliore → HEAD probe → sniff CSV
  │    → readiness_score 0-10
  │ → validated.parquet, summary.json
  ▼
Report (weekly)
  │ Aggrega per fonte: reachable, readiness medio, formati, CSV con schema
  │ → source_reports/*.json, sources_dashboard.json
```

## Regola fondamentale: usa `HttpClient` per chiamate HTTP

Tutti gli script che fanno chiamate HTTP **devono** usare `HttpClient` da `lab_connectors.http`,
non `requests.get()` diretto. Motivo: SSL fallback automatico, retry, backoff, User-Agent coerente.

## Validatori per protocollo

Ogni protocollo ha un validatore specializzato, cablato in `scripts/collectors/__init__.py`:

| Protocollo | Validatore | Logica |
|---|---|---|
| CKAN | `ckan.validate_items` | HEAD probe + sniff CSV |
| HTML | `ckan.validate_items` | HEAD probe + sniff CSV (stessa logica) |
| SDMX | `sdmx.validate_items` | Nessun probe HTTP — validazione su metadati (api_base_url, distribution_url, dimensioni) |
| SPARQL | `sparql.validate_items` | COUNT query su endpoint named graph |

I protocolli non ancora cablati usano `validate_tabular_group` come fallback.

## readiness_score 0-10

Il readiness_score sostituisce il vecchio intake_score 0-100. È calcolato in `_validate_base.py:235-253`:

```
reachable (2) + formato_aperto (2) + colonne >= 3 (2) / > 0 (1)
+ status 200 (1) + delimiter (1) + encoding utf-8 (1) + anni noti (1)
= 0-10

Penalità: sniff fallito su falso CSV (-3), content-type non CSV (-1)
```

## Directory

| Directory | Cosa contiene | Versionato |
|---|---|---|
| `scripts/` | Codice runtime (pipeline, report, radar) | ✅ |
| `so_mcp/` | Layer MCP read-only (package installabile) | ✅ |
| `data/radar/` | Radar summary, history, registry | ✅ |
| `data/reports/` | Report per fonte + dashboard | ✅ |
| `data/pipeline/` | validated.parquet, summary.json | ❌ (cache operativa) |
| `data/catalog_inventory/generated/` | inventory parquet + report | ❌ (cache operativa) |
| `tests/` | Test | ✅ |
| `skills/` | Guide operative per agenti | ✅ |
| `docs/` | Documentazione | ✅ |

### GCS artifact paths

```
gs://dataciviclab-clean/catalog_inventory/
  catalog_inventory_latest.parquet
  catalog_inventory_report.json
  pipeline/validated.parquet
```

## Dipendenze

- **lab-connectors**: HttpClient, DuckDB + GCS connect, MCP utilities, SPARQL executor
- **toolkit**: scout.http (probe, link extractor), scout.infer (granularità e anni), profile.preview (preview URL)
