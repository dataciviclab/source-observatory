# Dati Catalogo

Segnali di inventario e drift per il Source Observatory.

## Contenuto

- `catalog_signals.json` — segnali di inventory-change / structural-drift / csv_magnet per fonte.
  Generato dalla CI ogni lunedì. Consumato da agent-context-builder.

## Perimetro

Segnali di conteggio package, dataflow, drift strutturale.
Non include salute del portale (radar) né monitoraggio file-level.

## Accesso via MCP

- `so_source_report(<source_id>)` — report completo per fonte (include segnali)
- `so_dashboard()` — KPI riassuntivi di tutte le fonti
- `so_catalog_signals` — solo i segnali raw (legacy)

Per segnali di inventario e drift, preferire `so_source_report` che li include insieme a health e source-check.
