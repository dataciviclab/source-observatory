# Workflows

Indice minimo dei workflow canonici di `source-observatory`.

## Come orientarsi

- [portal-scout.md](./portal-scout.md)
  - classifica un portale o una superficie dati prima dell'ingresso nel funnel
  - decide se ha senso `catalog-watch`, `radar-only` o `source-check` item-based

- [source-check.md](./source-check.md)
  - verifica se una fonte o un dataset pubblico regge davvero come pista del Lab
  - esce con un verdetto singolo e un next step esplicito

- [catalog-watch.md](./catalog-watch.md)
  - osserva pochi cataloghi in modalita inventariale
  - cerca segnali di cambiamento sul catalogo, non sul singolo file

- [radar-check.md](./radar-check.md)
  - controlla la salute infrastrutturale della fonte
  - risponde alla domanda: la fonte e viva?

- [resource-monitor.md](./resource-monitor.md)
  - monitora poche risorse note ad alto valore
  - segnala cambi che possono richiedere un next step umano sul dataset

## Boundary rapido

- `portal-scout`
  - classificazione iniziale del portale
- `radar-check`
  - health della fonte o del portale
- `catalog-watch`
  - cambi inventariali o strutturali del catalogo
- `resource-monitor`
  - cambi su risorse note e ristrette
- `source-check`
  - valutazione umana della fonte come possibile pista del Lab

## Regola pratica

Se la domanda e:

- "la fonte e viva?" -> `radar-check`
- "questo portale e davvero un catalogo osservabile?" -> `portal-scout`
- "il catalogo ha cambiato inventario o struttura?" -> `catalog-watch`
- "questa risorsa nota e cambiata in modo rilevante?" -> `resource-monitor`
- "questa fonte regge davvero come pista del Lab?" -> `source-check`

## Onboarding portali

Sequenza canonica minima per un nuovo portale:

1. `portal-scout`
2. decision gate
3. eventuale ingresso nel registry
4. eventuale baseline o inventory
5. eventuale `source-check` su item specifici

Esiti canonici del gate:

- `GO catalog-watch`
- `GO radar-only`
- `GO source-check item-based`
- `NO per ora`

Regola di orientamento:

- se il metodo di enumerazione degli item e stabile e riproducibile -> `catalog-watch`
- se il portale e utile ma non inventariabile in modo affidabile -> `radar-only`
- se il valore sta in pochi item noti e non nel portale come catalogo -> `source-check item-based`

## Nota: catalog inventory

`catalog inventory` non e un workflow. E un artifact derivato:
uno snapshot tabulare di tutti gli item in un catalogo noto, prodotto da `scripts/build_catalog_inventory.py`.

La distinzione rispetto a `catalog-watch`:

- `catalog-watch` osserva se il catalogo e cambiato
- `catalog inventory` enumera cosa c'e dentro

Il catalog inventory serve per scouting e triage di item promettenti, non per rilevare cambiamenti.
Se nasce un dubbio su quale dei due usare: `catalog-watch` risponde a "e cambiato qualcosa?", `catalog inventory` risponde a "cosa c'e in questo catalogo?"

L'inventory nasce solo dopo un esito `GO catalog-watch` e solo se esiste un metodo di enumerazione verificato.
Se il portale e `radar-only` o `source-check item-based`, l'inventory non e il passo giusto.
