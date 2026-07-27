# Source Observatory MCP

Layer MCP read-only sugli artifact prodotti da Source Observatory.

Il server espone agli agenti una vista interrogabile degli artifact generati da CI o run locali.
Non scrive nello workspace.

Gli artifact di catalog-inventory sono cache locali sotto `data/catalog_inventory/generated/`.
Il nuovo `validated.parquet` (output della pipeline merge+validate) e' in `data/pipeline/`.
Le risposte sui parquet includono un blocco `cache` con scadenza configurabile.

## Workflow sorgente

| Workflow | Schedule | Prodotto principale | Dove finisce |
|---|---|---|---|
| `radar.yml` | **daily** 03:15 | `radar_summary.json`, `radar_history.json`, `sources_registry.yaml`, `STATUS.md` | commit su git |
| `observatory.yml` | **weekly** lun 03:20 | inventory parquet, validated parquet (pipeline), source reports (33 JSON) | upload GCS + commit report su git |
| `ci.yml` | PR/push su main | test, lint, mypy | solo CI |

Il server MCP legge i dati in `auto` (default) con priorità: **locale (git) → GCS**.

## Avvio

```json
{
  "mcpServers": {
    "source-observatory": {
      "command": "<workspace>/.venv/bin/python",
      "args": [
        "<workspace>/so_mcp/so_server.py"
      ]
    }
  }
}
```

Sostituisci `<workspace>` con il path assoluto del repo `source-observatory/`. L'avvio è via file path diretto (non `python -m`).

## Config artifact

Default pubblici:

- `CATALOG_INVENTORY_GCS_PREFIX=gs://dataciviclab-clean/catalog_inventory`

Variabili supportate per override:

- `SO_ARTIFACT_BACKEND`: `auto`, `gcs` o `local` (`auto` default)
- `SO_ENV_FILE`: file env opzionale; se non impostato, il server prova `dataciviclab-workspace/.env`
- `CATALOG_INVENTORY_GCS_PREFIX` o `SO_CATALOG_INVENTORY_GCS_PREFIX`: override del prefisso GCS inventory/source-check (valgono entrambi, con priorità alla versione `SO_`)
- `SO_CACHE_MAX_AGE_HOURS`: soglia di freschezza per cache locale (`24` default)

In `auto`, il server prova i prefissi GCS pubblici; se il read GCS fallisce, usa la cache locale e lo dichiara in `cache.fallback_warning`. In `gcs`, un errore GCS è bloccante. In `local`, il server usa solo i file locali.

## Tool — 5 strumenti

| # | Tool | Cosa fa | Legge da |
|---|---|---|---|
| 1 | `so_source_report` | 📋 Report completo per fonte (health, inventory, validated, verdict) | `data/reports/source_reports/{id}.json` (git) |
| 2 | `so_dashboard` | 📊 KPI riassuntivi di tutte le fonti | `data/reports/sources_dashboard.json` (git) |
| 3 | `so_inventory_search` | Cerca in `catalog_inventory_latest.parquet`: 3 modalità | parquet (locale → GCS) |
| 4 | `so_source_check` | Query `validated.parquet` + inventory status/diff | parquet (locale → GCS) |
| 5 | `so_find_by_url` | Cerca URL su validated + catalog_inventory (cross-parquet) | parquet (locale → GCS) |

### Modalità `so_inventory_search`

| Parametro | Modalità |
|---|---|
| `keyword=` | Raggruppa per fonte (recommend) |
| `source_id=` solo | Lista item con paginazione (`limit`/`offset`) |
| `query=` + opz. `source_id=`/`protocol=` | Full-text search |

### Modalità `so_source_check`

| Parametro | Modalità |
|---|---|
| `include_diff=True` | Inventory status + delta item count per fonte |
| Default | Query validated.parquet con filtri (source_id, min_score, has_results, grouped) |

### Caching

`so_source_report` e `so_dashboard` leggono file JSON statici da git — risposta in millisecondi senza cache. `so_inventory_search`, `so_source_check` e `so_find_by_url` hanno cache TTL 120s sui parquet.



## Boundary

Il layer MCP deve restare:

- read-only sugli artifact locali
- esplicito sulla provenienza del dato restituito
- conservativo quando un artifact manca
- coerente con i workflow pubblici di Source Observatory

Non deve:

- produrre nuovi artifact
- scaricare artifact GitHub Actions in modo implicito durante una query
- correggere automaticamente registry o workflow
- usare fallback opachi tra artifact con semantiche diverse
- trasformare una fonte assente dal parquet in un giudizio sulla fonte

## Artifact principali

| Artifact | Uso MCP |
|---|---|---|
| `data/reports/source_reports/{id}.json` | report completo per fonte (consumo standard) |
| `data/reports/sources_dashboard.json` | KPI riassuntivi di tutte le fonti |
| `data/radar/radar_summary.json` | stato fonte radar |
| `data/radar/radar_history.json` | storia probes e streak RED |
| `data/radar/STATUS.md` | sommario umano radar |
| `data/radar/sources_registry.yaml` | query fonti per protocol/kind/mode |
| `data/pipeline/validated.parquet` | ✅ **nuovo** — gruppi validati (reachable + schema colonne) |
| `data/catalog_inventory/generated/catalog_inventory_latest.parquet` | inventory cataloghi enumerabili |
| `data/catalog_inventory/generated/catalog_inventory_report.json` | stato per fonte del run inventory |
| GCS: `gs://dataciviclab-clean/catalog_inventory/` | percorso base parquet operativi (fallback) |

## Skill

Le 3 skill operative sono in `skills/`:

- `portal-scout.md` — dado un URL, identifica protocollo e decide go registry
- `inventory-triage.md` — browse inventory, estrai shortlist per source-check
- `source-check.md` — verifica singolo item, verdict go intake / watchlist / no-go

Il workflow di riferimento è `skills/portal-scout.md`, `skills/source-check.md` e `skills/inventory-triage.md`.
