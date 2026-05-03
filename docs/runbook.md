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

- run giornaliero via GitHub Actions (`observatory.yml`)
- `workflow_dispatch` disponibile per run manuali
- il modello v0 è `report-only`: aggiorna `STATUS.md` e `sources_registry.yaml`
- nessuna issue automatica o alerting complesso in questa fase

Comportamento probe:

- non-SDMX portals con timeout/connection error (http_code="-", status YELLOW): retry automatico 1x. Se il retry è GREEN, lo usa; altrimenti annota "Retry timeout/connection: ..." e mantiene YELLOW.
- exception isolation: un portal che esplode non ferma il loop — ritorna ProbeResult(RED) e il probe continua con le fonti successive.

Manutenzione del Registry:

- Se una fonte è stabilmente giù, verificare manualmente l'URL.
- Se l'URL è cambiato, aggiornare `data/radar/sources_registry.yaml`.
- Se la fonte è definitivamente rimossa, valutare la disattivazione o rimozione nel registry.

Boundary:

- Se il problema è di contenuto (non infrastrutturale) -> [source-check.md](../skills/source-check.md)
- Se il catalogo è cambiato ma la fonte è viva -> [catalog-inventory-scout.md](../skills/catalog-inventory-scout.md)

## Catalog-watch

Output correnti:

- [CATALOG_WATCH_REPORT.md](../data/catalog/CATALOG_WATCH_REPORT.md)
- [catalog_signals.json](../data/catalog/catalog_signals.json)

Usa `catalog-watch` quando la domanda è:

- l'inventario è cambiato?
- c'è drift strutturale?
- c'è un follow-up candidate che merita revisione umana?

Modello v0:

- i segnali vengono prodotti automaticamente dal workflow schedulato `observatory.yml` (ogni lunedì 03:15)
- il follow-up resta `human-run`: il report non sostituisce la review umana sui cambi rilevanti
- il run manuale va usato quando serve un check metodologicamente difendibile fuori schedule
- gli output canonici restano `CATALOG_WATCH_REPORT.md` e `catalog_signals.json`
- problemi di connessione/HTTP vanno letti in `radar_summary.json`, non in `catalog_signals.json`

## Catalog inventory

```bash
python scripts/build_catalog_inventory.py
python scripts/build_catalog_inventory.py --workers 3  # parallelo, sperimentale
```

Usa `catalog inventory` quando la domanda è:

- quali item sono oggi enumerabili nei cataloghi osservati?
- quali fonti `catalog-watch` producono un inventario riusabile per scouting?
- il perimetro pubblico resta coerente con le esclusioni dichiarate?

Output (non versionati nel repo):

- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- `data/catalog_inventory/generated/catalog_inventory_report.json`

Per ottenere l'ultimo output senza rieseguire: artifact del workflow `observatory` su GitHub Actions, oppure GCS se configurato.

Disciplina:

- il perimetro segue le fonti `catalog-watch` del registry
- una fonte può restare osservata in SO ma non essere inventariabile
- `anac` oggi resta escluso dall'inventory automatico per vincoli WAF
- l'upload su GCS è opzionale e richiede secret espliciti
- in assenza di GCS il workflow resta valido: usa baseline locale vuota e salta i passaggi opzionali di storage/diff
- il workflow gira ogni lunedì (schedule) ed è disponibile anche via `workflow_dispatch`

## Ordine consigliato

1. esegui `radar`
2. leggi `catalog-watch`
3. decidi se esiste davvero un follow-up umano giustificato

## Disciplina

- tieni l'universo piccolo
- preferisci segnali leggibili alla copertura larga
