# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane.

Fa parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

Tre pezzi principali:

1. **catalog inventory** - enumera cosa esiste nei cataloghi osservati e produce un parquet interrogabile
2. **radar** - verifica se una fonte risponde prima di investirci tempo
3. **source-check / portal-scout** - workflow disciplinati per decidere se una fonte merita lavoro del Lab

Non è:

- una pipeline dataset
- un sistema di intake candidate
- una piattaforma di monitoraggio diffuso

## Catalog inventory

`scripts/build_catalog_inventory.py` entra nei cataloghi CKAN, SDMX e SPARQL del registry e produce uno snapshot tabulare di tutti gli item enumerabili.

Output:

- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- `data/catalog_inventory/generated/catalog_inventory_report.json`

Il parquet contiene oggi oltre 6000 item da fonti come INPS, OpenBDAP, MIM USTAT, Lavoro, Consip, Camera, ISPRA. È il punto di partenza per lo scouting: invece di navigare portali ostili manualmente, si interroga il parquet in DuckDB e si shortlista.

```bash
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated
```

## Radar

`scripts/radar_check.py` fa un health check economico di tutte le fonti nel registry: risponde, ha problemi SSL, è fragile?

Output: [`data/radar/STATUS.md`](data/radar/STATUS.md) - un artefatto leggibile usabile come pre-flight prima di un source-check o di un run DI.

```bash
python scripts/radar_check.py
```

Schedulato giornalmente via GitHub Actions. Il registry è in [`data/radar/sources_registry.yaml`](data/radar/sources_registry.yaml).

## Source-check e portal-scout

Non sono script, sono workflow disciplinati documentati in `workflows/`.

- [`portal-scout.md`](workflows/portal-scout.md) - classifica un portale prima che entri nel registry: è un catalogo reale? è inventariabile? quale modalità di osservazione ha senso?
- [`source-check.md`](workflows/source-check.md) - verifica se una fonte o un dataset regge davvero come pista del Lab. Entra con una fonte opaca, esce con un verdetto esplicito e un next step.

Il valore è nel processo: impedisce di portare in `dataset-incubator` candidate non ancora maturi.

## Catalog-watch

Osserva i cataloghi del registry per segnali di cambiamento inventariale. Non enumera cosa c'è dentro (quello è catalog inventory), risponde a "il catalogo è cambiato?".

Output: [`data/catalog/CATALOG_WATCH_REPORT.md`](data/catalog/CATALOG_WATCH_REPORT.md)

Resta `human-run` nella v0.

## Struttura del repo

- `scripts/` - codice runtime canonico
- `data/` - stato generato e report
- `docs/` - architettura, runbook, policy di misura
- `workflows/` - workflow operativi documentati

## Documentazione

- [runbook.md](docs/runbook.md)
- [architecture.md](docs/architecture.md)
- [usage.md](docs/usage.md)
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)
