# Contributing to source-observatory

Questa guida vale per la repo `source-observatory`.

Per le regole GitHub condivise dell'organizzazione, parti prima da
[`.github`](https://github.com/dataciviclab/.github).

## A cosa serve questa repo

`source-observatory` è l'intelligence layer leggero per fonti pubbliche italiane.
Risponde a una domanda: **questa fonte vale il tempo del Lab?**

Il funnel del repo:

```
radar ── gate ── catalog-watch ── catalog-inventory ── pipeline (merge → validate)
              └── radar-only
```

Qui stanno:

- `sources_registry.yaml` — registro di tutte le fonti osservate
- `scripts/` — radar check, inventory, pipeline, report
- `scripts/pipeline/` — merge + validate (produce `validated.parquet`)
- `skills/` — guide operative per agenti (source-check, inventory-triage, portal-scout)
- `so_mcp/` — layer MCP read-only sugli artifact
- `data/` — artifact versionati: radar_summary, radar_history
- workflow CI: `radar.yml` (daily), `observatory.yml` (weekly)

Qui non stanno:

- pipeline di trasformazione dati (RAW → CLEAN → MART) — va in `dataset-incubator` + `toolkit`
- analisi pubbliche o notebook — vanno in `dataciviclab/analisi/`
- il motore della pipeline — va in `toolkit`
- package condivisi di infrastruttura — vanno in `lab-connectors`
- policy GitHub comuni — vanno in `.github`

## Come funziona il funnel

Le fonti nel `sources_registry.yaml` hanno un `observation_mode` che ne determina
il trattamento:

| Modalità | Cosa succede | Frequenza |
|---|---|---|
| `radar-only` | Solo health check HTTP | Daily (radar.yml) |
| `catalog-watch` | Radar + inventory + pipeline (merge→validate) | Daily radar + weekly observatory |

### Radar (daily)

Probe HTTP leggero su ogni fonte. Produce:
- `radar_summary.json` — stato compatto per fonte (GREEN/YELLOW/RED)
- `radar_history.json` — cronologia probe
- `STATUS.md` — sommario leggibile

### Observatory (weekly, lunedì)

1. Build inventory parquet per fonti `catalog-watch`
2. Pipeline merge + validate → `validated.parquet`
3. Report per fonte + dashboard
4. Upload su GCS

## Setup locale

```bash
pip install -e ".[dev]"
```

Dipende da `lab-connectors` per HTTP client e MCP core. Se lavori su script
che usano `lab_connectors`, assicurati di averlo installato:

```bash
pip install -e ../lab-connectors
```

### Comandi utili

```bash
# Radar check manuale
so-radar-check

# Catalog inventory
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated --workers 4

# Pipeline merge + validate
so-run-pipeline --workers 4

# Build reports
so-build-reports

# Test
pytest tests/
ruff check .
mypy scripts/
```

## Quando aprire una issue

Apri una issue in `source-observatory` se il lavoro riguarda:

- aggiungere o rimuovere una fonte dal registry
- modificare il funnel o i criteri di osservazione
- bug o miglioramenti ai workflow CI (radar, observatory)
- miglioramenti a script, MCP o skills

Template esistenti:

- `.github/ISSUE_TEMPLATE/source-check.yml` — per verificare una fonte specifica
- `.github/ISSUE_TEMPLATE/inventory-triage.yml` — per triage di un inventory

## Quando usare una Discussion

Se stai esplorando una fonte non ancora verificata o un possibile nuovo
protocollo di osservazione, usa prima una Discussion nella categoria giusta.
Vedi [`.github`](https://github.com/dataciviclab/.github) per orientarti.

## Prima di aprire una PR

- verifica se esiste già una issue collegata
- tieni il perimetro stretto
- se aggiungi una fonte, aggiorna `sources_registry.yaml` e verifica
  che `radar_check.py` la gestisca
- se modifichi uno script, controlla che i test passino
- se modifichi il funnel, controlla anche `docs/architecture.md`

## Riferimenti

- [README.md](README.md) — panoramica del repo
- [docs/runbook.md](docs/runbook.md) — guida operativa radar, inventory, pipeline
- [docs/architecture.md](docs/architecture.md) — architettura del sistema
- [docs/catalog_watch_measurement_policy.md](docs/catalog_watch_measurement_policy.md) — policy di misura
- [skills/](skills/) — guide operative per agenti
- [`lab-connectors`](https://github.com/dataciviclab/lab-connectors) — dipendenza condivisa
- [`dataset-incubator`](https://github.com/dataciviclab/dataset-incubator) — downstream: qui finiscono i validated che diventano candidate
