---
name: radar-check
description: Workflow canonico del Source Observatory per controllare la salute infrastrutturale delle fonti nel registry.
license: MIT
metadata:
  version: "1.2"
  owner: "DataCivicLab"
  tags: [source-observatory, radar-check, health, monitoring]
---

# Workflow: radar-check

Workflow canonico di `source-observatory`.
Versione: 1.2 - 2026-04-10

## Obiettivo di fase

Verificare la raggiungibilita e la salute infrastrutturale delle fonti nel registry.

Questo workflow serve a:

- capire se una fonte e viva
- rilevare errori SSL, DNS, timeout o risposta anomala
- produrre una sintesi infrastrutturale leggibile

Non serve a:

- capire se un dataset e aggiornato
- leggere il catalogo
- decidere il valore civico della fonte
- aprire follow-up automatici

## Quando usarlo

Usarlo quando hai gia:

- `sources_registry.yaml` aggiornato
- script `scripts/radar_check.py`
- bisogno di un check rapido sulla salute delle fonti

Non usarlo quando:

- devi verificare una fonte specifica o un file
- devi leggere delta di catalogo
- devi interpretare un segnale a livello dataset

## Preconditions minime

Per partire servono:

- registry leggibile
- script radar eseguibile
- output atteso chiaro: `data/radar/STATUS.md`
- fonti con `base_url` plausibile

Nel dubbio:

- se la domanda vera non e "questa fonte e viva?", probabilmente non sei nel workflow giusto

## Stop rules

Fermarsi se:

- stai per interpretare un problema infrastrutturale come update di contenuto
- il caso appartiene a `catalog-watch` o `source-check`
- il run produce solo rumore da una fonte gia nota come fragile
- stai per modificare il registry a mano invece di limitarti a leggere il risultato del run

## Passi canonici

### 1. Leggi il registry

Leggere `data/radar/sources_registry.yaml` per avere il contesto delle fonti prima del run:

- fonte
- `protocol`
- `verdict`
- `observation_mode`

### 2. Esegui il radar

Dalla root del repo:

```bash
python scripts/radar_check.py
```

Per un dry-run:

```bash
python scripts/radar_check.py --dry-run
```

### 3. Leggi `STATUS.md`

Leggere `data/radar/STATUS.md` e classificare ogni fonte in uno di questi stati:

- `ok`
- `warning infrastrutturale`
- `da osservare`

### 4. Produci la sintesi

Produrre una sintesi breve con:

- conteggio per classificazione
- fonti con warning o problemi ripetuti
- eventuali fonti `go` che ora mostrano problemi infrastrutturali

## Errori tipici

- confondere salute del portale con update del dataset
- promuovere un warning a decisione di workflow successivo
- trattare un falso negativo noto come rottura reale
- usare il radar per decidere da solo un source-check

## Output minimo atteso

Alla fine devono esistere:

- `STATUS.md` aggiornato dallo script oppure un dry-run leggibile
- sintesi leggibile del run
- eventuali fonti problematiche chiaramente evidenziate

## Definition of done

Il workflow e chiuso bene quando:

- il radar e stato eseguito o simulato in modo esplicito
- `STATUS.md` e leggibile
- i problemi infrastrutturali sono distinti dai problemi di contenuto
- il registry non e stato modificato manualmente
- non sono stati aperti altri artefatti o workflow

## Stati finali ammessi

- `ok`
- `warning infrastrutturale`
- `da osservare`

## Dove orientarsi

- [README.md](../README.md)
- [docs/runbook.md](../docs/runbook.md)
- [data/radar/README.md](../data/radar/README.md)
