# Architettura Intelligence Layer

- Data: 2026-03-27
- Stato: architettura v0 attiva

## Scopo

Trattare `source-observatory` come un piccolo intelligence layer con confini chiari:

- `radar_check.py` risponde a "la fonte o il catalogo è vivo?"
- `catalog-watch` risponde a "un inventario noto è cambiato in modo rilevante?"
- `source-check` risponde a "questa fonte merita lavoro del Lab?"

L'obiettivo non è monitorare tutto il web o "dataset in generale".
L'obiettivo è seguire una lista molto corta di fonti e cataloghi ricchi che contano già per DataCivicLab e capire se un segnale merita davvero un passo successivo.

Il repo rende di più se trattato come un intelligence layer leggero tra scouting e lavoro di pipeline.

## Rapporto con il toolkit

- `toolkit`
  - costruisce ed esegue pipeline dataset riproducibili
- `source-observatory`
  - osserva portali, cataloghi e resource note per segnali rilevanti
- `source-check`
  - decide se un segnale merita un passo successivo del Lab

Quindi l'osservatorio non dovrebbe provare a diventare un secondo sistema di pipeline.
Dovrebbe aiutare a decidere:

- se una fonte è reale e stabile
- se un cambiamento conta davvero
- se un pattern di fonte ricorrente merita supporto nel toolkit

## Struttura raccomandata

### Codice

- `scripts/radar_check.py`

### Stato e output

- `data/radar/sources_registry.yaml`
- `data/radar/STATUS.md`
- `data/catalog/CATALOG_WATCH_REPORT.md`
- `data/catalog/catalog_signals.json`

### Note e decisioni

- `docs/usage.md`
- `docs/runbook.md`
- `docs/catalog_watch_measurement_policy.md`

## Perimetro

Il set di fonti osservate è definito in `data/radar/sources_registry.yaml`.

Regola: se una fonte non produce segnali chiari e difendibili, resta fuori dal perimetro.

## Intelligence layer: inquadramento

L'osservatorio è più utile quando ogni segnale porta a un next step concreto:

- nessuna azione
- source-check
- rerun candidate
- verifica di un dataset pubblico stabile
- valutazione di pattern ricorrenti per il toolkit

Se un segnale non implica nessuno di questi follow-up, probabilmente è rumore.

Questo implica tre livelli di segnale:

- `radar`
  - salute della fonte o del catalogo
- `catalog-watch`
  - cambi di inventario e struttura su un catalogo noto

E un piccolo modello di stato per gli oggetti osservati:

- `radar-only`
- `catalog-watch`

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

## Cosa sta in catalog-watch

`catalog-watch` è il livello intermedio tra radar e monitoraggio file.

Usarlo quando:

- il protocollo è abbastanza stabile da poter essere osservato a livello inventario
- il segnale può informare source-check o priorità connector del toolkit

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

- radar/catalogo: poche fonti ricche con segnali leggibili

## Direzione

Per la v0 pubblicabile:

1. universe piccolo
2. segnali leggibili
4. niente automazione ampia finché il rumore non resta basso
