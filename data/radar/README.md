# Dati Radar

Stato canonico dei controlli radar a livello portale.

## File

- `sources_registry.yaml`
  - registry di input per `scripts/radar_check.py`
  - una entry per portale
- `STATUS.md`
  - ultimo output leggibile del probe radar
- `radar_summary.json`
  - summary compatto generato da `scripts/radar_check.py`, consumabile da agent-context-builder (ACB)
  - contiene: timestamp, conteggi status (GREEN/YELLOW/RED), lista fonti con status e metadati essenziali

## Perimetro

Questa area serve solo per la salute del portale:

- raggiungibilita'
- stato HTTP
- note su timeout / SSL / DNS

Non e' un inventario di resource e non decide se una fonte merita un candidate.

## Strumenti collegati

- script: `scripts/radar_check.py`
- runbook: `docs/runbook.md`
- nota architetturale: `docs/architecture.md`
