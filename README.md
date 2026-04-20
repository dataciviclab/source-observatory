# Source Observatory

Intelligence layer leggero per fonti pubbliche italiane — parte dell'ecosistema [DataCivicLab](https://github.com/dataciviclab).

Risponde a una domanda sola: **questa fonte vale il tempo del Lab?**

## Il funnel

```
discover_portals  →  portal-scout  →  gate
                                        ├─ catalog-watch   (catalogo osservabile)
                                        ├─ radar-only      (monitoraggio passivo)
                                        └─ source-check    (valutazione manuale)
                                              ↓
                                        catalog-inventory  (snapshot interrogabile)
```

1. **Discover** — trova portali PA nazionali via DDG, proba il protocollo (CKAN/SDMX/SPARQL)
2. **Portal-scout** — classifica la superficie tecnica, assegna un verdict
3. **Gate** — decide il regime di osservazione
4. **Catalog-inventory** — enumera gli item dei cataloghi ammessi

## Script

| Script | Cosa fa |
|---|---|
| `scripts/discover_portals.py` | Discovery DDG + protocol probe → parquet candidati |
| `scripts/portal_scout.py` | Sonda copertura metadata su campione → JSON per portale |
| `scripts/radar_check.py` | Health check giornaliero delle fonti nel registry |
| `scripts/build_catalog_inventory.py` | Snapshot tabulare di tutti gli item enumerabili |
| `scripts/build_catalog_signals.py` | Segnali drift/inventory del catalogo; health delegata a radar |

```bash
# Discovery mirata per protocollo
python scripts/discover_portals.py --protocols ckan --only-matched

# Scout su candidati
python scripts/portal_scout.py --registry-path /tmp/candidate.yaml --dry-run

# Radar
python scripts/radar_check.py

# Catalog inventory
python scripts/build_catalog_inventory.py --out-dir data/catalog_inventory/generated
```

## Workflow

I workflow sono istruzioni per agenti — non pipeline CI/CD. Seguire in ordine per ogni portale nuovo.

- [`workflows/portal-scout.md`](workflows/portal-scout.md) — classifica un portale e assegna verdict
- [`workflows/source-check.md`](workflows/source-check.md) — valuta se una fonte regge come pista del Lab
- [`workflows/catalog-watch.md`](workflows/catalog-watch.md) — osserva cambi inventariali del catalogo
- [`workflows/catalog-inventory-scout.md`](workflows/catalog-inventory-scout.md) — triage degli item in un catalogo noto

## Output e artefatti

Gli artifact generati (`parquet`, `json`, `STATUS.md`) non sono versionati nel repo. Si ottengono da GitHub Actions o GCS se configurato.

- `data/radar/STATUS.md` — stato corrente delle fonti nel registry
- `data/radar/radar_summary.json` — health complessivo (GREEN/YELLOW/RED per fonte)
- `data/catalog/catalog_signals.json` — segnali drift/inventory per singola fonte
- `data/portal_scout/discovered_portals.parquet` — candidati discovery (parquet completo)
- `data/portal_scout/discovered_portals_summary.json` — sommario nuovi portali strutturati
- `data/portal_scout/portal_scout_shortlist.md` — shortlist leggibile per review umana
- `data/catalog_inventory/generated/catalog_inventory_latest.parquet` — oltre 6000 item da INPS, OpenBDAP, ISPRA, Camera e altri

I tre JSON (`radar_summary`, `catalog_signals`, `discovered_portals_summary`) sono consumati da **agent-context-builder** per includere lo stato delle fonti nel contesto operativo degli agenti AI. `radar_summary` presidia la salute di rete/HTTP; `catalog_signals` resta solo sul drift inventariale.

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
