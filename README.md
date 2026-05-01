# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

Risponde a una domanda sola: **questa fonte vale il tempo del Lab?**

## Il funnel

```
gate  ── catalog-watch ── catalog-inventory ── source-check
     └── radar-only
```

1. **Gate** — decide il regime di osservazione (`catalog-watch` o `radar-only`)
2. **Catalog-inventory** — enumera gli item dei cataloghi ammessi
3. **Source-check** — valuta qualità e granularità dei dataset

Il funnel è alimentato dal `sources_registry.yaml`: ogni fonte ha un `source_id`, un `protocol` e un `observation_mode`. Le fonti nuove vengono aggiunte al registry manualmente.

## Script

| Script | Cosa fa |
|---|---|
| `scripts/radar_check.py` | Health check giornaliero delle fonti nel registry |
| `scripts/build_catalog_inventory.py` | Snapshot tabulare di tutti gli item enumerabili |
| `scripts/build_catalog_signals.py` | Segnali drift/inventory del catalogo; health delegata a radar |
| `scripts/bulk_source_check.py` | Scoring di qualità, granularità e rilevanza per ogni item |

```bash
# Radar (giornaliero)
python scripts/radar_check.py

# Catalog inventory (settimanale)
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated

# Source-check (settimanale — scoring completo di tutti gli item)
python scripts/bulk_source_check.py --only-with-title --include-no-url --workers 8
```

## Workflow

I workflow in `workflows/` sono istruzioni operative per agenti e review umana. In parallelo, alcuni workflow GitHub Actions schedulati producono artifact e report di osservazione.

- [`workflows/source-check.md`](workflows/source-check.md) — valuta se una fonte regge come pista del Lab
- [`workflows/catalog-inventory-scout.md`](workflows/catalog-inventory-scout.md) — triage degli item in un catalogo noto

## Output e artefatti

Gli artifact generati (`parquet`, `json`, `STATUS.md`) non sono versionati nel repo. Si ottengono da GitHub Actions o GCS se configurato.

Se GCS non è configurato, i workflow restano eseguibili: usano artifact Actions e saltano i passaggi opzionali di storage remoto.

- `data/radar/STATUS.md` — stato corrente delle fonti nel registry
- `data/radar/radar_summary.json` — health complessivo (GREEN/YELLOW/RED per fonte)
- `data/catalog/catalog_signals.json` — segnali drift/inventory per singola fonte
- `data/catalog/CATALOG_WATCH_REPORT.md` — report leggibile prodotto dalla CI ogni lunedì
- `data/catalog_inventory/generated/catalog_inventory_latest.parquet` — oltre 6000 item da INPS, OpenBDAP, ISPRA, Camera e altri
- `data/catalog_inventory/generated/source_check_results.parquet` — scoring completo degli item

I tre JSON (`radar_summary`, `catalog_signals`) sono consumati da **agent-context-builder** per includere lo stato delle fonti nel contesto operativo degli agenti AI.

## Struttura

```
scripts/    codice runtime
data/       stato generato e report
workflows/  istruzioni operative per agenti
docs/       architettura, runbook, policy
```

## Documentazione

- [runbook.md](docs/runbook.md)
- [architecture.md](docs/architecture.md)
- [catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md)
