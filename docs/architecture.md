# Architettura Intelligence Layer

- Data: 2026-03-27
- Stato: architettura v0 attiva

## Scopo

Trattare `source-observatory` come un piccolo intelligence layer con confini chiari:

- `radar_check.py` risponde a "la fonte o il catalogo e' vivo?"
- `catalog-watch` risponde a "un inventario noto e' cambiato in modo rilevante?"
- `resource_monitor.py` risponde a "una file/resource Tier 1 e' cambiata?"
- `source-check` risponde a "questa fonte merita lavoro del Lab?"

L'obiettivo non e' monitorare tutto il web o "dataset in generale".
L'obiettivo e' seguire una lista molto corta di fonti e cataloghi ricchi che contano gia' per DataCivicLab e capire se un segnale merita davvero un passo successivo.

Il repo rende di piu' se trattato come un intelligence layer leggero tra scouting e lavoro di pipeline.

## Rapporto con il toolkit

- `toolkit`
  - costruisce ed esegue pipeline dataset riproducibili
- `source-observatory`
  - osserva portali, cataloghi e resource note per segnali rilevanti
- `source-check`
  - decide se un segnale merita un passo successivo del Lab

Quindi l'osservatorio non dovrebbe provare a diventare un secondo sistema di pipeline.
Dovrebbe aiutare a decidere:

- se una fonte e' reale e stabile
- se un cambiamento conta davvero
- se un pattern di fonte ricorrente merita supporto nel toolkit

## Struttura raccomandata

### Codice

- `scripts/radar_check.py`
- `scripts/resource_monitor.py`
- `scripts/resource_monitor.sources.yml`

### Stato e output

- `source-observatory/data/radar/sources_registry.yaml`
- `source-observatory/data/radar/STATUS.md`
- `source-observatory/data/catalog/CATALOG_WATCH_REPORT.md`
- `source-observatory/data/catalog/catalog_signals.json`
- `source-observatory/data/monitor/snapshots/`
- `source-observatory/data/monitor/reports/latest.md`

### Note e decisioni

- `source-observatory/docs/usage.md`
- `source-observatory/docs/runbook.md`
- `source-observatory/docs/catalog_watch_measurement_policy.md`

## Universe v0

Per la v0 il set va tenuto deliberatamente piccolo:

- `istat_sdmx`
- `anac`
- `inps`
- `openbdap`

Se una fonte non produce segnali chiari e difendibili, resta fuori dalla v0.

## Intelligence layer: inquadramento

L'osservatorio e' piu' utile quando ogni segnale porta a un next step concreto:

- nessuna azione
- source-check
- rerun candidate
- verifica di un dataset pubblico stabile
- valutazione di pattern ricorrenti per il toolkit

Se un segnale non implica nessuno di questi follow-up, probabilmente e' rumore.

Questo implica tre livelli di segnale:

- `radar`
  - salute della fonte o del catalogo
- `catalog-watch`
  - cambi di inventario e struttura su un catalogo noto
- `resource_monitor`
  - cambi file/resource su una lista corta di fonti ad alto segnale

E un piccolo modello di stato per gli oggetti osservati:

- `radar-only`
- `catalog-watch`
- `monitor-active`

## Cosa sta nel radar

Il radar dovrebbe tenere solo salute della fonte:

- base URL raggiungibile o no
- problemi di timeout / SSL / DNS
- metadati di protocollo a grana grossa

Buoni candidati v0:

- ISTAT SDMX
- ANAC
- INPS
- OpenBDAP

## Cosa sta nel resource monitor

Il resource monitor dovrebbe seguire solo fonti con una ragione operativa chiara.

Includere:

- candidate DI attivi con update attesi
- dataset stabili in `analisi/` dove nuove annualita' contano
- un numero molto piccolo di support dataset strategici

Escludere:

- watchlist larghe senza next step
- portali instabili senza un adapter usabile
- grandi listing HTML con pattern `include` deboli

## Cosa sta in catalog-watch

`catalog-watch` e' il livello intermedio tra radar e monitoraggio file.

Usarlo quando:

- il portale conta, ma un file monitor concreto sarebbe rumoroso
- il protocollo e' abbastanza stabile da poter essere osservato a livello inventario
- il segnale puo' informare source-check o priorita' connector del toolkit

Casi tipici v0:

- CKAN package inventories
- SDMX dataflows

Tassonomia raccomandata dei segnali:

- `health`
- `inventory_change`
- `structural_drift`
- `follow_up_candidate`
- `missing_data`

Per la v0 questa tassonomia va tenuta stretta: non va espansa facilmente e non dovrebbe mescolare segnale osservato e passo successivo.

Questa tassonomia serve a evitare che il layer catalogo degeneri in:

- scraping rumoroso
- monitoraggio diffuso di singoli dataset
- automatismi di intake o issue

## Regola pratica attuale

Tenere il set monitorato piccolo:

- radar/catalogo: 3 fonti ricche
- monitor: 3-5 casi Tier 1 al massimo

Se una fonte non ha un next step plausibile dopo un cambio, dovrebbe restare nel radar o nello scouting, non nel monitor.

## Direzione

Per la v0 pubblicabile:

1. universe piccolo
2. segnali leggibili
3. monitor davvero secondario
4. niente automazione ampia finche' il rumore non resta basso
