# Source Observatory MCP

Layer MCP read-only sugli artifact prodotti da Source Observatory.

Il server non sostituisce gli script di build e non scrive nello workspace: espone agli agenti una vista interrogabile degli artifact già generati da CI o run locali.

Gli artifact sotto `data/*/generated/` sono cache locali. La fonte operativa corrente per i parquet è il prefisso GCS configurato dai workflow; gli artifact GitHub Actions restano utili per debug e recupero manuale. Le risposte sui parquet includono un blocco `cache` con `source`, `uri`, `modified_at`, `age_hours`, soglia `max_age_hours` e warning quando la cache locale supera 24 ore.

## Avvio

Config canonica workspace:

```json
{
  "mcpServers": {
    "source-observatory": {
      "command": "/home/gabry/dev/dataciviclab-workspace/source-observatory/.venv/bin/python",
      "args": [
        "/home/gabry/dev/dataciviclab-workspace/source-observatory/mcp/so_server.py"
      ],
      "cwd": "/tmp"
    }
  }
}
```

Usare l'avvio via file path, non `python -m mcp.so_server`: la repo contiene una directory locale `mcp/` che può collidere con la libreria Python `mcp`.

## Config artifact

Default pubblici:

- `CATALOG_INVENTORY_GCS_PREFIX=gs://dataciviclab-clean/catalog_inventory`

Variabili supportate per override:

- `SO_ARTIFACT_BACKEND`: `auto`, `gcs` o `local` (`auto` default)
- `SO_ENV_FILE`: file env opzionale; se non impostato, il server prova `dataciviclab-workspace/.env`
- `CATALOG_INVENTORY_GCS_PREFIX`: override del prefisso GCS inventory/source-check
- `SO_CACHE_MAX_AGE_HOURS`: soglia di freschezza per cache locale (`24` default)

In `auto`, il server prova i prefissi GCS pubblici; se il read GCS fallisce, usa la cache locale e lo dichiara in `cache.fallback_warning`. In `gcs`, un errore GCS è bloccante. In `local`, il server usa solo i file locali.

## Tool

- `so_inventory_query`
  - legge `data/catalog_inventory/generated/source_check_results.parquet`
  - serve per cercare risultati item-level già controllati
  - include `has_results` filter e `gcs_uri` in risposta

- `so_catalog_signals`
  - legge `data/catalog/catalog_signals.json`
  - serve per controllare segnali di drift o cambiamento catalogo

- `so_radar_summary`
  - legge `data/radar/radar_summary.json`
  - serve per capire lo stato sintetico delle fonti nel radar

- `so_radar_history`
  - legge `data/radar/radar_history.json`
  - serve per verificare streak/persistent RED e storia probes per fonte

- `so_radar_status_md`
  - legge `data/radar/STATUS.md`
  - serve per avere un sommario umano leggibile dello stato radar

- `so_radar_delta`
  - confronta ultimo e penultimo probe del radar
  - restituisce fonti cambiate, nuove RED, recovery, persistent RED

- `so_find_by_url`
  - cerca un URL in source_check_results e catalog_inventory
  - serve per capire se un URL è già catalogato

- `so_registry_query`
  - interroga `data/radar/sources_registry.yaml`
  - filtra per protocol, source_kind, observation_mode o cerca per source_id

- `so_inventory_status`
  - legge `data/catalog_inventory/generated/catalog_inventory_report.json`
  - serve per distinguere fonte assente, errore di run, protocollo non supportato e inventory riuscito

- `so_catalog_inventory_search`
  - legge `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
  - serve per cercare item e dataflow nel catalog inventory derivato

- `so_probe_url`
  - esegue una verifica HTTP leggera su un URL esplicito
  - è pensato per controlli puntuali, non per crawling

- `so_discover_sdmx`
  - usa solo `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
  - se l'inventory SDMX non è disponibile, restituisce lo stato del report inventory invece di ripiegare su artifact item-level diversi

- `so_portal_candidates`
  - **DEPRECATED**: portal-scout non è più nel perimetro di SO. Rimosso.

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

## Uso operativo

Per una domanda su "cosa sappiamo già":

1. leggere prima radar e report inventory
2. controllare il blocco `cache` prima di trattare i parquet come correnti
3. interrogare l'inventory solo se la fonte è inventariata
4. usare i source-check item-level per evidenze già validate
5. usare probe o discovery solo per verifiche puntuali

Il workflow di riferimento è `skills/mcp-artifact-triage.md`.