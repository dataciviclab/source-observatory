# Dati Radar

Stato canonico dei controlli radar a livello portale.

## File

- `sources_registry.yaml`
  - registry di input per `source-observatory/scripts/radar_check.py`
  - una entry per portale
- `STATUS.md`
  - ultimo output leggibile del probe radar

## Perimetro

Questa area serve solo per la salute del portale:

- raggiungibilita'
- stato HTTP
- note su timeout / SSL / DNS

Non e' un inventario di resource e non decide se una fonte merita un candidate.

## Strumenti collegati

- script: `source-observatory/scripts/radar_check.py`
- nota d'uso: `source-observatory/docs/usage.md`
- nota architetturale: `source-observatory/docs/architecture.md`
