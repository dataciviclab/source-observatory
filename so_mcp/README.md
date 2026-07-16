# Source Observatory MCP

Layer MCP read-only sugli artifact prodotti da Source Observatory.

Il server non sostituisce gli script di build e non scrive nello workspace: espone agli agenti una vista interrogabile degli artifact già generati da CI o run locali.

Gli artifact di catalog-inventory sono cache locali sotto `data/catalog_inventory/generated/`. Gli altri artifact (catalog_signals, radar, registry) sono sotto `data/catalog/` e `data/radar/`. Le risposte sui parquet includono un blocco `cache` con `source`, `uri`, `modified_at`, `age_hours`, soglia `max_age_hours` e warning quando la cache locale supera 24 ore.

## Workflow sorgente

| Workflow | Schedule | Prodotto principale | Dove finisce |
|---|---|---|---|
| `radar.yml` | **daily** 03:15 | `radar_summary.json`, `radar_history.json`, `sources_registry.yaml`, `STATUS.md` | commit su git |
| `observatory.yml` | **weekly** lun 03:20 | inventory parquet, source-check parquet, `catalog_signals.json`, source reports (33 JSON) | upload GCS + commit signals e report su git. Crea/aggiorna issue `catalog-alert` in caso di variazioni |
| `ci.yml` | PR/push su main | test, lint, mypy, smoke test | solo CI — non produce artifact |

Il server MCP legge i dati nell'ordine: **GCS → cache locale**. I commit su git sono la fonte per radar e signals. I parquet operativi sono letti dal prefisso GCS configurato (`CATALOG_INVENTORY_GCS_PREFIX`); la cache locale in `data/catalog_inventory/generated/` è il fallback.

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

## Tool — 7 strumenti

### Tool finali (dopo refactoring luglio 2026)

| # | Tool | Cosa fa | Sostituisce |
|---|------|---------|-------------|
| 1 | `so_registry_query` | Query `sources_registry.yaml` per protocol/source_kind/source_id | — |
| 2 | `so_radar_summary` | Radar health portale (con `include_history=True` per cronologia probe) | — |
| 3 | `so_inventory_search` | Cerca in `catalog_inventory_latest.parquet`: 3 modalità automatiche | `so_catalog_inventory_search` + `so_list_source_items` + `so_recommend_sources` |
| 4 | `so_source_check` | Query `source_check_results.parquet` + inventory report/diff | `so_inventory_query` + `so_inventory_status` + `so_inventory_diff` |
| 5 | `so_catalog_signals` | Segnali drift/inventory da `catalog_signals.json` | — |
| 6 | `so_find_by_url` | Cerca URL su source_check + catalog_inventory (cross-parquet) | — |
| 7 | `so_source_overview` | Composito: registry + radar + inventory + signals in 1 call | — |

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
| Default (senza `include_diff`) | Query source_check_results.parquet con filtri |

### Caching

Tutti i tool (tranne `so_registry_query` e `so_source_overview`) hanno cache TTL 120s. Chiave include parametri normalizzati — query identiche tornano in ~100ms invece di 2-6s.



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
|---|---|
| `data/radar/radar_summary.json` | stato fonte radar |
| `data/radar/radar_history.json` | storia probes e streak RED |
| `data/radar/STATUS.md` | sommario umano radar |
| `data/radar/sources_registry.yaml` | query fonti per protocol/kind/mode |
| `data/catalog/catalog_signals.json` | segnali catalog-watch |
| `data/catalog_inventory/generated/source_check_results.parquet` | risultati source-check item-level |
| `data/catalog_inventory/generated/catalog_inventory_latest.parquet` | inventory cataloghi enumerabili |
| `data/catalog_inventory/generated/catalog_inventory_report.json` | stato per fonte del run inventory |
| GCS: `gs://dataciviclab-clean/catalog_inventory/` | percorso base dei parquet operativi |

## Skill

Le 3 skill operative sono in `skills/`:

- `portal-scout.md` — dado un URL, identifica protocollo e decide go registry
- `inventory-triage.md` — browse inventory, estrai shortlist per source-check
- `source-check.md` — verifica singolo item, verdict go intake / watchlist / no-go

Il workflow di riferimento è `skills/portal-scout.md`, `skills/source-check.md` e `skills/inventory-triage.md`.
