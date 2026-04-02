# Policy: Catalog Watch Measurement

Data: 2026-03-31

## Scopo

Chiarire come leggere i delta numerici prodotti da `catalog-watch`.

Un cambiamento di conteggio non va trattato automaticamente come segnale reale del catalogo.
Prima bisogna distinguere tra:

- segnale del catalogo
- anomalia di misurazione

## Regola base

Per la v0, la comparabilita' dovrebbe essere leggibile anche nella baseline:

- `metric`
- `value`
- `method`
- opzionale: `reliability`

Un delta numerico è un **segnale reale di catalogo** solo se il confronto è metodologicamente comparabile.

Se il confronto non è chiaramente comparabile, il delta va classificato come:

- `missing_data`
- oppure `measurement anomaly`

e non come `inventory_change`.

## Quando un delta è comparabile

Il confronto è comparabile solo se restano stabili:

1. endpoint interrogato
2. metodo di conteggio
3. eventuali limiti o paginazione
4. scope della risposta
5. formato/parsing della risposta

Se anche uno solo di questi punti cambia o non è verificato, il delta non è ancora affidabile.

## Casi tipici

### SDMX

Segnali sospetti:

- conteggi molto inferiori alla baseline
- numeri “rotondi” o ricorrenti
- presenza nota di dataflow non inclusi nel conteggio

Lettura corretta:

- probabile limite del tool
- probabile paginazione implicita
- non vero crollo del catalogo

### CKAN

Segnali sospetti:

- salto improvviso molto ampio
- `package_list` e `package_search` che sembrano dare universi diversi
- baseline storica ottenuta con query diversa dalla query attuale

Lettura corretta:

- probabile mismatch di metodo
- probabile baseline incomparabile
- non vera espansione editoriale finché non verificata

Regola pratica:

- se la baseline dichiara `method: package_list`, il confronto numerico va fatto con `package_list`
- se la baseline dichiara `method: package_search`, il confronto numerico va fatto con `package_search`
- se il metodo non e' dichiarato o non e' confrontabile, il delta va trattato come `[DATO MANCANTE]`

## Tassonomia operativa

Usare:

- `inventory_change`
  - solo per delta comparabili e difendibili
- `structural_drift`
  - quando cambia struttura, naming, shape o comportamento del catalogo
- `missing_data`
  - quando il numero osservato non è ancora affidabile

`measurement anomaly` può vivere come descrizione nel dettaglio, ma il tipo segnale da esporre nel report dovrebbe restare `missing_data`.

`follow_up_candidate` non dovrebbe invece sostituire il segnale principale:

- se il delta è debole o non confrontabile, resta `missing_data`
- se il delta è difendibile, può diventare `inventory_change`
- solo dopo, se serve davvero revisione umana, il report può suggerire un follow-up

## Regola editoriale

Nel report:

- non trasformare delta numerici grezzi in narrativa
- non usare conteggi sospetti come prova di novità
- preferire una frase come:
  - "conteggio non ancora confrontabile con la baseline"

## Impatto sulla v0

Per la v0 pubblicabile:

- meglio pochi segnali affidabili
- peggio numeri impressionanti ma metodologicamente deboli

Questo vale in particolare per:

- `istat_sdmx`
- `inps`

finché il metodo di conteggio non è stabilizzato.
