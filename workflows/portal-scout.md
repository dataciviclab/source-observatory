---
name: portal-scout
description: Workflow pubblico/light del Source Observatory per capire se un portale dati o una superficie web può entrare nel funnel del repo come catalog-watch, radar-only o sorgente da verificare item per item.
license: MIT
metadata:
  version: "0.1"
  owner: "DataCivicLab"
  tags: [source-observatory, portal-scout, scouting, workflows]
---

# Workflow: portal-scout

Workflow pubblico/light del Source Observatory.
Versione: 0.1 - 2026-04-10

---

## Obiettivo di fase

Capire che tipo di superficie è un portale e quale metodo di osservazione ha senso nel repo.

Questo workflow serve a rispondere a:

- è davvero un catalogo o solo un contenitore di file?
- esiste una superficie osservabile stabile?
- il portale è inventariabile oppure no?
- conviene trattarlo come `catalog-watch`, `radar-only` o solo come ingresso a futuri `source-check`?

Non serve a:

- verificare in profondita' un singolo dataset
- costruire subito un inventory completo
- fare monitoraggio continuo
- sostituire `source-check` o `catalog-watch`

## Output minimo atteso

Una nota o checklist verificata che chiuda con un solo verdetto:

- `portale pronto per catalog-watch`
- `portale da tenere radar-only`
- `portale utile solo per source-check item-based`
- `superficie non abbastanza chiara`

## Quando usarlo

- un portale nuovo entra nel radar del repo
- una landing dati sembra catalogo ma la superficie reale non è ancora chiara
- una fonte sembra promettente ma non è chiaramente CKAN, SDMX o altra famiglia già nota
- serve una classificazione prima di aggiornare `sources_registry.yaml`

Non usarlo quando:

- devi verificare una singola fonte o file: in quel caso usare `source-check`
- hai già un inventory leggibile e devi shortlistare item: in quel caso lavorare sull'inventory
- il portale è già in `catalog-watch` e stai solo leggendo segnali o delta
- devi seguire nel tempo una singola resource Tier 1

## Workflow minimo

### 1. Inquadra la superficie

Annotare almeno:

- nome del portale
- URL base
- istituzione o publisher apparente
- dominio e sottodominio rilevanti
- eventuali superfici secondarie osservate

### 2. Identifica il tipo di portale

Provare a classificare la superficie come una di queste:

- `ckan`
- `sdmx`
- `html` con sitemap o listing stabile
- `aem` o CMS con Open API
- `sparql`
- `custom`
- `non chiaro`

Se il protocollo non è chiaro, annotare cosa è stato osservato senza forzare la classificazione.

### 3. Individua la superficie osservabile reale

Capire qual è il punto giusto da osservare, per esempio:

- action API
- endpoint dataflow
- sitemap
- listing HTML
- Open API
- endpoint SPARQL

Separare sempre:

- home o branding del portale
- superficie tecnica reale usabile per osservazione

### 4. Valuta l'inventariabilità

Chiedersi in modo esplicito:

- si possono enumerare gli item?
- il metodo è riproducibile?
- il conteggio è difendibile?
- la superficie è stabile abbastanza per una baseline?

Classificare l'esito come:

- `inventariabile`
- `parzialmente inventariabile`
- `osservabile ma non inventariabile`
- `non chiaro`

### 5. Controllo leggero di overlap

Verificare in modo leggero se il portale o il tema sono già presenti in:

- `sources_registry.yaml`
- workflow o note del repo già esistenti
- filoni o candidate già chiaramente collegati

Non serve un audit completo. Serve evitare di trattare come nuovo un portale già capito o già classificato.

### 6. Chiudi con un verdetto

Chiudere con uno di questi esiti:

- `portale pronto per catalog-watch`
- `portale da tenere radar-only`
- `portale utile solo per source-check item-based`
- `superficie non abbastanza chiara`

Il verdetto deve dire anche:

- metodo osservabile più plausibile
- limite principale
- next step minimo

## Regole

- non forzare `catalog-watch` senza metodo inventariale chiaro
- non trattare come catalogo qualcosa che regge solo item per item
- non costruire inventory completi troppo presto
- non confondere sito istituzionale e superficie tecnica utile
- meglio `radar-only` esplicito che classificazione debole

## Come si collega al resto del repo

- `portal-scout` classifica il portale e decide il metodo plausibile
- `catalog-watch` osserva un catalogo con metodo stabile
- `source-check` verifica una fonte specifica o un item promettente

## Prossimo passo tipico

Se il verdetto è positivo:

- aggiornare o proporre aggiornamento di `sources_registry.yaml`
- oppure passare a `source-check` su item specifici
- oppure lasciare il portale in `radar-only` fino a metodo migliore
