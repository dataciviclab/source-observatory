---
name: catalog-watch
description: Workflow canonico del Source Observatory per osservare pochi cataloghi in modalita catalog-watch e produrre un report locale di intelligence senza aprire issue o avviare pipeline.
license: MIT
metadata:
  version: "1.5"
  owner: "DataCivicLab"
  tags: [source-observatory, catalog-watch, monitoring, scouting]
---

# Workflow: catalog-watch

Workflow canonico di `source-observatory`.
Versione: 1.5 - 2026-04-10

## Obiettivo di fase

Controllare i pochi cataloghi classificati come `catalog-watch` nel registry e capire se:

- l'inventario e cambiato
- la struttura del catalogo e cambiata
- esiste un segnale che merita un follow-up umano

Questo workflow serve a:

- osservare l'inventario del catalogo
- confrontare lo stato attuale con una baseline dichiarata
- produrre un report di intelligence leggibile
- suggerire, ma non eseguire, il next step umano

Non serve a:

- fare `source-check` automatici
- aprire issue o PR
- avviare pipeline o candidate
- monitorare ogni dataset o file singolarmente

## Quando usarlo

Usarlo quando hai gia:

- fonti classificate come `catalog-watch` nel registry
- una baseline inventariale o qualitativa dichiarata
- una domanda del tipo:
  - questo catalogo ha esposto qualcosa di nuovo o strutturalmente rilevante?

Non usarlo quando:

- la domanda vera e solo "la fonte e viva?"
- il caso richiede un `source-check` puntuale su una fonte o dataset specifico
- il caso e un monitor file-level o resource-level
- la baseline non e abbastanza comparabile da sostenere un confronto serio

## Preconditions minime

Per partire servono almeno:

- registry `data/radar/sources_registry.yaml`
- fonti con `observation_mode: catalog-watch`
- `protocol`, `base_url` e `catalog_baseline` leggibili
- output canonici confermati:
  - `data/catalog/CATALOG_WATCH_REPORT.md`
  - `data/catalog/catalog_signals.json`

Nel dubbio:

- se il metodo attuale non e comparabile con la baseline, meglio `[DATO MANCANTE]` che una conclusione forzata

## Stop rules

Fermarsi quando:

- il protocollo reale non e chiaro
- l'endpoint non restituisce dati comparabili con la baseline
- il delta osservato dipende chiaramente da un mismatch di metodo
- il catalogo e troppo fragile per distinguere tra `health` e `inventory change`
- stai per trasformare un segnale grezzo in decisione automatica

## Passi canonici

### 1. Leggi il registry

Leggere `data/radar/sources_registry.yaml`.

Filtrare solo le fonti con:

- `observation_mode: catalog-watch`

Per ciascuna annotare almeno:

- `protocol`
- `base_url`
- `last_probed`
- `datasets_in_use`
- `catalog_baseline.metric`
- `catalog_baseline.value`
- `catalog_baseline.method`
- `catalog_baseline.reliability`

### 2. Controlla ciascuna fonte col metodo giusto

Per ogni fonte, eseguire il check coerente col protocollo.

Per `sdmx`:

- chiamare il listing dei dataflow
- contare i dataflow totali
- verificare se i dataflow correlati a `datasets_in_use` sono ancora presenti
- se la baseline usa `dataflow_count`, confrontare il conteggio con il valore atteso

Per `ckan`:

- usare l'endpoint dichiarato nel registry
- identificare il metodo di conteggio dichiarato nella baseline
- confrontare il totale solo se il metodo osservato coincide con quello dichiarato
- verificare, se presenti, i package correlati a `datasets_in_use`

Regola:

- se `package_list` e `package_search` descrivono universi diversi, trattare il caso come mismatch di metodo, non come `inventory change`

Per `rest_json`:

- verificare disponibilita e struttura di massima
- segnalare cambi di schema o endpoint irraggiungibili

Per `xlsx_direct` o `html`:

- verificare raggiungibilita
- controllare se la struttura dei link di download e cambiata
- usare confronti qualitativi se la baseline e qualitativa

### 3. Classifica il segnale primario

Per ogni fonte e per ogni run, usare un solo segnale primario:

- `no signal`
- `health`
- `inventory change`
- `structural drift`
- `follow-up candidate`
- `[DATO MANCANTE]`

Regole:

- `follow-up candidate` e un suggerimento di follow-up umano, non un automatismo
- se il metodo osservato non e comparabile con la baseline, preferire `[DATO MANCANTE]`
- se il problema e soprattutto di raggiungibilita o affidabilita, preferire `health`

### 4. Produci il report

Scrivere il report in:

- `data/catalog/CATALOG_WATCH_REPORT.md`

Per ogni fonte, il report deve lasciare almeno:

- fonte controllata
- protocollo usato
- baseline rilevante
- osservazione principale
- segnale primario
- suggerimento di next step umano, se esiste

### 5. Aggiorna il registry

Per ogni fonte controllata, aggiornare:

- `last_probed`

Non modificare:

- `catalog_baseline`
- `method`
- `reliability`

senza istruzione esplicita.

## Errori tipici

- confrontare numeri prodotti da metodi diversi
- trattare un endpoint rotto come `inventory change`
- scambiare un problema di health per un segnale di catalogo
- aprire follow-up automatici senza verifica umana
- aggiornare la baseline implicitamente durante il run

## Output minimo atteso

Un run buono di `catalog-watch` lascia:

- tutte le fonti `catalog-watch` controllate con tool reali
- `CATALOG_WATCH_REPORT.md` aggiornato
- `catalog_signals.json` aggiornato
- `last_probed` aggiornato nel registry
- un segnale primario per fonte
- un next step umano suggerito, se serve

## Definition of done

Il workflow e chiuso bene quando:

- tutte le fonti `catalog-watch` del registry sono state controllate
- il report e aggiornato
- nessun delta numerico e stato forzato senza comparabilita di metodo
- non sono state aperte issue, source-check o pipeline in automatico
- il maintainer puo leggere il report e capire subito se esiste un follow-up umano plausibile

## Stati finali ammessi

- `no signal`
- `health`
- `inventory change`
- `structural drift`
- `follow-up candidate`
- `[DATO MANCANTE]`

## Dove orientarsi

- [README.md](../README.md)
- [workflows/README.md](./README.md)
- [docs/architecture.md](../docs/architecture.md)
- [docs/runbook.md](../docs/runbook.md)
