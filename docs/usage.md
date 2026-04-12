# Radar, Catalog-Watch, Resource Monitor, Source-Check

Nota operativa breve.

Serve a chiarire quando usare:

- `source-observatory/scripts/radar_check.py`
- `catalog-watch`
- `source-observatory/scripts/resource_monitor.py`
- il workflow `source-check`

## 1. Radar

Usare `radar_check.py` quando la domanda e':

- il portale risponde?
- l'endpoint base e' vivo?
- ci sono timeout, SSL error o 404?

Esempio:
- controllo periodico dei pochi cataloghi in `source-observatory/data/radar/sources_registry.yaml`

Output:
- `source-observatory/data/radar/STATUS.md`

Non usare il radar per capire:
- se ci sono file nuovi
- se una resource specifica e' cambiata
- se un dataset merita intake

## 2. Catalog-watch

Usare `catalog-watch` quando la domanda e':

- il catalogo ha cambiato inventario?
- c'e' drift strutturale?
- emerge un segnale che merita follow-up umano?

Output:
- `source-observatory/data/catalog/CATALOG_WATCH_REPORT.md`
- `source-observatory/data/catalog/catalog_signals.json`

Non usare `catalog-watch` per:
- promuovere automaticamente candidate
- fare source-check automatici
- trattare il singolo dataset come oggetto monitorato continuo

## 3. Resource monitor

Usare `resource_monitor.py` quando la domanda e':

- su una fonte gia' nota sono comparsi file nuovi?
- una resource e' stata aggiornata, rimossa o sostituita?
- una pagina HTML o un dataset CKAN ha cambiato inventario?

Esempio:
- monitorare una pagina export del Ministero
- monitorare una fonte Tier 1 con update attesi e follow-up reale

Output:
- snapshot JSON in `source-observatory/data/monitor/snapshots/`
- report in `source-observatory/data/monitor/reports/latest.md`

Non usare il resource monitor per:
- decidere da solo il valore civico della fonte
- sostituire il source-check
- fare probing largo di portali sconosciuti
- tenere watchlist generiche o casi "interessanti ma senza next step"

## 4. Source-check

Usare `source-check` quando la domanda e':

- questa fonte e' un candidato serio per il Lab?
- accesso, formato e granularita' reggono davvero?
- merita `go Discussion`, `watchlist`, `support dataset` o `scarto`?

Output tipico:
- checklist o nota verificata
- verdict chiaro

Il source-check e' il passaggio giusto quando:
- una fonte nuova sembra promettente
- il radar segnala una fonte viva ma non sai se vale qualcosa
- il resource monitor trova un file nuovo e vuoi capire se cambia davvero il quadro

Nel repo, il workflow pubblico/light sta in:

- `source-observatory/workflows/source-check.md`

## Regola pratica

- `radar_check.py` = health check del portale
- `catalog-watch` = segnali su inventario e drift di pochi cataloghi ricchi
- `resource_monitor.py` = change detection su file e resources
- `source-check` = valutazione reale della fonte o del dataset

Ordine tipico:

1. radar
2. catalog-watch sui cataloghi scelti
3. resource monitor, solo per pochi casi Tier 1
4. source-check, quando emerge una pista concreta

## Comandi minimi

```powershell
python source-observatory/scripts/radar_check.py
python source-observatory/scripts/resource_monitor.py
```

Il source-check non e' uno script solo: segue il workflow e chiude con un verdetto.

## Universe v0

Per ora la v0 resta concentrata su:

- `istat_sdmx`
- `anac`
- `inps`

La regola pratica e' semplice:

- meglio 3 cataloghi ricchi e leggibili
- peggio 12 fonti eterogenee con poco segnale
