---
name: resource-monitor
description: Workflow canonico del Source Observatory per monitorare un insieme ristretto di risorse note e suggerire un next step umano.
license: MIT
metadata:
  version: "1.3"
  owner: "DataCivicLab"
  tags: [source-observatory, resource-monitor, monitoring, follow-up]
---

# Workflow: resource-monitor

Workflow canonico di `source-observatory`.
Versione: 1.3 - 2026-04-10

Nota di stato:

- `resource-monitor` e congelato come utility legacy su poche fonti gia presenti
- non e il punto di ingresso per nuove fonti o nuovi candidate
- i futuri source ping orientati al dataset vivranno preferibilmente in `dataset-incubator`, vicino al candidate

## Obiettivo di fase

Rilevare cambi su un insieme molto ristretto di fonti note e capire se il segnale osservato richiede davvero un next step umano sul dataset.

Questo workflow serve a:

- leggere i segnali del monitor su pochi casi ad alto valore
- distinguere tra cambio utile e rumore
- suggerire un next step umano plausibile

Non serve a:

- aprire issue o rilanciare candidate
- fare `source-check` autonomamente
- diventare watchlist generica di dataset
- sostituire `catalog-watch` o `source-check`

## Quando usarlo

Usarlo quando:

- la fonte e gia importante per il Lab
- esiste un next step plausibile se il segnale cambia
- il monitor costa meno di uno scouting umano ripetuto
- la fonte e gia una delle poche monitorate, non un nuovo ingresso nel funnel

Non usarlo quando:

- la fonte e ancora solo interessante ma non ancora centrale
- il caso e meglio descritto da `radar-check`
- il caso e meglio descritto da `catalog-watch`
- il monitor non porta quasi mai a decisioni utili
- stai valutando se aggiungere una nuova fonte

## Preconditions minime

Per partire servono:

- config fonti:
  - `source-observatory/scripts/monitor/resource_monitor.sources.yml`
  - oppure `resource_monitor.sources.yml.example` come riferimento
- script:
  - `source-observatory/scripts/monitor/resource_monitor.py`
- output atteso:
  - `source-observatory/data/monitor/reports/latest.md`
- una fonte Tier 1 o equivalente, gia giustificata
- un adapter abbastanza chiaro
- un next step plausibile se compare un vero segnale

Nel dubbio:

- se non riesci a spiegare quale decisione concreta potrebbe seguire al segnale, la fonte probabilmente non dovrebbe stare nel monitor

## Stop rules

Fermarsi quando:

- il segnale e chiaramente infrastrutturale e appartiene a `radar-check`
- il cambio osservato dipende da rumore HTML o da fragilita dell'adapter
- non esiste un next step difendibile anche se il segnale fosse vero
- stai per trattare un `changed` come rerun automatico senza leggere il tipo di cambio
- stai per usare `resource-monitor` come canale per nuove fonti

## Passi canonici

### 1. Verifica il perimetro del monitor

Prima del run, chiediti:

- questa fonte e davvero un caso da monitor ristretto?
- esiste un next step plausibile se il segnale cambia?

Se la risposta e no, il problema puo essere nel perimetro del monitor, non nel dataset.

### 2. Esegui il monitor

Dalla root del workspace:

```powershell
python source-observatory/scripts/monitor/resource_monitor.py --sources source-observatory/scripts/monitor/resource_monitor.sources.yml
```

### 3. Leggi `latest.md`

Leggere `source-observatory/data/monitor/reports/latest.md`.

Classificare ogni segnale in una di queste classi:

| Tipo | Significato |
|---|---|
| `new` | risorsa comparsa per la prima volta |
| `changed` | URL, nome, formato o metadati modificati |
| `removed` | risorsa presente in precedenza non piu visibile |
| `error` | problema di adapter o di portale |

### 4. Valuta l'affidabilita dell'adapter

Regola pratica:

- `single_url` o `ckan` = segnale piu affidabile
- `html` = piu sospetto, aspettati piu falsi positivi

Se il segnale viene da un adapter fragile:

- alza il livello di cautela
- non saltare subito a conclusioni sul dataset

### 5. Classifica il next step umano

Per ogni segnale non nullo, usa questa logica:

| Condizione | Next step |
|---|---|
| `di_candidate` attivo con config runnable | ispeziona candidate, poi valuta rerun |
| dataset stabile pubblico | verifica se serve update pubblico |
| watchlist o support dataset | `source-check`, non rerun |
| errore SSL/DNS/timeout | problema da radar, non da dataset |
| nessun next step difendibile | proporre demotion o rimozione dal monitor |

### 6. Produci la sintesi

La sintesi deve lasciare:

- conteggio segnali per tipo
- per ogni segnale rilevante:
  - fonte
  - tipo
  - affidabilita dell'adapter
  - azione suggerita
- fonti senza segnale:
  - `ok, nessuna azione`

## Errori tipici

- trattare `changed` come rerun automatico
- scambiare rumore HTML per cambio vero
- leggere `error` infrastrutturali come problema del dataset
- tenere nel monitor fonti che quasi non producono mai decisioni utili
- allargare il monitor a nuove fonti solo per entusiasmo

## Output minimo atteso

Un run buono di `resource-monitor` lascia:

- `latest.md` aggiornato
- segnali classificati per tipo
- azione suggerita per ogni segnale rilevante
- nessuna decisione automatica presa al posto del maintainer

## Definition of done

Il workflow e chiuso bene quando:

- il report e aggiornato e leggibile
- ogni segnale rilevante ha un next step umano plausibile
- i segnali infrastrutturali non sono stati scambiati per cambi del dataset
- non sono state aperte issue o rilanciati candidate automaticamente
- se il monitor sembra inutile su una fonte, questo emerge chiaramente nella sintesi

## Stati finali ammessi

- `new`
- `changed`
- `removed`
- `error`

## Dove orientarsi

- [README.md](../README.md)
- [workflows/README.md](./README.md)
- [docs/runbook.md](../docs/runbook.md)
- [docs/architecture.md](../docs/architecture.md)
