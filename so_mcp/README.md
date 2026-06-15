# Source Observatory MCP

Layer MCP read-only sugli artifact prodotti da Source Observatory.

Il server non sostituisce gli script di build e non scrive nello workspace: espone agli agenti una vista interrogabile degli artifact già generati da CI o run locali.

Gli artifact di catalog-inventory sono cache locali sotto `data/catalog_inventory/generated/`. Gli altri artifact (catalog_signals, radar, registry) sono sotto `data/catalog/` e `data/radar/`. Le risposte sui parquet includono un blocco `cache` con `source`, `uri`, `modified_at`, `age_hours`, soglia `max_age_hours` e warning quando la cache locale supera 24 ore.

## Workflow sorgente

| Workflow | Schedule | Prodotto principale | Dove finisce |
|---|---|---|---|
| `radar.yml` | **daily** 03:15 | `radar_summary.json`, `radar_history.json`, `sources_registry.yaml`, `STATUS.md` | commit su git |
| `observatory.yml` | **weekly** lun 03:20 | inventory parquet, source-check parquet, `catalog_signals.json`, `CATALOG_WATCH_REPORT.md` | upload GCS + commit signals su git. Crea/aggiorna issue `catalog-alert` in caso di variazioni |
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

## Tool — raggruppati per skill

### SO_01 — portal-scout

| Tool | Uso |
|---|---|
| `so_find_by_url` | pre-check: gia catalogato? |
| — | Probe HTTP, CKAN, HTML: usa i tool **`toolkit_*`** del toolkit MCP |
| `so_registry_query` | pre-check: gia nel registry? |

> **Nota**: `so_probe_url`, `so_html_extract_links`, `so_ckan_package_show` sono stati rimossi. Usa i corrispondenti tool del toolkit MCP: `toolkit_probe_url`, `toolkit_html_extract_links`, `toolkit_ckan_package_show`.

### SO_02 — inventory-triage

| Tool | Uso |
|---|---|
| `so_inventory_status` | stato build inventory per fonte (con `include_diff=True` per delta item) |
| `so_catalog_inventory_search` | cerca item per keyword/testo |
| `so_recommend_sources` | trova source_id per keyword tema |
| — | Topic inference: usa **`toolkit_infer_topic`** del toolkit MCP |

> **Nota**: `so_infer_topic`, `so_inventory_diff` sono stati rimossi. Usa `so_inventory_status` con `include_diff=True` per il delta item.

### SO_03 — source-check

| Tool | Uso |
|---|---|
| `so_find_by_url` | pre-check: gia catalogato? |
| `so_inventory_query` | score esistente per questa fonte |
| — | Probe, CKAN, Topic: usa i tool **`toolkit_*`** del toolkit MCP |

> **Nota**: `so_probe_url`, `so_ckan_package_show`, `so_infer_topic` sono stati rimossi. Usa `toolkit_probe_url`, `toolkit_ckan_package_show`, `toolkit_infer_topic` del toolkit MCP.

### Extra (non legati a skill specifica)

| Tool | Uso |
|---|---|
| `so_radar_summary` | health portali (con `include_history=True` per cronologia probe) |
| `so_radar_history` | **[deprecato]** usa `so_radar_summary include_history=True` |
| `so_catalog_signals` | drift catalogo (weekly CI) |
| — | SPARQL: usa **`toolkit_sparql_query`** del toolkit MCP |

> **Nota**: `so_sparql_query`, `so_discover_sdmx`, `so_radar_status_md` sono stati rimossi. Usa `toolkit_sparql_query` per SPARQL, `so_list_source_items(source_id=istat_sdmx)` per SDMX, `so_radar_summary` per health portali.

## Tool detail

- `so_inventory_query`
  - legge `source_check_results.parquet`
  - cerca risultati item-level gia controllati
  - include `has_results` filter e `gcs_uri`

- `so_catalog_signals`
  - legge `catalog_signals.json`
  - segnali di drift o cambiamento catalogo

- `so_radar_summary`
  - legge `radar_summary.json`
  - stato GREEN/YELLOW/RED per fonte
  - con `include_history=True` include anche `radar_history.json`

- `so_radar_history` **[deprecato]**
  - usa `so_radar_summary` con `include_history=True`

- `so_find_by_url`
  - cerca URL in source_check_results e catalog_inventory
  - verifica se gia catalogato

- `so_registry_query`
  - interroga `sources_registry.yaml`
  - filtra per protocol, source_kind, observation_mode

- `so_inventory_status`
  - legge `catalog_inventory_report.json`
  - distingue ok/error/protocol_not_supported
  - con `include_diff=True` include anche il delta item (ex `so_inventory_diff`)

- `so_catalog_inventory_search`
  - legge `catalog_inventory_latest.parquet`
  - cerca item per testo/libro

- `so_recommend_sources`
  - cerca fonti nell'inventory per keyword
  - cerca in: item_name, title, tags, organization, notes_excerpt
  - ritorna: source_id, item_count, organizations



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
