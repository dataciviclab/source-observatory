# Source Observatory — Osservatorio delle fonti pubbliche

**Monitoriamo le fonti pubbliche italiane: quali sono vive, quali cambiano, quali meritano di diventare dataset del Lab.**

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema
[DataCivicLab](https://github.com/dataciviclab).

## Il funnel

```
radar ── gate ── catalog-watch ── catalog-inventory ── pipeline (merge → validate)
              └── radar-only
```

1. **Radar** — health check leggero su tutte le fonti (sempre attivo)
2. **Gate** — decide il regime di osservazione (`catalog-watch` o `radar-only`)
3. **Catalog-inventory** — enumera gli item dei cataloghi ammessi
4. **Pipeline** — merge + validate → `readiness_score` 0-10

Il funnel è alimentato dal `sources_registry.yaml`: ogni fonte ha `source_id`,
`protocol` e `observation_mode`.

## CI / Workflow

| Workflow | Schedule | Cosa fa |
|---|---|---|
| `radar.yml` | **daily** 03:15 | Radar check su tutte le fonti + sync `datasets_in_use` |
| `observatory.yml` | **weekly** (lunedì) 03:20 | Inventory → pipeline → report → upload GCS |

I report vengono committati nel repo. I parquet operativi sono caricati su GCS
(`gs://dataciviclab-clean/catalog_inventory/`).

## Script principali

| Script | Cosa fa |
|---|---|
| `radar_check.py` | Health check delle fonti nel registry |
| `build_catalog_inventory.py` | Snapshot tabulare degli item enumerabili |
| `pipeline/run_pipeline.py` | Merge + validate → `validated.parquet` |
| `build_source_reports.py` | Report per fonte + dashboard |
| `collectors/` | Adapter per protocollo: CKAN, SDMX, SPARQL, HTML |

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

## Consultare i dati (MCP)

Il layer MCP (`so_mcp/so_server.py`) è il modo consigliato per consultare gli
artifact senza scaricare file. Espone 5 tool:

`so_source_report` (report completo per fonte) · `so_dashboard` (KPI riassuntivi) ·
`so_inventory_search` · `so_source_check` · `so_find_by_url`

## Skills

Le skills in `skills/` sono guide operative per agenti e review umana:

| Skill | Cosa fa |
|---|---|
| `source-check.md` | Verifica una fonte specifica → issue intake in dataset-incubator |
| `inventory-triage.md` | Triage di un inventory → issue SO per source-check |
| `portal-scout.md` | Identifica protocollo e decide se aggiungere al registry |

## Output e artefatti

Gli artifact strutturali (`radar_summary.json`, `radar_history.json`, `STATUS.md`)
sono versionati nel repo e aggiornati dalla CI. I parquet in `generated/` sono
cache operative, sovrascritti a ogni run.

```
data/radar/           STATUS.md, radar_summary.json, radar_history.json, sources_registry.yaml
data/reports/         sources_dashboard.json, source_reports/*.json
data/pipeline/        validated.parquet, summary.json
data/catalog_inventory/generated/   catalog_inventory_latest.parquet, report
```

I JSON strutturali sono consumati da **agent-context-builder** per il contesto
operativo degli agenti.

## Documentazione

- [runbook.md](docs/runbook.md) — guida operativa per radar, inventory, pipeline
- [architecture.md](docs/architecture.md) — architettura del sistema
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)

## Installazione

```bash
pip install -e ".[dev]"
```

Il pacchetto espone 5 entry point CLI:
`so-observatory-mcp` · `so-run-pipeline` · `so-build-reports` · `so-radar-check` · `so-sync-datasets`

Parte del [DataCivicLab](https://github.com/dataciviclab).
