# Workflow: radar-check

Workflow per l'esecuzione del radar di salute portali nel Source Observatory.
Versione: 1.1 - 2026-03-30

---

## Scopo

Verificare la raggiungibilità e la salute infrastrutturale dei portali nel registry.
Risponde a: "questo portale è vivo?"

Non risponde a:
- "il dataset è aggiornato?"
- "c'è qualcosa di nuovo nel catalogo?"
- "vale la pena analizzarlo?"

Queste domande appartengono rispettivamente a:
- `resource-monitor` nei pochissimi casi Tier 1 già giustificati
- `catalog-watch`
- `source-check`

---

## Input

- Registry: `source-observatory/data/radar/sources_registry.yaml`
- Script: `source-observatory/scripts/radar_check.py`
- Output script: `source-observatory/data/radar/STATUS.md`

## Perimetro corretto

`radar-check` è il layer più alto e più semplice del repo.

Serve a osservare:

- salute della fonte
- raggiungibilità
- errori SSL, DNS, timeout o risposta anomala

Non serve a:

- leggere il catalogo
- inferire update di dataset
- proporre source-check in automatico

---

## Workflow

### Step 1 - Leggi il registry

Leggere `sources_registry.yaml` per avere il contesto delle fonti prima del run:
- elencare le fonti con il loro `verdict` attuale e `observation_mode`

### Step 2 - Esegui radar_check

Dalla root del workspace:

```powershell
python source-observatory/scripts/radar_check.py
```

Per un dry-run senza scrivere lo stato:

```powershell
python source-observatory/scripts/radar_check.py --dry-run
```

### Step 3 - Leggi STATUS.md

Leggere `source-observatory/data/radar/STATUS.md` dopo il run.

Classificare ogni fonte in uno di questi stati:

| Classificazione | Segnale |
|---|---|
| `ok` | stato `GREEN`, nessun errore rilevante |
| `warning infrastrutturale` | stato `YELLOW` o `RED` per timeout, SSL, DNS, request error |
| `da osservare` | note ripetute o fallback SSL usato anche se la fonte risponde |

### Step 4 - Sintesi

Produrre un breve output con:
- conteggio per classificazione
- lettura rapida dei tipi sorgente e delle modalità osservazione
- fonti con `warning infrastrutturale` o `da osservare` con dettaglio
- eventuali fonti `go` nel registry che ora mostrano problemi

---

## Regole di interpretazione

- `GREEN` / `ok` non implica lavoro sul dataset: è solo salute della fonte
- Un warning SSL, DNS o timeout non è un aggiornamento di contenuto
- Se una fonte SDMX restituisce 404 su HEAD: è un falso negativo noto
- Errori ripetuti sulla stessa fonte: segnalarlo a Gabri, non modificare il registry da soli
- La modalità osservazione aiuta a capire il next step atteso, ma non cambia il significato del segnale radar

---

## STOP POINT

Fermarsi dopo la sintesi. Non aprire issue, non fare source-check, non modificare il registry
senza istruzione esplicita.

Se una fonte mostra un problema rilevante, segnalarlo chiaramente con `[ATTENZIONE]`
e aspettare istruzioni.

---

## Vincoli

- Niente emoji, niente em dash
- Non modificare `sources_registry.yaml`: il registry è aggiornato dallo script, non dalla skill
- Non promuovere fonti a `monitor-active` o `catalog-watch` senza conferma
- Non trattare una fonte come problema di dataset solo perché è collegata a un candidate o a un dataset noto

---

## Riferimenti

- Script: `source-observatory/scripts/radar_check.py`
- Registry: `source-observatory/data/radar/sources_registry.yaml`
- Output: `source-observatory/data/radar/STATUS.md`
- Runbook: `source-observatory/docs/runbook.md`
