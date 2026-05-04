# Skills

Indice delle guide operative di `source-observatory`.

## MCP tools come modo consigliato

Il layer MCP SO (`mcp/so_server_core.py`) è il modo **consigliato** per leggere tutti gli artifact del Lab:
- `so_radar_summary`, `so_radar_delta`, `so_radar_history` — radar
- `so_inventory_status`, `so_inventory_query`, `so_catalog_signals` — inventory
- `so_find_by_url`, `so_catalog_inventory_search` — ricerca item
- `so_registry_query`, `so_catalog_inventory_search`, `so_probe_url` — scouting
- `so_discover_sdmx` — discovery ISTAT SDMX

Vedi [mcp-artifact-triage.md](./mcp-artifact-triage.md) per l'ordine di lettura canonico.

I workflow documentati sotto partono dal presupposto che gli artifact siano già stati consultati via MCP o che il parquet locale sia disponibile.

## Come orientarsi

- [catalog-inventory-scout.md](./catalog-inventory-scout.md)
  - triage di un catalog inventory per ricavare una shortlist
  - decide cosa mandare a `source-check` o `watchlist`

- [mcp-artifact-triage.md](./mcp-artifact-triage.md)
  - lettura ordinata degli artifact Source Observatory via MCP read-only
  - chiarisce cosa è coperto, cosa manca e quale workflow usare dopo

- [source-check.md](./source-check.md)
  - verifica se una fonte o un dataset pubblico regge davvero come pista del Lab
  - esce con un verdetto singolo e un next step esplicito

## Boundary rapido

- `catalog-inventory-scout`
  - triage di una lista di item di un catalogo
- `mcp-artifact-triage`
  - orientamento sugli artifact già prodotti da radar, catalog-watch, inventory e discovery
- `source-check`
  - valutazione umana della fonte come possibile pista del Lab

> I segnali di drift/inventory change del catalogo sono prodotti automaticamente dalla CI (`observatory.yml`) e leggibili in `data/catalog/CATALOG_WATCH_REPORT.md` e `data/catalog/catalog_signals.json`.

## Regola pratica

Se la domanda è:

- "cosa c'è in questo catalogo e cosa vale la pena approfondire?" -> `catalog-inventory-scout`
- "cosa dicono gli artifact SO già prodotti?" -> `mcp-artifact-triage`
- "questo portale è davvero un catalogo osservabile?" -> `portal-scout`
- "il catalogo ha cambiato inventario o struttura?" -> leggi `data/catalog/CATALOG_WATCH_REPORT.md`
- "questa fonte regge davvero come pista del Lab?" -> `source-check`

## Ingresso di una nuova fonte

Le fonti nuove vengono aggiunte al `sources_registry.yaml` manualmente, con:

- `source_id`, `base_url`, `protocol`
- `observation_mode`: `catalog-watch` o `radar-only`
- eventuale `note` sulla fonte

Non esiste un processo di discovery automatico. I portali CKAN italiani noti sono tracciati da `ckan_find_portals(country="Italy")` o dal registry di datashades.

## Nota: catalog inventory

`catalog inventory` non è un workflow. È un artifact derivato:
uno snapshot tabulare di tutti gli item in un catalogo noto, prodotto da `scripts/build_catalog_inventory.py`.

Il catalog inventory serve per scouting e triage di item promettenti, non per rilevare cambiamenti.
I segnali di cambiamento inventariale sono prodotti automaticamente dalla CI in `data/catalog/catalog_signals.json` e `data/catalog/CATALOG_WATCH_REPORT.md`.

L'inventory nasce solo dopo un esito `GO catalog-watch` e solo se esiste un metodo di enumerazione verificato.
Se il portale è `radar-only` o `source-check item-based`, l'inventory non è il passo giusto.

## Documentazione e Runbook

- [runbook.md](../docs/runbook.md)
  - runbook operativo per tutti i controlli (radar, catalog-watch, inventory)
  - include dettagli sulla gestione del registry e delle GitHub Actions
