# Schema: `source_check_results.parquet`

Output di `scripts/bulk_source_check.py`. Consuma questo file chiunque debba valutare se un item del catalogo è idoneo per l'intake nel Lab (toolkit, BI, ACB, pipeline downstream).

---

## Panoramica

Ogni riga corrisponde a un item controllato. Le colonne si dividono in tre gruppi:

| Gruppo | Contenuto |
|---|---|
| **Identità** | `source_id`, `item_id`, `item_name`, `title`, `organization`, `tags` |
| **Check** | `url_checked`, `http_status`, `reachable`, `check_notes`, `granularity`, `year_min`, `year_max`, `resource_format`, `notes` |
| **Score** | `intake_score`, `intake_candidate`, `needs_review`, `enrich_method`, `check_timestamp` |

---

## Colonne

### Identità

| Campo | Tipo | Descrizione |
|---|---|---|
| `source_id` | `str` | ID della fonte nel registry (es. `inps`, `openbdap`). Può essere `None` se l'item non è stato matched a una fonte nota. |
| `item_id` | `str` | Identificativo univoco dell'item nel catalogo di origine. Formato dipende dalla fonte (CKAN slug, SDMX dataflow ID, ecc.). |
| `item_name` | `str` | Nome leggibile dell'item. Può coincidere con `title` se il catalogo source non separa nome e titolo. |
| `title` | `str` | Titolo arricchito dell'item. Preferisce `enriched_title` da CKAN package_show se disponibile, altrimenti il `title` del catalogo. |
| `organization` | `str` | Organizzazione responsabile secondo il catalogo. Per CKAN, è il campo `organization.title`. Può essere `None` per fonti che non espongono questo concetto (es. SPARQL DCAT). |
| `tags` | `list[str]` | Tag associati all'item. Prelevati da enrichment o dal catalogo. `None` se non disponibili. |

### Check

| Campo | Tipo | Descrizione |
|---|---|---|
| `url_checked` | `str` | URL su cui è stato eseguito il HEAD check. Precedenza: `resource_url` (enrichment) → `landing_page` (catalogo) → `distribution_url` (catalogo). Può essere stringa vuota se nessun URL era disponibile. |
| `http_status` | `int` | Codice HTTP restituito dal HEAD. `None` se il check non è stato possibile (es. URL mancante, errore di rete). |
| `reachable` | `bool` | `True` se `http_status` è < 400. `False` altrimenti (inclusi i casi di errore di rete che producono `http_status = None`). |
| `check_notes` | `str` | Motivo dell'errore se `reachable = False`. Valori possibili: `"url_missing_or_invalid"`, `"ssl_error"`, `"connection_error"`, `"timeout"`, o altro messaggio. Troncato a 120 caratteri nel path normale via `_http_head()`; fino a 200 caratteri nel fallback su eccezioni non gestite. `None` se il check è andato a buon fine. |
| `granularity` | `str` | Livello geografico/materico del dato. Valori: `comune` (40 punti), `provincia` (30), `regione` (20), `nazionale` (10), `europeo` (5), `non_determinato` (0). Derivato da enrichment SDMX annotations o inferito da titolo/tag con regex. |
| `year_min` | `int` | Anno più antico coperto dal dataset. Derivato da SDMX annotations o inferito da titolo/tag. `None` se non determinabile. |
| `year_max` | `int` | Anno più recente coperto dal dataset. Stessa logica di `year_min`. `None` se non determinabile. |
| `resource_format` | `str` | Formato della risorsa downloadable. Valori previsti: `CSV`, `JSON`, `XLSX`, `XLS`, `XML`, `SDMX`, `PDF`. Estratto da CKAN resource o da HTML scrape. `None` se non disponibile. |
| `notes` | `str` | Note esplicitate dall'enrichment CKAN (`enriched_notes`). Campo libero per annotazioni di contesto. Può essere `None` se l'enrichment non ha prodotto note. |

### Score e metadati

| Campo | Tipo | Descrizione |
|---|---|---|
| `intake_score` | `int` | Punteggio 0–100 calcolato da `_intake_score()`. Composizione: granularità (0–40) + copertura anni (0–20) + raggiungibilità (0–20) + formato (0–20) + bonus/malus enrichment (0–5, -5). |
| `intake_candidate` | `bool` | `True` se `intake_score >= 40` **e** `needs_review = False`. Indica che l'item è idoneo per l'intake senza review manuale. |
| `needs_review` | `bool` | `True` se `granularity = "non_determinato"` oppure `year_min is None`. Segnala che il dato richiede valutazione manuale prima dell'intake. |
| `enrich_method` | `str` | Metodo usato per arricchire i metadata. Valori: `ckan_package_show` (arricchimento pieno CKAN, +5 punti), `sdmx_dataflow_annotations` (arricchimento SDMX, +5 punti), `html_scrape` (estrazione link da HTML), `scraping_blocked` (fonte bloccata per scraping, nessun bonus), `html_scrape_failed`, `none`, `error`. |
| `check_timestamp` | `str` | ISO 8601 timestamp in UTC del momento in cui il check è stato eseguito (es. `"2026-04-21T05:00:00+00:00"`). |

---

## Calcolo di `intake_score`

La funzione `_intake_score()` in `bulk_source_check.py:438` composizione:

```
granularità:    comune=40, provincia=30, regione=20, nazionale=10, europeo=5, non_determinato=0
anni:           span > 0 → min(20, span/20*20); un solo anno noto → +5
raggiungibile:  +20 se reachable=True, altrimenti +0
formato:        CSV=20, JSON=20, XLSX=12, XLS=10, XML=8, SDMX=8, PDF=2, altro=0
enrichment:     ckan_package_show o sdmx_dataflow_annotations → +5; needs_review → -5

score finale: max(0, min(100, somma))
```

**Soglia**: `intake_candidate = True` quando `score >= 40` e `needs_review == False`.

---

## Note per consumer

- **Un item può avere `intake_score` alto ma `intake_candidate = False`** se `needs_review = True` (granularità o anni non determinati). Il check lo segnala per dare priorità alla review.
- **HTTP status e raggiungibilità non influenzano lo score** — un URL irraggiungibile non abbassa direttamente il punteggio, ma l'assenza di `resource_format` e `year_min` produrrà `needs_review = True`, che applica il -5 e potrebbe far scendere sotto soglia.
- **`enrich_method = error`** indica un'eccezione non gestita durante l'enrichment. La riga è presente ma con dati incompleti.
- Il parquet viene sovrascritto ad ogni run — non è incrementale. Per segnali longitudinali, consultare gli snapshot in GCS (`source-check/snapshots/source_check_{stamp}.parquet`).
- Il file locale sotto `data/catalog_inventory/generated/` è una cache operativa. La fonte corrente è il path GCS pubblicato dal workflow `source-check.yml`; l'artifact GitHub Actions resta un canale di recupero/debug.

---

## Output location

- Default: `data/catalog_inventory/generated/source_check_results.parquet`
- Snapshots GCS: `gs://<CATALOG_INVENTORY_GCS_PREFIX>/source-check/snapshots/`
- Artifact Actions: disponibile come `source-check-results` su ogni run del workflow `source-check.yml`
