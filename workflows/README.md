# Workflows

Indice minimo dei workflow canonici di `source-observatory`.

## Come orientarsi

- [portal-scout.md](./portal-scout.md)
  - classifica un portale o una superficie dati prima dell'ingresso nel funnel
  - decide se ha senso `catalog-watch`, `radar-only` o `source-check` item-based

- [catalog-inventory-scout.md](./catalog-inventory-scout.md)
  - triage di un catalog inventory per ricavare una shortlist
  - decide cosa mandare a `source-check` o `watchlist`

- [source-check.md](./source-check.md)
  - verifica se una fonte o un dataset pubblico regge davvero come pista del Lab
  - esce con un verdetto singolo e un next step esplicito

- [catalog-watch.md](./catalog-watch.md)
  - osserva pochi cataloghi in modalità inventariale
  - cerca segnali di cambiamento sul catalogo, non sul singolo file


## Boundary rapido

- `portal-scout`
  - classificazione iniziale del portale
- `catalog-inventory-scout`
  - triage di una lista di item di un catalogo
- `catalog-watch`
  - cambi inventariali o strutturali del catalogo
- `source-check`
  - valutazione umana della fonte come possibile pista del Lab

## Regola pratica

Se la domanda è:

- "cosa c'è in questo catalogo e cosa vale la pena approfondire?" -> `catalog-inventory-scout`
- "questo portale è davvero un catalogo osservabile?" -> `portal-scout`
- "il catalogo ha cambiato inventario o struttura?" -> `catalog-watch`
- "questa fonte regge davvero come pista del Lab?" -> `source-check`

## Onboarding portali

Sequenza canonica minima per un nuovo portale:

1. `discover_portals.py` (opzionale, per discovery batch) → parquet candidati
2. `portal-scout` → verdict + soglie minime
3. decision gate
4. eventuale ingresso nel registry
5. eventuale baseline o inventory
6. eventuale `source-check` su item specifici

Esiti canonici del gate e soglie minime:

| Esito | Condizioni minime |
|---|---|
| `GO catalog-watch` | Probe reale · enumerabile · temporale ≥ 80% · ≥ 20 dataset strutturati · non duplicato |
| `GO radar-only` | Raggiungibile · PA nazionale · non automatizzabile ora |
| `GO source-check item-based` | Strutturato ma < 20 dataset o > 50% PDF |
| `NO per ora` | Falso positivo · WAF · fuori scope · duplicato |

`GO catalog-watch` → proponi YAML per registry + apri issue SO (`portal-scout`).
`GO radar-only` → aggiorna registry direttamente, nessuna issue.

## Nota: catalog inventory

`catalog inventory` non è un workflow. È un artifact derivato:
uno snapshot tabulare di tutti gli item in un catalogo noto, prodotto da `scripts/build_catalog_inventory.py`.

La distinzione rispetto a `catalog-watch`:

- `catalog-watch` osserva se il catalogo è cambiato
- `catalog inventory` enumera cosa c'è dentro

Il catalog inventory serve per scouting e triage di item promettenti, non per rilevare cambiamenti.
Se nasce un dubbio su quale dei due usare: `catalog-watch` risponde a "è cambiato qualcosa?", `catalog inventory` risponde a "cosa c'è in questo catalogo?"

L'inventory nasce solo dopo un esito `GO catalog-watch` e solo se esiste un metodo di enumerazione verificato.
Se il portale è `radar-only` o `source-check item-based`, l'inventory non è il passo giusto.

## Documentazione e Runbook

- [runbook.md](../docs/runbook.md)
  - runbook operativo per tutti i controlli (radar, catalog-watch, inventory)
  - include dettagli sulla gestione del registry e delle GitHub Actions
