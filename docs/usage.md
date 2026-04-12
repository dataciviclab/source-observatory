# Radar, Catalog-Watch, Resource Monitor, Source-Check

Nota operativa breve.

Serve a chiarire quando usare:

- `scripts/radar_check.py`
- `catalog-watch`
- il workflow `source-check`

## 1. Radar

Usare `radar_check.py` quando la domanda è:

- il portale risponde?
- l'endpoint base è vivo?
- ci sono timeout, SSL error o 404?

Esempio:
- controllo periodico dei pochi cataloghi in `data/radar/sources_registry.yaml`

Output:
- `data/radar/STATUS.md`

Non usare il radar per capire:
- se ci sono file nuovi
- se una resource specifica è cambiata
- se un dataset merita intake

## 2. Catalog-watch

Usare `catalog-watch` quando la domanda è:

- il catalogo ha cambiato inventario?
- c'è drift strutturale?
- emerge un segnale che merita follow-up umano?

Output:
- `data/catalog/CATALOG_WATCH_REPORT.md`
- `data/catalog/catalog_signals.json`

Non usare `catalog-watch` per:
- promuovere automaticamente candidate
- fare source-check automatici
- trattare il singolo dataset come oggetto monitorato continuo

## 3. Source-check

Usare `source-check` quando la domanda è:

- questa fonte è un candidato serio per il Lab?
- accesso, formato e granularità reggono davvero?
- merita `go Discussion`, `watchlist`, `support dataset` o `scarto`?

Output tipico:
- checklist o nota verificata
- verdict chiaro

Il source-check è il passaggio giusto quando:
- una fonte nuova sembra promettente
- il radar segnala una fonte viva ma non sai se vale qualcosa

Nel repo, il workflow pubblico/light sta in:

- `workflows/source-check.md`

## Regola pratica

- `radar_check.py` = health check del portale
- `catalog-watch` = segnali su inventario e drift di pochi cataloghi ricchi
- `source-check` = valutazione reale della fonte o del dataset

Ordine tipico:

1. radar
2. catalog-watch sui cataloghi scelti
3. source-check, quando emerge una pista concreta

## Comandi minimi

```bash
python scripts/radar_check.py
```

Il source-check non è uno script solo: segue il workflow e chiude con un verdetto.
