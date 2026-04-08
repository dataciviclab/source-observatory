---
name: source-check
description: Workflow canonico del Source Observatory per verificare se una fonte pubblica regge davvero come pista del Lab e merita un passo successivo.
license: MIT
metadata:
  version: "1.0"
  owner: "DataCivicLab"
  tags: [source-observatory, source-check, scouting, datasets]
---

# Workflow: source-check

Workflow canonico del Source Observatory.
Versione: 1.0 - 2026-04-08

## Obiettivo di fase

Decidere se una fonte o un dataset pubblico merita davvero un passo successivo del Lab.

Questo workflow serve a rispondere a:

- la fonte e' davvero accessibile?
- formato, granularita' e copertura reggono?
- esiste una domanda civica plausibile?
- il caso merita un passo successivo oppure no?

Questo workflow serve a:

- verificare accesso reale e forma minima della fonte
- distinguere tra fonte viva e fonte davvero utile
- chiudere con un verdict unico e leggibile
- chiarire un perimetro v0 plausibile quando la fonte regge
- lasciare una nota locale che permetta al filone di muoversi nel funnel del Lab

Non serve a:

- aprire automaticamente issue, PR o Discussion
- fare intake in `dataset-incubator`
- fare monitoraggio continuo
- sostituire `radar-check`, `catalog-watch` o `resource-monitor`

## Quando usarlo

Usalo quando hai gia':

- una fonte nuova che sembra promettente
- una URL, pagina o dataset reale da verificare
- un sospetto ragionevole che possa reggere un filone o un support dataset

Usalo anche quando:

- `catalog-watch` o `resource-monitor` segnalano un caso che merita verifica umana
- un portale e' vivo ma non e' ancora chiaro se il dato valga davvero

Non usarlo quando:

- la fonte e' gia' stata verificata e devi solo lavorare il passo successivo
- sei gia' in intake o pipeline
- stai facendo solo un health check del portale
- il lavoro vero e' monitoraggio ricorrente e non valutazione della fonte

## Input minimi

Per partire servono almeno:

- URL, pagina o endpoint reale
- contesto minimo su che cosa dovrebbe contenere la fonte
- una ragione concreta per cui potrebbe valere la pena guardarla

## Preconditions minime

Prima di fare un source-check dovrebbe esserci almeno:

- una fonte o pagina concreta, non solo un tema generico
- un possibile uso o domanda, anche ancora grezzo
- un next step plausibile se il caso regge

Nel dubbio:

- se non hai ancora una fonte concreta, non sei in source-check ma ancora in scouting generico

## Stop rules

Fermati e non forzare source-check quando:

- hai solo un tema astratto ma non una fonte reale
- il caso appartiene ancora a `radar-check` o `catalog-watch`
- il caso e' gia' abbastanza maturo da richiedere direttamente un workflow successivo
- stai per aprire automaticamente artifact pubblici senza aver chiuso il verdetto
- la fonte e' cosi' opaca che non riesci a verificare neppure il minimo accesso reale

## Passi canonici

### 1. Parti dalla fonte reale

Usa come base:

- pagina ufficiale
- file diretto
- endpoint
- catalogo

Non partire da descrizioni di terzi se puoi verificare la fonte primaria.

### 2. Verifica l'accesso reale

Controlla con strumenti reali:

- URL o endpoint raggiungibile
- file o metadata leggibili davvero
- redirect, login, JavaScript o WAF, se presenti
- eventuale opacita' dichiarata in modo esplicito

Distinguere sempre tra:

- `verificato`
- `inferito`

Se il file non e' accessibile ma il pattern sembra plausibile, dillo chiaramente. Non fingere accesso pieno.

### 3. Verifica la shape minima del dato

Controlla almeno:

- formato
- granularita'
- copertura temporale o geografica
- una riga rappresenta cosa
- misura o struttura principale

Se il dato e' abbastanza strutturato, prova anche a estrarre:

- campi principali
- dimensioni confermate
- rischio semantico principale

### 4. Formula la domanda civica

Scrivi in una riga:

- quale domanda civica la fonte potrebbe sostenere
- perche' non e' solo descrittiva o inventariale

Se non riesci a formulare una domanda leggibile, e' spesso un segnale che il caso apre male.

### 5. Fissa un perimetro v0 plausibile

Se la fonte regge, indica:

- geografia o universo iniziale consigliato
- anni o finestra temporale iniziale
- dimensioni da tenere nel v0
- dimensioni da lasciare fuori all'inizio

Regola pratica:

- meglio un v0 piu' stretto ma difendibile che una fonte ampia con perimetro confuso

### 6. Controlla se il filone e' gia' vivo

Prima di chiudere il verdetto, verifica se esiste gia' un artefatto rilevante del Lab sullo stesso caso.

Controlla almeno se esiste gia':

- una `Discussion Datasets`
- una `Discussion Domande`
- una `Discussion Analisi`
- un candidate DI chiaramente aperto

Se il filone e' gia' vivo, non aprire un doppione concettuale.

In quel caso il verdetto tipico non e':

- `go Discussion`

ma:

- `aggiorna artefatto esistente`

### 7. Chiudi con un solo verdict

Scegli un solo verdetto finale:

- `go Discussion`
- `watchlist`
- `support dataset`
- `aggiorna artefatto esistente`
- `no-go`

Usa:

- `go Discussion` se la fonte regge davvero come pista autonoma
- `watchlist` se e' promettente ma non ancora pronta
- `support dataset` se serve soprattutto come join o supporto
- `aggiorna artefatto esistente` se il filone e' gia' vivo e il passo giusto e' aggiornare, non aprire
- `no-go` se accesso, formato o valore civico non reggono

### 8. Produci sempre una nota locale

Il source-check non e' chiuso bene se resta solo come giudizio orale o mentale.

Lascia sempre una nota locale con almeno:

- fonte e link principali
- cosa e' stato verificato davvero
- cosa e' solo inferito
- shape minima del dato
- domanda civica plausibile
- perimetro v0 consigliato, se esiste
- rischio o caveat principale
- verdetto finale
- prossimo passo

### 9. Lascia un next step esplicito

Il workflow si ferma al verdetto, ma il next step va comunque scritto in modo leggibile.

Pattern tipici:

- `go Discussion`
  - next step normale: preparare o aprire una `Discussion Datasets`
- `aggiorna artefatto esistente`
  - next step normale: aggiornare il filone gia' vivo, non aprirne uno nuovo
- `watchlist`
  - next step normale: lasciare un trigger di riapertura
- `support dataset`
  - next step normale: tenerlo come supporto, non come filone autonomo
- `no-go`
  - next step normale: fermarsi

## Errori tipici

- confondere una fonte viva con una fonte utile
- fermarsi alla home page senza verificare il file o endpoint reale
- non distinguere tra accesso verificato e accesso inferito
- formulare una domanda troppo generica
- allargare troppo presto il perimetro v0
- usare `go Discussion` per entusiasmo anche quando sarebbe meglio `watchlist`
- non controllare se il filone e' gia' vivo prima di dire `go Discussion`

## Output minimo atteso

Un source-check buono lascia:

- fonte reale verificata o limite di accesso dichiarato
- shape minima del dato
- domanda civica plausibile
- perimetro v0 iniziale, se il caso regge
- un verdict unico e leggibile
- una nota locale riusabile
- un next step esplicito

## Definition of done

Il workflow e' chiuso bene quando:

- il check non confonde fonte viva e fonte utile
- il livello di accesso e' dichiarato in modo onesto
- il verdetto finale e' unico e coerente
- esiste un next step plausibile se il verdetto e' positivo
- esiste una nota locale che permette di riprendere il caso
- non sono stati aperti automaticamente artifact pubblici o pipeline

## Stati finali ammessi

- `go Discussion`
- `watchlist`
- `support dataset`
- `aggiorna artefatto esistente`
- `no-go`

## Dove orientarsi

- [README.md](../README.md)
- [workflows/README.md](./README.md)
- [docs/usage.md](../docs/usage.md)
- [docs/architecture.md](../docs/architecture.md)
