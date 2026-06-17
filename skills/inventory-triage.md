---
name: inventory-triage
description: Triage di un catalog inventory per ricavare shortlist di item da verificare con source-check e aprire issue in SO.
license: MIT
metadata:
  version: "1.0"
  owner: "DataCivicLab"
  tags: [source-observatory, scouting, triage, inventory]
---

# Workflow: inventory-triage

Workflow canonico di `source-observatory` per fare triage disciplinato a partire da un catalog inventory.
Versione: 1.0 - 2026-04-15

## Obiettivo di fase

Partire da un inventory di catalogo (generato da `scripts/build_catalog_inventory.py`) e produrre una shortlist di elementi promettenti, rumorosi o trascurabili senza fare ancora un `source-check` completo.

Questo workflow serve a chiudere il gap tra un inventory ampio/rumoroso e i workflow successivi di approfondimento.

## Quando usarlo

Usalo quando hai già uno di questi input:
- `data/catalog_inventory/generated/*.parquet` (generato dalla CI o manualmente)
- Accesso al layer MCP SO (per consultare artifact senza scaricare file)

Usalo soprattutto se devi capire rapidamente cosa vale la pena approfondire e cosa ignorare senza perdere tempo.

## Non usarlo quando

- Devi verificare davvero una singola fonte: in quel caso fai [source-check.md](./source-check.md).
- Devi vedere se il catalogo ha cambiato inventario o struttura: leggi `data/catalog/CATALOG_WATCH_REPORT.md` (prodotto dalla CI ogni lunedì) oppure usa `so_catalog_signals` via MCP.
- L'inventory non è leggibile o non hai abbastanza metadati minimi per triagiarlo.

## Pre-check MCP (prima di aprire il parquet)

Prima di toccare l'inventory parquet, consulta gli artifact SO via MCP per orientarti:

```
1. so_catalog_inventory_search(query)  → cerca nell'inventory se la fonte esiste già
2. so_inventory_status             → stato build inventory: ok/error/protocol_not_supported
3. so_catalog_signals(limit=5)     → segnali di drift per fonte
4. so_radar_summary               → stato radar delle fonti monitorate
```

**Alternativa compatta**: se conosci già lo `source_id`, puoi usare
`so_source_overview(<source_id>)` che combina inventory_status + signals +
radar_summary + registry in una chiamata sola.

**Se `so_inventory_status` mostra error per una fonte**: l'inventory di quella fonte è inaffidabile — salta il triage per quella fonte o interpreta i risultati con cautela.

**Se `so_catalog_signals` mostra `no signal`**: il catalogo è stabile, nessun bisogno urgente di re-inventory.

## Preconditions minime

- Inventory leggibile o lista di item del catalogo.
- Almeno alcuni metadati utili per item (titolo, URL, formato, organizzazione, data update).
- Se i metadati sono troppo poveri per distinguere gli item, fermati e dichiaralo.

## Passi canonici

### 1. Inquadra l'inventory
Identifica il catalogo, la data dell'inventory e la dimensione della lista.
Se hai già consultato `so_inventory_status` e `so_catalog_signals`, integra qui il risultato.

### 2. Definisci il criterio di triage
Dichiara cosa stai cercando (es. nuovi dataset su un tema specifico, aggiornamenti rilevanti, risorse candidate per il Lab).

### 3. Classifica gli item
Per ogni item interessante, assegna una classe semplice:
- `go intake`: item promettente, merita un source-check.
- `watchlist`: interessante ma non prioritario.
- `ignore`: rumore o fuori scopo.

### 4. Costruisci la shortlist
Mantieni una lista corta e leggibile. Per ogni item annota titolo, URL e motivazione.
Controlla brevemente se l'item è già coperto da filoni vivi in `dataset-incubator` o discussioni aperte.

### 5. Apri issue in SO per source-check

Usa il template [Inventory triage](../.github/ISSUE_TEMPLATE/inventory-triage.yml) per documentare il risultato del triage.

Per ogni item classificato `go intake`, il prossimo passo è eseguire un
[source-check](./source-check.md) che ne verifichi l'accesso reale, la forma e
la pertinenza con una domanda civica, e che porti a una issue intake in DI.

## Boundary con altri workflow

- `inventory-triage` -> prepara il terreno via triage di una lista.
- [source-check.md](./source-check.md) -> verifica una fonte specifica.
- `CATALOG_WATCH_REPORT.md` / `catalog_signals.json` -> segnali differenziali prodotti automaticamente dalla CI.

## Output atteso

- Issue di tipo `inventory-triage` con shortlist ragionata, aperta in SO.
- Per ogni item `go intake` → il prossimo passo è un [source-check](./source-check.md)
  che apre issue intake in `dataset-incubator`.
