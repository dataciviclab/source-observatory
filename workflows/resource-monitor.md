# Workflow: resource-monitor

Workflow per l'esecuzione del monitor di risorse nel Source Observatory.
Versione: 1.1 - 2026-03-30

---

## Scopo

Rilevare cambi su un insieme ristretto di fonti note e decidere il next step giusto.
Risponde a: "questa fonte nota è cambiata in modo da richiedere lavoro sul dataset?"

Non apre issue, non rilancia candidate, non fa source-check autonomamente.

## Perimetro corretto

`resource-monitor` non è uno degli assi core del repo.

Va trattato come supporto ristretto per pochissimi casi ad alto segnale, quando:

- la fonte è già importante per il Lab
- esiste un next step plausibile se il segnale cambia
- il monitor costa meno di uno scouting umano ripetuto

Non va usato come:

- watchlist generica di dataset
- default per nuove fonti
- sostituto di `catalog-watch` o `source-check`

---

## Input

- Config fonti: `source-observatory/scripts/monitor/resource_monitor.sources.yml`
  (se non esiste ancora: `resource_monitor.sources.yml.example` come riferimento)
- Script: `source-observatory/scripts/monitor/resource_monitor.py`
- Output script: `source-observatory/data/monitor/reports/latest.md`
- Snapshot più recente: `source-observatory/data/monitor/snapshots/`

---

## Workflow

### Step 1 - Esegui resource_monitor

Dalla root del workspace:

```powershell
python source-observatory/scripts/monitor/resource_monitor.py --sources source-observatory/scripts/monitor/resource_monitor.sources.yml
```

### Step 2 - Leggi latest.md

Leggere `source-observatory/data/monitor/reports/latest.md`.

Prima di interpretare il report, chiedersi:

- questa fonte è davvero un caso Tier 1?
- il segnale osservato può portare a un next step reale?

Se la risposta è no, il problema può essere nel perimetro del monitor, non nel dataset.

Classificare ogni segnale:

| Tipo | Significato |
|---|---|
| `new` | risorsa comparsa per la prima volta |
| `changed` | URL, nome, formato o metadati modificati |
| `removed` | risorsa presente in precedenza non più visibile |
| `error` | problema di adapter o di portale |

### Step 3 - Applica la matrice del runbook

Per ogni segnale non nullo:

**1. Valuta l'affidabilità dell'adapter**
- `single_url` o `ckan`: segnale più affidabile
- `html`: più sospetto, attendi più falsi positivi

**2. Classifica il next step**

| Condizione | Next step |
|---|---|
| `di_candidate` attivo con config runnable | ispeziona candidate, poi valuta rerun |
| dataset stabile pubblico | verifica se serve update pubblico |
| watchlist o support dataset | source-check, non rerun |
| errore SSL/DNS/timeout | problema da radar, non da dataset |
| nessun next step difendibile | proporre demotion o rimozione dal monitor |

**3. Fermati se il segnale è infrastrutturale**
- SSL, DNS, timeout, drift HTML sono segnali da `radar-check`, non da monitor
- Non trattarli come update del dataset

### Step 4 - Sintesi

Produrre un output strutturato con:
- conteggio segnali per tipo (`new`, `changed`, `removed`, `error`)
- per ogni segnale rilevante: fonte, tipo, azione suggerita
- fonti senza segnale: ok, nessuna azione

---

## Regole di interpretazione

- `changed` non implica rerun automatico: dipende dal tipo di cambio
- `removed` dopo modifiche alla config del monitor è spesso rumore: confrontare la pagina/API prima di assumere una rottura
- `error` ripetuti sulla stessa fonte per SSL/DNS/HTML fragile: valutare demotion a `radar-only`
- Il monitor non valuta il valore civico della fonte: quella è una decisione umana o di `source-check`
- Se `di_candidate` è presente nella config della fonte, ispezionarlo sempre prima di decidere
- Se il segnale non porta quasi mai a una decisione utile, la fonte forse non dovrebbe stare nel monitor

---

## STOP POINT

Fermarsi dopo la sintesi. Non aprire issue, non rilanciare candidate, non modificare
il set monitorato senza istruzione esplicita.

Segnali urgenti: marcarli con
`[ATTENZIONE]` e aspettare istruzioni.

---

## Vincoli

- Niente emoji, niente em dash
- Non modificare `resource_monitor.sources.yml` senza istruzione esplicita
- Non spostare fonti in `radar-only` da soli: proporlo a Gabri
- Non allargare il monitor a nuove fonti solo perché sono interessanti: prima serve una giustificazione forte

---

## Riferimenti

- Script: `source-observatory/scripts/monitor/resource_monitor.py`
- Config: `source-observatory/scripts/monitor/resource_monitor.sources.yml`
- Output: `source-observatory/data/monitor/reports/latest.md`
- Runbook: `source-observatory/docs/runbook.md`
