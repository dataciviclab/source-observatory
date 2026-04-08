# Workflows

Indice minimo dei workflow canonici di `source-observatory`.

## Come orientarsi

- [source-check.md](./source-check.md)
  - verifica se una fonte o un dataset pubblico regge davvero come pista del Lab
  - esce con un verdetto singolo e un next step esplicito

- [catalog-watch.md](./catalog-watch.md)
  - osserva pochi cataloghi in modalita' inventariale
  - cerca segnali di cambiamento sul catalogo, non sul singolo file

- [radar-check.md](./radar-check.md)
  - controlla la salute infrastrutturale della fonte
  - risponde alla domanda: la fonte e' viva?

- [resource-monitor.md](./resource-monitor.md)
  - monitora poche risorse note ad alto valore
  - segnala cambi che possono richiedere un next step umano sul dataset

## Boundary rapido

- `radar-check`:
  - health della fonte o del portale
- `catalog-watch`:
  - cambi inventariali o strutturali del catalogo
- `resource-monitor`:
  - cambi su risorse note e ristrette
- `source-check`:
  - valutazione umana della fonte come possibile filone del Lab

## Regola pratica

Se la domanda e':

- "la fonte e' viva?" -> `radar-check`
- "il catalogo ha cambiato inventario o struttura?" -> `catalog-watch`
- "questa risorsa nota e' cambiata in modo rilevante?" -> `resource-monitor`
- "questa fonte regge davvero come pista del Lab?" -> `source-check`
