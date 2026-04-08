# Workflow: radar-check

Workflow canonico di `source-observatory` per il controllo di salute dei portali.
Versione: 1.2 - 2026-04-08

## Obiettivo di fase

Verificare la raggiungibilita' e la salute infrastrutturale delle fonti nel registry.

Questo workflow serve a rispondere a:

- questa fonte e' viva?
- il portale risponde?
- ci sono errori di SSL, DNS, timeout o risposta anomala?

Questo workflow serve a:

- controllare la salute della fonte
- produrre uno stato radar leggibile
- distinguere rapidamente tra `ok` e problema infrastrutturale

Non serve a:

- dire se il dataset e' aggiornato
- dire se il catalogo contiene qualcosa di nuovo
- dire se la fonte merita lavoro del Lab
- aprire follow-up automatici

Queste domande appartengono invece a:

- `catalog-watch`
- `resource-monitor`
- `source-check`

## Quando usarlo

Usalo quando:

- vuoi controllare la salute attuale delle fonti nel registry
- vuoi aggiornare `STATUS.md`
- vuoi capire se esistono problemi infrastrutturali ricorrenti

Non usarlo quando:

- la domanda vera e' sul contenuto del catalogo
- la domanda vera e' sul valore della fonte
- stai cercando di fare source-check o intake

## Input minimi

Per partire servono almeno:

- registry `source-observatory/data/radar/sources_registry.yaml`
- script `source-observatory/scripts/radar_check.py`

## Preconditions minime

Prima del run dovrebbero esserci almeno:

- un registry leggibile
- una ragione semplice per eseguire il check:
  - health snapshot
  - dry-run
  - verifica dopo fix

Nel dubbio:

- se la domanda vera non e' "questa fonte e' viva?", probabilmente non sei nel workflow giusto

## Stop rules

Fermati e non allargare il lavoro quando:

- stai cercando di inferire aggiornamenti di contenuto dai soli segnali radar
- stai per trasformare un warning infrastrutturale in giudizio sul dataset
- stai per aprire issue o source-check in automatico
- stai per modificare il registry a mano invece di limitarti a leggere il risultato del run

## Passi canonici

### 1. Leggi il registry

Leggi:

- `source-observatory/data/radar/sources_registry.yaml`

Giusto per avere il contesto delle fonti prima del run:

- `protocol`
- `source_kind`
- `observation_mode`
- eventuale `verdict`

### 2. Esegui il run

Dalla root del workspace:

```powershell
python source-observatory/scripts/radar_check.py
```

Per un dry-run senza scrivere lo stato:

```powershell
python source-observatory/scripts/radar_check.py --dry-run
```

Regola pratica:

- se vuoi solo capire come si comporta il probe, parti da `--dry-run`

### 3. Leggi `STATUS.md`

Dopo il run, leggi:

- `source-observatory/data/radar/STATUS.md`

Classifica almeno cosi':

| Classificazione | Segnale |
|---|---|
| `ok` | stato `GREEN`, nessun errore rilevante |
| `warning infrastrutturale` | stato `YELLOW` o `RED` per timeout, SSL, DNS, request error |
| `da osservare` | note ripetute o fallback SSL usato anche se la fonte risponde |

### 4. Fai una sintesi breve

Lascia una sintesi con:

- conteggio per classificazione
- fonti con `warning infrastrutturale`
- fonti `da osservare`
- eventuali fonti considerate importanti che ora mostrano problemi

## Errori tipici

- leggere `GREEN` come segnale di valore del dataset
- trattare un warning SSL, DNS o timeout come aggiornamento di contenuto
- usare il radar per decidere da solo un source-check
- confondere un problema di health con un problema del candidate o del dataset

## Regole di interpretazione

- `GREEN` non implica lavoro sul dataset: e' solo salute della fonte
- un warning SSL, DNS o timeout non e' un aggiornamento di contenuto
- se una fonte SDMX restituisce `404` su `HEAD`, puo' essere un falso negativo noto
- la modalita' di osservazione aiuta a capire il contesto, ma non cambia il significato del segnale radar

## Output minimo atteso

Un run buono di `radar-check` lascia:

- `STATUS.md` aggiornato oppure un dry-run leggibile
- una classificazione semplice per fonte
- una sintesi rapida dei problemi infrastrutturali osservati

## Definition of done

Il workflow e' chiuso bene quando:

- il run e' stato eseguito o simulato in modo esplicito
- `STATUS.md` e' leggibile
- la sintesi distingue chiaramente tra fonti sane e warning infrastrutturali
- non sono stati aperti follow-up automatici
- non sono state fatte inferenze improprie sul contenuto dei dataset

## Stati finali ammessi

- `ok`
- `warning infrastrutturale`
- `da osservare`

## Dove orientarsi

- [README.md](../README.md)
- [docs/runbook.md](../docs/runbook.md)
- [data/radar/README.md](../data/radar/README.md)
