# Runbook

Guida operativa breve per la v0 attuale.

## Radar

```bash
python scripts/radar_check.py --dry-run
python scripts/radar_check.py
```

Usa `radar` quando la domanda è:

- la fonte risponde?
- ci sono problemi di timeout, SSL, DNS o HTTP?
- il registry è sano?

Output:

- [STATUS.md](../data/radar/STATUS.md)

Scheduling:

- `radar.yml`: run **daily** 03:15 — health check, aggiorna `STATUS.md`, `radar_summary.json`, `radar_history.json`, `sources_registry.yaml`
- `observatory.yml`: run **weekly** (lunedì) 03:20 — inventory, catalog signals, source-check, upload GCS
- `workflow_dispatch` disponibile per entrambi i workflow per run manuali

Comportamento probe:

- non-SDMX portals con timeout/connection error (http_code="-", status YELLOW): retry automatico 1x. Se il retry è GREEN, lo usa; altrimenti annota "Retry timeout/connection: ..." e mantiene YELLOW.
- exception isolation: un portal che esplode non ferma il loop — ritorna ProbeResult(RED) e il probe continua con le fonti successive.

Manutenzione del Registry:

- Se una fonte è stabilmente giù, verificare manualmente l'URL.
- Se l'URL è cambiato, aggiornare `data/radar/sources_registry.yaml`.
- Se la fonte è definitivamente rimossa, valutare la disattivazione o rimozione nel registry.
- `user_agent`, se presente nella fonte del registry, è un contratto della fonte: lo usano radar, inventory e validate. Serve per i portali dietro WAF (es. ANAC).

Boundary:

- Se il problema è di contenuto (non infrastrutturale) -> [source-check.md](../skills/source-check.md)
- Se il catalogo è cambiato ma la fonte è viva -> [inventory-triage.md](../skills/inventory-triage.md)

## Catalog-watch

Output correnti:

- [sources_dashboard.json](../data/reports/sources_dashboard.json) (KPI riassuntivi)
- [catalog_signals.json](../data/catalog/catalog_signals.json)

Usa `catalog-watch` quando la domanda è:

- l'inventario è cambiato?
- c'è drift strutturale?
- c'è un follow-up candidate che merita revisione umana?

Modello v0:

- i segnali vengono prodotti automaticamente dal workflow schedulato `observatory.yml` (ogni lunedì 03:20)
- il follow-up resta `human-run`: il report non sostituisce la review umana sui cambi rilevanti
- il run manuale va usato quando serve un check metodologicamente difendibile fuori schedule
- gli output canonici sono i source report in `data/reports/` e `sources_dashboard.json`; `catalog_signals.json` resta un contratto legacy per ACB
- problemi di connessione/HTTP vanno letti in `radar_summary.json`, non in `catalog_signals.json`
- **Issue automatiche**: in caso di variazioni rilevanti nel catalogo, `observatory.yml` crea o aggiorna una issue `catalog-alert` su GitHub
- **Verdict**: `DOWN` > `NO_DATA`/`HEALTH_ONLY` > `UNREACHABLE` > `STALE` > `INVENTORY_CHANGED` > `CATALOG_ONLY`/`NOT_PROBEABLE` > `PARTIALLY_SCOPED` > `STABLE`. `STABLE` non è il default: se non c'è misura, il verdict è `NO_DATA` (o `HEALTH_ONLY` per `radar-only`).

### Catalog per-repo e `pattern_probes`

Ogni repo dati che dichiara `[tool.observatory]` nel proprio `pyproject.toml`
genera il catalog in-repo (`registry/catalog.json`) con `so-catalog` — engine
condiviso, zero secrets (vedi `catalog-reusable.yml`).

Per le fonti **senza catalogo enumerabile ma con URL deterministici** si
dichiarano sentinelle in `pattern_probes`: se una passa da non disponibile ad
available, il verdict riceve il trigger `new_content_available`.

```toml
[tool.observatory]
source_id = "mef_finanze"
protocol = "html"
base_url = "https://www1.finanze.gov.it/finanze/analisi_stat/"

[[tool.observatory.pattern_probes]]
name = "iva-regionale-2026"
url = "https://www1.finanze.gov.it/finanze/analisi_stat/public/index.php?tree=2026CIVATOT0201&export=3"
min_bytes = 200
```

- `min_bytes` (opzionale): sotto quella soglia una risposta 2xx **non** conta
  come disponibile. Serve per le fonti che rispondono 200 con corpo vuoto
  quando il dato non esiste ancora (es. MEF `analisi_stat`): senza soglia il
  trigger "nuovo contenuto" scatterebbe a ogni run, per sempre.

**Drift degli URL consumati**: per gli upstream di tipo `url` (connector
`http_file`) l'inventario della fonte **non è autorevole** — può descrivere un
altro endpoint dello stesso dato (AGID: `catalogocloud.agid.gov.it` vs
`indicepa.gov.it`) o una sola distribuzione per item (Consip: un resource per
package, mentre il repo consuma più anni). Quando l'inventario non conferma,
`so-catalog` verifica l'URL consumato via HTTP: 2xx → `matched`, risposta di
errore → `missing` (drift reale), errore di rete → `unknown` (nessun falso
drift). **401/403/407/429 sono `unknown`, non drift**: un blocco WAF o un rate
limit non prova che la risorsa sia stata rimossa. I ref **templati**
(`{year}`) non si verificano via HTTP: l'URL concreto lo genera la pipeline,
quindi resta l'esito dell'inventario. Con inventario vuoto (fonti radar-only)
il check funziona **solo** grazie a questa verifica. L'UA usato è quello di
`[tool.observatory]`, per le fonti dietro WAF.

**Regola della prova di assenza** (vale per ogni `kind`): il drift dichiara
`missing` **solo** se ha una prova positiva che l'item esatto non c'è più.
La prova richiesta è dichiarata in `drift.ABSENCE_EVIDENCE`:

| `kind` | Prova | Perché |
|---|---|---|
| `dataflow` | `inventory` | una riga per dataflow nel catalogo SDMX |
| `ckan_dataset` | `inventory` | una riga per package (il nome è l'identità) |
| `ckan_resource` | `probe` | l'inventario tiene **una** distribuzione per item, ma un package ne ha decine → verifica con `resource_show` sulla fonte |
| `url` | `probe` | l'inventario può descrivere un altro endpoint |
| `script_type` | `inventory` | ID logico: match per token sull'area della fonte |

Un `kind` non dichiarato non può dichiarare `missing`: al massimo `unknown`.
Il gate è `tests/test_catalog_drift.py::TestAbsenceEvidence`.

**Query-string negli artifact**: l'URL che va al probe è quello intero, query
inclusa (è l'identità della risorsa per molte fonti), quindi la query finisce
nei parquet tracciati — `data/pipeline/validated.parquet` in questo repo e
`out/so/validated.parquet` nei repo dati. Oggi i parametri osservati sono
`format`, `d`, `t`: nessuna credenziale. **Prima di onboardare una fonte con
URL firmati/tokenizzati** (`?token=`, `?sig=`, `?api_key=`, …) va aggiunta la
redazione dei parametri sensibili (#436), altrimenti il valore viene persistito
in chiaro nel parquet committato.

## Catalog inventory

```bash
python scripts/build_catalog_inventory.py
python scripts/build_catalog_inventory.py --workers 3  # parallelo, sperimentale
python scripts/pipeline/run_pipeline.py --workers 16 --max-concurrency-per-host 4
```

`run_pipeline` applica due limiti: `max_concurrency_per_host` (default 4) e
`max_concurrency` per fonte, letto dal registry e trasportato nelle righe di
inventory. Il numero di worker del pool non è il numero di richieste
concorrenti consentite su un singolo host.

### Semantica di `reachable`

Il probe è una HEAD; `HttpResult.is_ok` significa solo "nessuna eccezione",
quindi una 404 arriverebbe come "ok". Il validator classifica lo status:

| Esito | Significato |
|---|---|
| `reachable=True` | 2xx/3xx |
| `reachable=False` | 4xx/5xx o errore di rete/timeout → `unreachable` |
| `reachable=None` | non verificato: formato non-CSV (nessun probe) |
| `blocked=True` | 401/403/407/429: la risorsa c'è ma non ci è concessa |

`blocked` è escluso dal denominatore di `probeable_items`/`reachability_pct`
(stessa logica `unknown` del drift): un WAF non è un dato sparito. Se tutti i
gruppi sono bloccati il verdict è `UNREACHABLE` con trigger `blocked`, non
`NOT_PROBEABLE`.

`summary.json` espone i conteggi separati: `reachable`, `unreachable` (solo
`False`), `not_checked` (`None`: non-CSV), `blocked`, `skipped`. Prima
`unreachable` includeva anche i non verificati, gonfiando il numero.

Il tempo è tracciato per gruppo (`duration_seconds` in `validated.parquet`) e
aggregato per fonte (`duration_seconds`, `avg_seconds_per_group` in
`by_source`). Per capire dove va il wall del validate: confronta
`avg_seconds_per_group` con il numero di gruppi e il limite per host — il collo
è la fonte con `gruppi / max_concurrency_per_host * avg` più alto.

### robots.txt nei fetch HTML

Il collector HTML (`area_pages`, `page_url_template`, pagine da sitemap,
`homepage`) verifica `robots.txt` prima di ogni fetch diretto, con cache per
origine (`scripts/collectors/robots.py`). Politica:

- `robots.txt` assente o 4xx → nessuna regola, fetch consentito;
- `robots.txt` illeggibile / 5xx / errore di rete → **fail-open** (il fetch
  procede) e l'origine finisce in `summary.robots_error`;
- pagina vietata → skip, conteggiata in `summary.robots_skipped`. Con
  `page_url_template` l'enumerazione si ferma alla prima pagina vietata,
  perché le pagine sono sequenziali sullo stesso percorso;
- se **tutte** le pagine sono bloccate, la fonte non produce righe: l'inventory
  la marca `robots_blocked` e preserva le righe precedenti come `stale`, invece
  di svuotare il catalogo.

Il matching segue **RFC 9309**, non `urllib.robotparser`: gruppo più specifico
dello user agent, `*` come jolly, `$` come ancora di fine path, longest-match e
`Allow` vincente a parità di lunghezza. `urllib.robotparser` non lo fa: ignora
wildcard e longest-match, quindi con `Disallow: /` + `Allow: /public/`
bloccherebbe `/public/a`.

Il fail-open è deliberato: un robots.txt temporaneamente rotto non deve
bloccare l'osservatorio. Se serve fail-closed, il punto unico da cambiare è
`RobotsGuard._fetch_rules`.

### `catalog-only`: inventory senza validate item-level

Per cataloghi enormi o non probeabili si può disattivare il validate per fonte:

```yaml
source_check:
  skip_item_validation: true
  skip_item_validation_reason: "catalogo enorme / formato non gestito"
```

Il flusso resta inventory → diff → report; la pipeline non esegue probe
item-level e il verdict diventa `CATALOG_ONLY` (o `INVENTORY_CHANGED` se il
catalogo è cambiato: il delta è più informativo dello stato). È il caso di
OpenBDAP, ISTAT SDMX, AGID, giustizia-statistiche e MIMIT RNA: il catalogo è
utile, il validate no.

Usa `catalog inventory` quando la domanda è:

- quali item sono oggi enumerabili nei cataloghi osservati?
- quali fonti `catalog-watch` producono un inventario riusabile per scouting?
- il perimetro pubblico resta coerente con le esclusioni dichiarate?

Output (non versionati nel repo):

- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- `data/catalog_inventory/generated/catalog_inventory_report.json`

Per ottenere l'ultimo output senza rieseguire: artifact del workflow `observatory` su GitHub Actions, oppure GCS se configurato.

Disciplina:

- il perimetro segue le fonti `catalog-watch` del registry
- un run completo droppa dall'inventory **solo** le fonti rimosse dal registry;
  un run filtrato (`--source-ids`) preserva tutto ciò che non ha girato, perché
  non è una fotografia completa
- le fonti `radar-only` restano nell'inventory con le righe esistenti, marcate
  `stale` con `stale_reason: not_catalog_watch`: sono escluse da validate e
  report, così una demotion riduce davvero probe e metriche. Se una fonte torna
  `catalog-watch` lo storico è ancora lì
- se un collector torna **0 righe** ma l'inventory precedente ne aveva, la
  fonte è `empty_result` e le righe restano `stale` (`stale_reason:
  empty_result`): un endpoint che cambia forma non deve cancellare la fonte
- se robots.txt blocca tutte le pagine, la fonte è `robots_blocked` e le righe
  vecchie restano come `stale` (`stale_reason: robots_disallow`): un catalogo
  vuoto non deve sembrare una fonte spenta con il radar verde
- una fonte può restare osservata in SO ma non essere inventariabile
- l'upload su GCS richiede WIF org-level (GCP_WORKLOAD_IDENTITY_PROVIDER, GCP_SERVICE_ACCOUNT) e il prefix hardcoded nella workflow (CATALOG_INVENTORY_GCS_PREFIX)
- in assenza di GCS il workflow resta valido: usa baseline locale vuota e salta i passaggi opzionali di storage/diff
- il workflow gira ogni lunedì (schedule) ed è disponibile anche via `workflow_dispatch`
- `--skip-red-sources` usato in CI per evitare tentativi su fonti già RED (timeout, WAF)
- `sync_datasets_in_use.py` viene eseguito nel workflow `radar.yml` per allineare il catalogo ACB (`topic_index.json`, branch `context`: `https://raw.githubusercontent.com/dataciviclab/agent-context-builder/context/topic_index.json`). Se ACB non risponde, il registry resta invariato.
  **La chiave del registry deve coincidere con il `source_id` usato dai repo e da ACB**: se differisce, l'uso reale non si aggancia e la fonte risulta a zero (è quello che era successo a `cortecostituzionale` vs `corte_costituzionale`). Prima di demote/rimuovere una fonte, verificare che l'id non sia solo un alias.
- Il sync ha una guardia anti-wipe: rifiuta `schema_version` diverso da 7, fonti non vuote che diventerebbero vuote, calo link >20% e discesa sotto 50 link. Per rimozioni intenzionali usare `--allow-drop`.

## Ordine consigliato

1. esegui `radar`
2. leggi `catalog-watch`
3. decidi se esiste davvero un follow-up umano giustificato

## Disciplina

- tieni l'universo piccolo
- preferisci segnali leggibili alla copertura larga
