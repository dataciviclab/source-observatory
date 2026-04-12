# Source Observatory

`source-observatory` è un piccolo intelligence layer per fonti pubbliche.

Fa parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

La sua v0 ha un perimetro volutamente stretto:

- verificare se una fonte è viva
- osservare un piccolo set di cataloghi ricchi per segnali di inventario significativi
- tenere il monitoraggio file/resource limitato a pochi casi Tier 1

Non è:

- una pipeline dataset
- un sistema di intake candidate
- una piattaforma di monitoraggio diffuso dataset-per-dataset

## Perimetro attuale

Il perimetro è definito in [`data/radar/sources_registry.yaml`](data/radar/sources_registry.yaml).

La regola guida è semplice:

- segnali leggibili su pochi cataloghi ricchi
- nessuna watchlist larga senza next step concreto

## Componenti

### `source-check`

Workflow pubblico/light per verificare se una fonte osservata regge davvero come pista del Lab.

File canonici:

- [source-check.md](workflows/source-check.md)
- [usage.md](docs/usage.md)

### `radar`

Risponde a:

- la fonte è raggiungibile?
- è fragile?

File canonici:

- [sources_registry.yaml](data/radar/sources_registry.yaml)
- [STATUS.md](data/radar/STATUS.md)
- [radar_check.py](scripts/radar_check.py)

### `catalog-watch`

Risponde a:

- l'inventario del catalogo è cambiato?
- c'è drift strutturale?
- c'è un segnale che merita follow-up umano?

Per la v0, `catalog-watch` resta `human-run`.

File canonici:

- [CATALOG_WATCH_REPORT.md](data/catalog/CATALOG_WATCH_REPORT.md)
- [catalog_signals.json](data/catalog/catalog_signals.json)
- [catalog-watch.md](workflows/catalog-watch.md)

### `monitor`

Layer secondario di supporto per un set molto piccolo di risorse Tier 1 già note.

File canonici:

- [resource_monitor.py](scripts/resource_monitor.py)
- [resource_monitor.sources.yml](scripts/resource_monitor.sources.yml)
- [latest.md](data/monitor/reports/latest.md)

## Struttura del repo

- `scripts/`
  - codice runtime canonico
- `data/`
  - stato generato e report
- `docs/`
  - uso, architettura, piano, runbook
- `workflows/`
  - workflow operativi posseduti dal repo

## Comandi canonici

Dalla root del repo:

```bash
python scripts/radar_check.py
python scripts/resource_monitor.py --sources scripts/resource_monitor.sources.yml --timeout 20
```

## Documentazione

- [runbook.md](docs/runbook.md)
- [architecture.md](docs/architecture.md)
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)
- [usage.md](docs/usage.md)
