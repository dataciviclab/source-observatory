# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

Risponde a una domanda sola: **questa fonte vale il tempo del Lab?**

## Il funnel

```
gate ── catalog-watch ── catalog-inventory ── source-check
     └── radar-only
```

1. **Gate** — decide il regime di osservazione (`catalog-watch` o `radar-only`)
2. **Catalog-inventory** — enumera gli item dei cataloghi ammessi
3. **Source-check** — valuta qualità e granularità dei dataset

Il funnel è alimentato dal `sources_registry.yaml`: ogni fonte ha un `source_id`, un `protocol` e un `observation_mode`. Le fonti nuove vengono aggiunte al registry manualmente.

## La CI

L'unica Action schedulata è `observatory.yml`. Gira ogni giorno alle 03:15 e in un solo job fa:

1. **Radar** — probe leggero di tutte le fonti nel registry (sempre)
2. **Inventory** — build dell'inventory parquet dei cataloghi enumerabili (solo lunedì o manual dispatch)
3. **Source-check** — scoring item-level sul parquet inventory (sempre, incrementale)

I risultati vengono committati nel repo, caricati su GCS e pubblicati come artifact Actions.

## Script

| Script | Cosa fa |
|---|---|
| `scripts/radar_check.py` | Health check delle fonti nel registry |
| `scripts/build_catalog_inventory.py` | Snapshot tabulare di tutti gli item enumerabili |
| `scripts/build_catalog_signals.py` | Segnali drift/inventory del catalogo |
| `scripts/bulk_source_check.py` | Scoring item-level (qualità, granularità, rilevanza) |
| `scripts/catalog_diff.py` | Diff tra due report inventory per segnalare regressioni |
| `scripts/collectors/` | Adapter per protocollo: CKAN, SDMX, SPARQL, HTML |

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
| `source-check.md` | Valuta se una fonte regge come pista del Lab |
| `catalog-inventory-scout.md` | Triage di un inventory per una shortlist |
| `portal-scout.md` | Identifica protocollo e decide se aggiungere al registry |

Il layer MCP (`mcp/so_server_core.py`) è il modo consigliato per consultare gli artifact senza scaricare file.

## Output e artefatti

Gli artifact strutturali (`radar_summary.json`, `radar_history.json`, `catalog_signals.json`, `STATUS.md`) sono versionati nel repo e aggiornati dalla CI. I parquet in `generated/` sono cache operative.

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

I tre JSON (`radar_summary`, `catalog_signals`, `radar_history`) sono consumati da **agent-context-builder** per il contesto operativo degli agenti.

L'artifact parquet su GCS: `gs://dataciviclab-clean/catalog_inventory/`

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