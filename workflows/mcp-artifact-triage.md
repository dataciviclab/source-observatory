# MCP Artifact Triage

Workflow per usare il layer MCP read-only di Source Observatory quando un agente deve capire cosa esiste gia' negli artifact.

## Quando usarlo

Usalo quando la domanda e':

- quali fonti sono gia' osservate?
- quali cataloghi sono inventariati?
- ci sono candidati portale nuovi?
- cosa dicono gli artifact prima di aprire un nuovo source-check?
- perche' una fonte non compare nel catalog inventory?

Non usarlo per:

- validare definitivamente una fonte come pista del Lab
- pubblicare un finding
- modificare registry o artifact
- decidere da solo un ingresso in `dataset-incubator`

## Ordine di lettura

1. `so_radar_summary`
   - orienta lo stato fonte e la copertura radar
   - utile per capire se una fonte e' gia' nota anche senza inventory

2. `so_inventory_status`
   - legge il report del catalog inventory
   - usa il GCS pubblico di default, altrimenti cache locale se il backend e' `local` o GCS non e' raggiungibile in `auto`
   - distingue `ok`, `error`, `protocol_not_supported` e assenza dal run
   - e' il primo posto da controllare quando una fonte non appare nel parquet

3. `so_catalog_inventory_search`
   - cerca item o dataflow solo dentro l'inventory derivato
   - non usarlo come prova di assenza assoluta di dataset

4. `so_catalog_signals`
   - controlla segnali di cambiamento catalogo
   - utile prima di riaprire triage su fonti gia' monitorate

5. `so_inventory_query`
   - cerca risultati source-check item-level gia' prodotti
   - utile per evitare duplicati e riusare evidenze

6. `so_portal_candidates`
   - controlla portali scoperti o nuovi candidati
   - utile per alimentare `portal-scout`

7. `so_probe_url`
   - verifica puntuale di reachability o content-type
   - non sostituisce `portal-scout`

8. `so_discover_sdmx`
   - consulta l'inventory SDMX se disponibile
   - se l'inventory non e' disponibile, leggere lo stato restituito e non dedurre che ISTAT non abbia dataflow

## Regole di interpretazione

- Ogni risposta va letta insieme al campo `artifact` o `source`.
- Per i parquet, `cache.source = gcs` e' la situazione preferita quando i prefissi GCS sono configurati.
- Per i parquet, leggere sempre anche il blocco `cache`: se `stale = true`, refresh da artifact CI/GCS o rigenera prima di usare i risultati come stato corrente.
- Un artifact mancante e' un problema di disponibilita' del run, non una conclusione sulla fonte.
- Una fonte assente dall'inventory puo' essere fuori perimetro, non supportata, fallita nel run o semplicemente non enumerabile in modo difendibile.
- `source_check_results.parquet` e `catalog_inventory_latest.parquet` hanno semantiche diverse: il primo contiene controlli item-level, il secondo inventory cataloghi.
- Non fare fallback automatici tra artifact diversi senza dichiararlo nel report.

## Output atteso

Un triage MCP dovrebbe chiudere con:

- artifact consultati
- freschezza della cache locale, se sono stati letti parquet
- stato per fonte, se rilevante
- cosa e' coperto dagli artifact
- cosa resta fuori
- prossimo workflow consigliato

Esempio:

```text
Artifact letti:
- radar_summary: fonte presente, stato YELLOW
- inventory_status: run error su endpoint catalogo
- source_check_results: cache locale stale, non usata come fonte corrente
- catalog_inventory_search: non interrogato perche' inventory non disponibile

Interpretazione:
la fonte e' nota al radar, ma non c'e' inventory interrogabile. Non e' una prova di assenza dataset.

Next step:
source-check su item noto oppure portal-scout se serve rivalutare l'enumerabilita'.
```
