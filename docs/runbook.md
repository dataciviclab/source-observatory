# Runbook

Guida operativa breve per la v0 attuale.

## Radar

```bash
python scripts/radar_check.py --dry-run
python scripts/radar_check.py
```

Usa `radar` quando la domanda è:

- la fonte risponde?
- ci sono problemi di timeout, SSL, DNS o HTTP?
- il registry è sano?

Output:

- [STATUS.md](../data/radar/STATUS.md)

Scheduling v0:

- run giornaliero via GitHub Actions
- `workflow_dispatch` disponibile per run manuali
- il modello v0 è `report-only`: aggiorna `STATUS.md` e `sources_registry.yaml`
- nessuna issue automatica o alerting complesso in questa fase

## Catalog-watch

Output correnti:

- [CATALOG_WATCH_REPORT.md](../data/catalog/CATALOG_WATCH_REPORT.md)
- [catalog_signals.json](../data/catalog/catalog_signals.json)

Usa `catalog-watch` quando la domanda è:

- l'inventario è cambiato?
- c'è drift strutturale?
- c'è un follow-up candidate che merita revisione umana?

Modello v0:

- `catalog-watch` resta `human-run`
- nessuno scheduler dedicato in questa fase
- il run va usato quando serve un check metodologicamente difendibile, non come polling continuo
- gli output canonici restano `CATALOG_WATCH_REPORT.md` e `catalog_signals.json`

## Catalog inventory

```bash
python scripts/build_catalog_inventory.py
```

Usa `catalog inventory` quando la domanda è:

- quali item sono oggi enumerabili nei cataloghi osservati?
- quali fonti `catalog-watch` producono un inventario riusabile per scouting?
- il perimetro pubblico resta coerente con le esclusioni dichiarate?

Output (non versionati nel repo):

- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- `data/catalog_inventory/generated/catalog_inventory_report.json`

Per ottenere l'ultimo output senza rieseguire: artifact del workflow `catalog-inventory` su GitHub Actions, oppure GCS se configurato.

Disciplina:

- il perimetro segue le fonti `catalog-watch` del registry
- una fonte può restare osservata in SO ma non essere inventariabile
- `anac` oggi resta escluso dall'inventory automatico per vincoli WAF
- l'upload su GCS è opzionale e richiede secret espliciti
- il workflow gira ogni lunedì (schedule) ed è disponibile anche via `workflow_dispatch`

## Ordine consigliato

1. esegui `radar`
2. leggi `catalog-watch`
3. decidi se esiste davvero un follow-up umano giustificato

## Disciplina

- tieni l'universo piccolo
- preferisci segnali leggibili alla copertura larga
