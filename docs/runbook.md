# Runbook

Guida operativa breve per la v0 attuale.

## Radar

```powershell
python source-observatory/scripts/radar_check.py --dry-run
python source-observatory/scripts/radar_check.py
```

Usa `radar` quando la domanda è:

- la fonte risponde?
- ci sono problemi di timeout, SSL, DNS o HTTP?
- il piccolo universe v0 è sano?

Universe v0 attuale:

- `istat_sdmx`
- `anac`
- `inps`

Output:

- [STATUS.md](../data/radar/STATUS.md)

Scheduling v0:

- run giornaliero via GitHub Actions
- `workflow_dispatch` disponibile per run manuali
- il modello v0 e' `report-only`: aggiorna `STATUS.md` e `sources_registry.yaml`
- nessuna issue automatica o alerting complesso in questa fase

## Catalog-watch

Output correnti:

- [CATALOG_WATCH_REPORT.md](../data/catalog/CATALOG_WATCH_REPORT.md)
- [catalog_signals.json](../data/catalog/catalog_signals.json)

Usa `catalog-watch` quando la domanda è:

- l'inventario è cambiato?
- c'è drift strutturale?
- c'è un follow-up candidate che merita revisione umana?

## Resource monitor

```powershell
python source-observatory/scripts/monitor/resource_monitor.py --sources source-observatory/scripts/monitor/resource_monitor.sources.yml
```

Usa `monitor` solo per un set molto piccolo di casi Tier 1 in cui il change detection file/resource ha un next step difendibile.

Output:

- [latest.md](../data/monitor/reports/latest.md)
- [snapshots](../data/monitor/snapshots)

## Ordine consigliato

1. esegui `radar`
2. leggi `catalog-watch`
3. esegui `monitor` solo sui casi Tier 1
4. decidi se esiste davvero un follow-up umano giustificato

## Disciplina

- tieni l'universo piccolo
- preferisci segnali leggibili alla copertura larga
- non trattare il monitor file/resource come prodotto principale
- non automatizzare follow-up oltre il reporting semplice finché i falsi positivi non restano bassi
