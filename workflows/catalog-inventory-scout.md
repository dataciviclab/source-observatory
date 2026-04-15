---
name: catalog-inventory-scout
description: Triage di un catalog inventory per ricavare una shortlist di segnali da mandare a source-check, catalog-watch o watchlist.
license: MIT
metadata:
  version: "1.0"
  owner: "DataCivicLab"
  tags: [source-observatory, scouting, triage, inventory]
---

# Workflow: catalog-inventory-scout

Workflow canonico di `source-observatory` per fare scouting disciplinato a partire da un catalog inventory.
Versione: 1.0 - 2026-04-15

## Obiettivo di fase

Partire da un inventory di catalogo (generato da `scripts/build_catalog_inventory.py`) e produrre una shortlist di elementi promettenti, rumorosi o trascurabili senza fare ancora un `source-check` completo.

Questo workflow serve a chiudere il gap tra un inventory ampio/rumoroso e i workflow successivi di approfondimento.

## Quando usarlo

Usalo quando hai già uno di questi input:
- `data/catalog_inventory/generated/*.parquet` (generato dalla CI o manualmente)
- lista di dataset o risorse di un portale estratta via `portal-scout`

Usalo soprattutto se devi capire rapidamente cosa vale la pena approfondire e cosa ignorare senza perdere tempo.

## Non usarlo quando

- Devi verificare davvero una singola fonte: in quel caso fai [source-check.md](./source-check.md).
- Devi confrontare un portale con una baseline per vedere cambiamenti strutturali: in quel caso fai [catalog-watch.md](./catalog-watch.md).
- L'inventory non è leggibile o non hai abbastanza metadati minimi per triagiarlo.

## Preconditions minime

- Inventory leggibile o lista di item del catalogo.
- Almeno alcuni metadati utili per item (titolo, URL, formato, organizzazione, data update).
- Se i metadati sono troppo poveri per distinguere gli item, fermati e dichiaralo.

## Passi canonici

### 1. Inquadra l'inventory
Identifica il catalogo, la data dell'inventory e la dimensione della lista.

### 2. Definisci il criterio di triage
Dichiara cosa stai cercando (es. nuovi dataset su un tema specifico, aggiornamenti rilevanti, risorse candidate per il Lab).

### 3. Classifica gli item
Per ogni item interessante, assegna una classe semplice:
- `source-check`: item pronto per la verifica profonda.
- `watchlist`: interessante ma non prioritario.
- `ignore`: rumore o fuori scopo.

### 4. Costruisci la shortlist
Mantieni una lista corta e leggibile. Per ogni item annota titolo, URL e motivazione.
Controlla brevemente se l'item è già coperto da filoni vivi in `dataset-incubator` o discussioni aperte.

### 5. Apri l'issue di scout
Usa il template [Catalog inventory scout](../.github/ISSUE_TEMPLATE/catalog-inventory-scout.yml) per documentare il risultato del triage.

## Boundary con altri workflow

- `catalog-inventory-scout` -> prepara il terreno via triage di una lista.
- [source-check.md](./source-check.md) -> verifica una fonte specifica.
- [catalog-watch.md](./catalog-watch.md) -> osserva un portale in modalità differenziale.

## Output atteso

- Issue di tipo `catalog-scout` con shortlist ragionata.
- Decisione sui passi successivi per gli item in shortlist.
