# Architettura

`source-observatory` è l'intelligence layer leggero del Lab: osserva poche fonti pubbliche ricche e decide se un segnale merita lavoro umano.

Non è:

- una pipeline dataset
- un sistema di intake automatico
- monitoraggio diffuso del web

## Responsabilità

- `radar_check.py`: health check della fonte o del catalogo.
- `catalog-watch`: cambi inventariali o strutturali di cataloghi noti.
- `catalog inventory`: snapshot tabulare degli item enumerabili.
- `source-check`: valutazione umana di una fonte o dataset.

Il confine con `toolkit` è netto: `source-observatory` trova e qualifica segnali; `toolkit` costruisce pipeline riproducibili.

## Stato Canonico

- Registry: `data/radar/sources_registry.yaml`
- Radar: `data/radar/STATUS.md`
- Catalog-watch: `data/catalog/CATALOG_WATCH_REPORT.md`
- Signals: `data/catalog/catalog_signals.json`
- Inventory generated: `data/catalog_inventory/generated/`

## Perimetro

Una fonte entra nel registry solo se produce segnali chiari e difendibili.

Stati operativi:

- `radar-only`: fonte utile da tenere viva, ma non inventariabile.
- `catalog-watch`: catalogo osservabile a livello inventario.
- `source-check item-based`: valore in pochi item specifici, non nel catalogo.

## Tassonomia Segnali

Usare pochi tipi:

- `health`
- `inventory_change`
- `structural_drift`
- `follow_up_candidate`
- `missing_data`

Il segnale osservato non va confuso con il next step. Prima si classifica il segnale, poi si decide se aprire source-check, rerun candidate, watchlist o nessuna azione.

## Guardrail

- Tenere piccolo l'universo monitorato.
- Non trasformare delta numerici non comparabili in novità.
- Non automatizzare issue o intake finché il rumore non resta basso.
- Usare `catalog-watch` solo con metodo di misura dichiarato e confrontabile.

## Documenti Collegati

- [runbook.md](runbook.md): comandi e operatività.
- [catalog_watch_measurement_policy.md](catalog_watch_measurement_policy.md): regole di comparabilità dei delta.
- [workflows/](../workflows/): procedure per scout, watch e source-check.
