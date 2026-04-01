---
name: source-check
description: Workflow pubblico/light del Source Observatory per verificare se una fonte pubblica regge davvero come pista del Lab. Usare quando serve distinguere una fonte viva da una fonte che merita davvero un passo successivo.
license: MIT
metadata:
  version: "0.1"
  owner: "DataCivicLab"
  tags: [source-observatory, source-check, scouting, datasets]
---

# Workflow: source-check

Workflow pubblico/light del Source Observatory.
Versione: 0.1 - 2026-04-01

---

## Obiettivo di fase

Decidere se una fonte o un dataset pubblico merita un passo successivo del Lab.

Questo workflow serve a rispondere a:

- la fonte e' davvero accessibile?
- formato e granularita' reggono?
- la domanda civica e' plausibile?
- conviene consolidare il caso oppure no?

Non serve a:

- aprire automaticamente issue, PR o discussion
- fare intake in `dataset-incubator`
- fare monitoraggio continuo
- sostituire `radar-check`, `catalog-watch` o `resource-monitor`

## Output minimo atteso

Una nota o checklist verificata che chiuda con un solo verdict:

- `go Discussion`
- `watchlist`
- `support dataset`
- `aggiorna artefatto esistente`
- `no-go`

## Quando usarla

Usarla quando:

- una fonte nuova sembra promettente
- un file o catalogo sembra vivo ma non e' ancora chiaro se valga davvero
- un update osservato da `catalog-watch` o `resource-monitor` merita verifica umana

Non usarla quando:

- la fonte e' gia stata verificata e devi solo lavorare il passo successivo
- sei gia in intake o pipeline
- stai facendo solo un health check del portale

## Workflow minimo

### 1. Verifica l'accesso reale

Controllare con strumenti reali:

- URL o endpoint raggiungibile
- file o metadata davvero leggibili
- eventuale opacita' dichiarata esplicitamente

Distinguere sempre tra:

- verificato
- inferito

### 2. Verifica la shape minima

Controllare almeno:

- formato plausibile
- granularita' utile
- copertura temporale o geografica
- presenza di una misura o struttura leggibile

Se la fonte e' strutturata, estrarre anche:

- indicatore o misura principale
- dimensioni confermate
- rischio semantico principale

### 3. Formula la domanda civica

Scrivere in una riga:

- quale domanda civica permette di sostenere
- perche' non e' solo descrittiva

### 4. Fissa un perimetro v0 plausibile

Se la fonte lo consente, indicare:

- geografia o universo iniziale consigliato
- anni o finestra temporale iniziale
- dimensioni da tenere nel v0
- dimensioni da lasciare fuori all'inizio

### 5. Chiudi con un verdict

Scegliere un solo verdetto:

- `go Discussion` se la fonte regge davvero
- `watchlist` se e' promettente ma non ancora pronta
- `support dataset` se serve soprattutto come join o supporto
- `aggiorna artefatto esistente` se il filone e' gia vivo
- `no-go` se accesso, formato o valore civico non reggono

## Regole

- meglio `watchlist` chiaro che `go Discussion` debole
- non forzare il funnel completo dentro questo workflow
- non duplicare un artefatto pubblico gia esistente
- non confondere fonte viva con fonte utile

## Come si collega al resto del repo

- `radar-check` dice se la fonte e' viva
- `catalog-watch` dice se un catalogo segnala qualcosa di nuovo
- `resource-monitor` dice se una resource Tier 1 e' cambiata
- `source-check` decide se il caso regge davvero come pista del Lab

## Prossimo passo tipico

Se il verdetto e' positivo:

- consolidare il caso in un artefatto pubblico del Lab
- oppure preparare il passaggio verso il workflow di intake tecnico

Il passaggio esatto dipende dal repo e dal contesto del filone.
