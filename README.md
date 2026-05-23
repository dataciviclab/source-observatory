# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

Risponde a una domanda sola: **questa fonte vale il tempo del Lab?**

## Il funnel

```
radar ── gate ── catalog-watch ── catalog-inventory ── source-check
             └── radar-only
```

1. **Radar** — probe leggero su tutte le fonti (health check, sempre)
2. **Gate** — decide il regime di osservazione (`catalog-watch` o `radar-only`)
3. **Catalog-inventory** — enumera gli item dei cataloghi ammessi
4. **Source-check** — valuta qualità e granularità dei dataset

Il funnel è alimentato dal `sources_registry.yaml`: ogni fonte ha un `source_id`, un `protocol` e un `observation_mode`. Le fonti nuove vengono aggiunte al registry manualmente.

## CI / Workflow

Due workflow schedulati su GitHub Actions:

| Workflow | Schedule | Cosa fa |
|---|---|---|
| `radar.yml` | **daily** 03:15 | Radar check su tutte le fonti + sync `datasets_in_use` da DI catalog |
| `observatory.yml` | **weekly** (lunedì) 03:20 | Inventory → catalog signals → source-check → upload GCS |

### `radar.yml` (daily)

Probe leggero HTTP su ogni fonte nel registry. Aggiorna `radar_summary.json`, `radar_history.json`, `STATUS.md` e `sources_registry.yaml`. Committa i risultati su git.

### `observatory.yml` (weekly, lunedì)

1. **Inventory** — build del parquet `catalog_inventory_latest.parquet` per le fonti `catalog-watch`
2. **Catalog signals** — calcola segnali di drift/inventory, produce `catalog_signals.json` e `CATALOG_WATCH_REPORT.md`
3. **Source-check** — scoring item-level sul parquet inventory (merge con risultati precedenti da GCS)
4. **Upload GCS** — parquet, report e snapshot su `gs://dataciviclab-clean/catalog_inventory/`
5. **Issue alert** — crea/aggiorna automaticamente issue `catalog-alert` in caso di variazioni rilevanti

I risultati vengono committati nel repo (signals), caricati su GCS e pubblicati come artifact Actions.

## Script

| Script | Cosa fa |
|---|---|
| `scripts/radar_check.py` | Health check delle fonti nel registry |
| `scripts/sync_datasets_in_use.py` | Sincronizza `datasets_in_use` dal catalogo DI (`radar.yml`) |
| `scripts/build_catalog_inventory.py` | Snapshot tabulare di tutti gli item enumerabili |
| `scripts/build_catalog_signals.py` | Segnali drift/inventory del catalogo |
| `scripts/bulk_source_check.py` | Scoring item-level (qualità, granularità, rilevanza) |
| `scripts/source_check_analyze.py` | Logica di scoring e analisi (usata da `bulk_source_check.py`) |
| `scripts/source_check_fetch.py` | Fetch HTTP e enrichment per source-check |
| `scripts/catalog_diff.py` | Diff tra due report inventory per segnalare regressioni |
| `scripts/collectors/` | Adapter per protocollo: CKAN, SDMX, SPARQL, HTML |
| `scripts/gha/` | Helper per CI (issue body, publish summary) |

```bash
# Radar (giornaliero)
python scripts/radar_check.py

# Catalog inventory (settimanale — lunedì o manuale)
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated --workers 4

# Source-check (giornaliero, incrementale — skippa item già checkati)
python scripts/bulk_source_check.py --skip-red-sources --max-items 200 --workers 8
```

## Skills

Le skills in `skills/` sono guide operative per agenti e review umana.

| Skill | Cosa fa |
|---|---|
| `source-check.md` | Verifica una fonte specifica — porta a issue intake in DI |
| `inventory-triage.md` | Triage di un inventory per una shortlist — porta a issue SO per source-check |
| `portal-scout.md` | Identifica protocollo e decide se aggiungere al registry |

Il layer MCP (`mcp/so_server_core.py`) è il modo consigliato per consultare gli artifact senza scaricare file.

## Output e artefatti

Gli artifact strutturali (`radar_summary.json`, `radar_history.json`, `catalog_signals.json`, `STATUS.md`) sono versionati nel repo e aggiornati dalla CI. I parquet in `generated/` sono cache operative, sovrascritti a ogni run.

```
data/radar/
  STATUS.md                   # sommario leggibile del probe
  radar_summary.json          # stato compatto per fonte (GREEN/YELLOW/RED)
  radar_history.json          # storia probe per fonte
  sources_registry.yaml       # registro input/output

data/catalog/
  catalog_signals.json        # segnali drift/inventory per fonte
  CATALOG_WATCH_REPORT.md     # report settimanale (lunedì)

data/catalog_inventory/generated/
  catalog_inventory_latest.parquet   # snapshot cumulativo item
  catalog_inventory_report.json      # stato run per fonte
  source_check_results.parquet       # scoring item-level
```

I JSON strutturali (`radar_summary`, `radar_history`, `catalog_signals`) sono consumati da **agent-context-builder** per il contesto operativo degli agenti.

Artifact su GCS (solo inventory e source-check — il radar vive su git + Actions artifacts):
- `gs://dataciviclab-clean/catalog_inventory/` — parquet inventory + report
- `gs://dataciviclab-clean/catalog_inventory/source-check/` — source-check results e snapshots

## Struttura

```
scripts/          codice runtime (radar, inventory, source-check, diff)
scripts/collectors/  adapter per protocollo (CKAN, SDMX, SPARQL, HTML)
data/             artifact versionati (radar, catalog, inventory)
skills/           guide operative per agenti
mcp/              layer MCP read-only sugli artifact
docs/             runbook, architettura, policy
```

## Documentazione

- [runbook.md](docs/runbook.md) — guida operativa per radar, inventory, source-check
- [architecture.md](docs/architecture.md) — architettura del sistema
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)