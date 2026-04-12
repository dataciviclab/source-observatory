# Catalog Inventory

Artifact derivato dai cataloghi osservati in `source-observatory`.

Serve per:
- consultazione veloce dei cataloghi gia' osservati
- scouting di dataset e dataflow per nuovi source-check
- query locali o snapshot pubblici leggeri quando il perimetro e' abbastanza stabile

Non e':
- il catalogo canonico del Lab
- una promessa di copertura completa di tutte le fonti nel registry
- un sostituto del radar o del catalog-watch

## Perimetro attuale

Sorgenti oggi inventariate in modo riproducibile:
- `istat_sdmx`
- `inps`
- `openbdap`
- `ispra_linked_data`

Sorgenti osservate ma non inventariate automaticamente:
- `anac`

Motivo dell'esclusione di `anac`:
- la fonte resta nel registry ed e' osservata lato `catalog-watch`
- ma risponde ai client HTTP standard con pagina WAF `Request Rejected`
- non introduciamo bypass o workaround anti-bot poco difendibili solo per forzare il conteggio

## Output attesi

Il workflow manuale produce due file:
- `catalog_inventory_latest.parquet`
- `catalog_inventory_report.json`

Per default questi output vengono generati in:
- `data/catalog_inventory/generated/`

La directory `generated/` non e' versionata nel repo:
- gli artifact vengono esposti come artifact GitHub Actions
- l'upload su GCS e' opzionale e richiede secret/config espliciti

## Schema minimo del parquet

Colonne chiave:
- `captured_at`: timestamp UTC del run inventory
- `source_id`: id della fonte nel registry (`istat_sdmx`, `inps`, `openbdap`, ...)
- `source_kind`: oggi atteso `catalog`
- `protocol`: protocollo della fonte (`ckan`, `sdmx`, `sparql`)
- `inventory_method`: metodo usato per l'enumerazione (`package_search`, `package_list`, `dataflow_count`, `sparql_query`)
- `item_kind`: tipo di item (`dataset` o `dataflow`)
- `item_id`: identificativo tecnico dell'item
- `item_name`: nome macchina o slug quando disponibile
- `title`: titolo umano quando disponibile
- `organization`: organizzazione CKAN quando disponibile
- `tags`: tag CKAN compressi in stringa
- `notes_excerpt`: estratto breve delle note, se disponibile
- `source_url`: endpoint usato per l'inventory
- `ordinal`: posizione del record nell'enumerazione della fonte

Nota operativa:
- per cataloghi CKAN il builder prova in ordine `package_search`, `current_package_list_with_resources`, `package_list`
- `current_package_list_with_resources` e' disabilitato per `inps` in ambiente locale Windows per instabilita SSL/GIL (fall-back diretto a `package_list` con warning esplicito)
- la logica di enrichment resta attiva per altri cataloghi CKAN futuri
- per cataloghi SPARQL il builder usa solo query dichiarate nel registry o template espliciti; il pilot iniziale è `dcat_datasets`
- il template SPARQL generico enumera dataset e metadati DCAT leggeri; non popola `distribution_url`, `distribution_count` o `format`
- per SPARQL `tags` resta vuoto e i temi DCAT stanno nel campo opzionale `theme`; query custom possono aggiungere campi opzionali come `distribution_url`, `distribution_count` e `format`

## Workflow

Workflow GitHub Actions disponibile:
- `.github/workflows/catalog-inventory-manual.yml`

Comando locale equivalente:

```bash
python scripts/build_catalog_inventory.py
```

## Caveat

- il perimetro segue solo le fonti `catalog-watch` del registry
- l'inventory puo' essere intenzionalmente parziale se una fonte e' osservabile ma non inventariabile in modo stabile
- il README locale resta in `_local/data/catalog_inventory/README.md`
- `istat_sdmx` oggi viene enumerato in modo riproducibile tramite `https://sdmx.istat.it/SDMXWS/rest/dataflow/IT1`, coerente con la baseline aggiornata a `509`
