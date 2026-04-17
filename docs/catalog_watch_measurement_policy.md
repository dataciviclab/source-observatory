# Policy Catalog-Watch

Scopo: evitare che un delta numerico grezzo diventi automaticamente `inventory_change`.

## Regola Base

Un delta è segnale reale solo se il confronto è metodologicamente comparabile.

La baseline dovrebbe dichiarare:

- `metric`
- `value`
- `method`
- `reliability` opzionale

Se il metodo non è chiaro o non è confrontabile, il delta va trattato come `missing_data`, non come novità.

## Comparabilità

Il confronto regge solo se restano stabili:

1. endpoint interrogato
2. metodo di conteggio
3. paginazione o limiti
4. scope della risposta
5. formato e parsing

Se uno di questi cambia o non è verificato, il numero osservato non è affidabile.

## Casi Tipici

SDMX:

- conteggi molto inferiori alla baseline
- numeri rotondi o ricorrenti
- dataflow noti non inclusi

Lettura: probabile limite del tool o paginazione implicita, non crollo reale del catalogo.

CKAN:

- salto improvviso molto ampio
- `package_list` e `package_search` con universi diversi
- baseline storica ottenuta con query diversa

Regola: confrontare `package_list` con `package_list` e `package_search` con `package_search`. Se il metodo non coincide, usare `[DATO MANCANTE]`.

## Tassonomia

- `inventory_change`: delta comparabile e difendibile.
- `structural_drift`: cambia struttura, naming, shape o comportamento.
- `missing_data`: numero osservato non ancora affidabile.

`measurement anomaly` può stare nel dettaglio, ma il tipo esposto resta `missing_data`.

`follow_up_candidate` non sostituisce il segnale: prima si classifica il delta, poi si decide se serve revisione umana.

## Regola Editoriale

Nel report:

- non trasformare delta grezzi in narrativa
- non usare conteggi sospetti come prova di novità
- preferire formule come "conteggio non ancora confrontabile con la baseline"

Per la v0: pochi segnali affidabili battono numeri impressionanti ma deboli.
