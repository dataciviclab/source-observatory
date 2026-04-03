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

## Workflow

Workflow GitHub Actions disponibile:
- `.github/workflows/catalog-inventory-manual.yml`

Comando locale equivalente:

```powershell
python source-observatory/scripts/build_catalog_inventory.py
```

## Caveat

- il perimetro segue solo le fonti `catalog-watch` del registry
- l'inventory puo' essere intenzionalmente parziale se una fonte e' osservabile ma non inventariabile in modo stabile
- il README locale resta in `_local/data/catalog_inventory/README.md`
