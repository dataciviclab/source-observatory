# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

## Il funnel

```
radar ── gate ── catalog-watch ── catalog-inventory ── pipeline (merge → validate)
              └── radar-only
```

1. **Radar** — probe leggero su tutte le fonti (health check, sempre)
2. **Gate** — decide il regime di osservazione (`catalog-watch` o `radar-only`)
3. **Catalog-inventory** — enumera gli item dei cataloghi ammessi
4. **Pipeline** — merge (dedup logico per dataset) + validate (reachability + sniff CSV) → `readiness_score` 0-10

Il funnel è alimentato dal `sources_registry.yaml`: ogni fonte ha un `source_id`, un `protocol` e un `observation_mode`.

## CI / Workflow

Due workflow schedulati su GitHub Actions:

| Workflow | Schedule | Cosa fa |
|---|---|---|
| `radar.yml` | **daily** 03:15 | Radar check su tutte le fonti + sync `datasets_in_use` da DI catalog |
| `observatory.yml` | **weekly** (lunedì) 03:20 | Inventory → pipeline (merge+validate) → report → upload GCS |

### `radar.yml` (daily)

Probe leggero HTTP su ogni fonte nel registry. Aggiorna `radar_summary.json`, `radar_history.json`, `STATUS.md` e `sources_registry.yaml`. Committa i risultati su git.

### `observatory.yml` (weekly, lunedì)

1. **Inventory** — build del parquet `catalog_inventory_latest.parquet` per le fonti `catalog-watch`
2. **Pipeline** — merge (raggruppa item in dataset logici) + validate (HEAD probe + sniff CSV schema) → `validated.parquet`
3. **Report** — genera report per fonte (`source_reports/*.json`) e dashboard (`sources_dashboard.json`)
4. **Upload GCS** — parquet, report e snapshot su `gs://dataciviclab-clean/catalog_inventory/`

I report vengono committati nel repo. I parquet operativi sono caricati su GCS.

## Script

| Script | Cosa fa |
|---|---|
| `scripts/radar_check.py` | Health check delle fonti nel registry |
| `scripts/sync_datasets_in_use.py` | Sincronizza `datasets_in_use` dal catalogo DI (`radar.yml`) |
| `scripts/build_catalog_inventory.py` | Snapshot tabulare di tutti gli item enumerabili |
| `scripts/pipeline/run_pipeline.py` | Merge + validate → `validated.parquet` |
| `scripts/build_source_reports.py` | Report per fonte + dashboard |
| `scripts/source_report.py` | Logica di aggregazione e scoring |
| `scripts/collectors/` | Adapter per protocollo: CKAN, SDMX, SPARQL, HTML |
| `scripts/collectors/_validate_base.py` | Validazione per gruppo tabulare (probe + sniff CSV) |
| `scripts/gha/` | Helper per CI (gcs upload, publish summary) |

```bash
# Radar (giornaliero)
so-radar-check

# Catalog inventory (settimanale)
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated --workers 4

# Pipeline merge + validate
so-run-pipeline --workers 4

# Build reports
so-build-reports
```

## Skills

Le skills in `skills/` sono guide operative per agenti e review umana.

| Skill | Cosa fa |
|---|---|
| `source-check.md` | Verifica una fonte specifica — porta a issue intake in DI |
| `inventory-triage.md` | Triage di un inventory per una shortlist — porta a issue SO per source-check |
| `portal-scout.md` | Identifica protocollo e decide se aggiungere al registry |

Il layer MCP (`so_mcp/so_server.py`) è il modo consigliato per consultare gli artifact senza scaricare file. Espone 5 tool: `so_source_report` (report completo per fonte), `so_dashboard` (KPI riassuntivi), `so_inventory_search`, `so_source_check`, `so_find_by_url`.

## Output e artefatti

Gli artifact strutturali (`radar_summary.json`, `radar_history.json`, `STATUS.md`) sono versionati nel repo e aggiornati dalla CI. I parquet in `generated/` sono cache operative, sovrascritti a ogni run.

```
data/radar/
  STATUS.md                   # sommario leggibile del probe
  radar_summary.json          # stato compatto per fonte (GREEN/YELLOW/RED)
  radar_history.json          # storia probe per fonte
  sources_registry.yaml       # registro input/output

data/reports/
  sources_dashboard.json      # KPI riassuntivi di tutte le fonti (report_version 2)
  source_reports/*.json       # report per singola fonte

data/pipeline/
  validated.parquet           # gruppi validati (merge + reachability + sniff)
  summary.json                # riepilogo run pipeline

data/catalog_inventory/generated/
  catalog_inventory_latest.parquet   # snapshot cumulativo item
  catalog_inventory_report.json      # stato run per fonte
```

I JSON strutturali (`radar_summary`, `radar_history`) sono consumati da **agent-context-builder** per il contesto operativo degli agenti.

Artifact su GCS (solo inventory e pipeline — il radar vive su git + Actions artifacts):
- `gs://dataciviclab-clean/catalog_inventory/` — parquet inventory + report
- `gs://dataciviclab-clean/catalog_inventory/pipeline/` — validated parquet

## Struttura

```
scripts/          codice runtime (radar, inventory, pipeline, report)
scripts/collectors/  adapter per protocollo (CKAN, SDMX, SPARQL, HTML)
scripts/pipeline/    merge + validate
data/             artifact versionati (radar, catalog, inventory)
skills/           guide operative per agenti
so_mcp/           layer MCP read-only sugli artifact
docs/             runbook, architettura, policy
```

## Documentazione

- [runbook.md](docs/runbook.md) — guida operativa per radar, inventory, pipeline
- [architecture.md](docs/architecture.md) — architettura del sistema
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)

## Installazione

```bash
pip install -e ".[dev]"
```

Il pacchetto espone 5 entry point CLI:

```
so-observatory-mcp     # server MCP
so-run-pipeline        # merge + validate
so-build-reports       # report per fonte
so-radar-check         # health check
so-sync-datasets       # sync datasets_in_use
```
