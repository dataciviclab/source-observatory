# Dati Catalogo

Stato canonico per l'osservazione a livello catalogo nel Source Observatory.

## Struttura

- `CATALOG_WATCH_REPORT.md`
  - rendering leggibile del report catalogo, generato dalla CI ogni lunedì via `scripts/build_catalog_signals.py`
- `catalog_signals.json`
  - output strutturato (stesso script che genera anche il `.md`); contiene segnali drill/down/inventory-change per singola fonte
  - consumato da agent-context-builder per il context operativo

## Perimetro

Quest'area serve per intelligence su cataloghi e inventari:

- conteggi package
- conteggi dataflow
- drift strutturale
- segnali di follow-up

Nel report `CATALOG_WATCH_REPORT.md` vanno esplicitate anche le fonti con
`observation_mode: catalog-watch` non inventariabili dal builder corrente (es. protocollo non supportato).

Non e' il posto per:

- salute del portale
- monitoraggio file-level
- decisioni di source-check

La salute di connettivita' e HTTP vive in `data/radar/radar_summary.json`; qui restano solo segnali legati a inventario e drift.

## Accesso via MCP

I tool MCP SO forniscono accesso programmatico a questi artifact:
- `so_catalog_signals` — legge `catalog_signals.json` (segnali drill/down/stable per fonte)
- `so_source_check(include_diff=True)` — legge stato build inventory per fonte (ok/error/protocol_not_supported)

GCS latest: `gs://dataciviclab-clean/catalog/catalog_signals.json`
