# Source Observatory — Guida Architettura

## Struttura scripts/

```
scripts/
  collectors/          # package: logica di inventory per protocollo
    base.py            # utility condivise: observatory_get, CollectorResult, strip_query
    ckan.py            # collector CKAN
    sdmx.py            # collector SDMX
    sparql.py          # collector SPARQL
  build_catalog_inventory.py   # entry point: enumera fonti → parquet
  build_catalog_signals.py     # entry point: segnali di cambiamento
  bulk_source_check.py         # entry point: enrichment e scoring per intake
  _constants.py                # costanti condivise tra script
```

## Regola fondamentale: riusa collectors/base.py

Tutti gli script che fanno chiamate HTTP **devono** usare `observatory_get()` da `collectors/base.py`, non `requests.get()` diretto. Motivo: User-Agent coerente, session management, timeout standard.

```python
# ✗ non fare
import requests
r = requests.get(url, timeout=15)

# ✓ fare
from collectors.base import observatory_get
r = observatory_get(url, timeout=15)
```

Per importare `collectors` da uno script in `scripts/`, usa:
```python
from collectors.base import observatory_get
from collectors.ckan import ckan_get_json
```

`build_catalog_inventory.py` importa direttamente da `collectors` (è un modulo di pari livello).

## Struttura di un nuovo script entry point

```python
#!/usr/bin/env python3
"""Docstring breve: cosa fa, input, output."""

from __future__ import annotations

# stdlib
# terze parti
# collectors (importazione diretta)

REPO_ROOT = Path(__file__).resolve().parents[1]

# costanti e configurazione

# funzioni private _*  (logica, no I/O)

# funzione pubblica principale (orchestrazione)

# CLI parse_args() + main()

if __name__ == "__main__":
    main()
```

## Regole

- **Un file = una responsabilità.** Entry point (`build_*`, `bulk_*`) contengono solo CLI + orchestrazione. Logica riusabile va in `collectors/` o in un modulo dedicato.
- **Funzioni private `_*`** non hanno docstring. Funzioni pubbliche hanno una riga.
- **Nessuna eccezione silenziata senza motivo.** Se catturi `Exception`, logga o restituisci un valore sentinel esplicito (es. `None`, `enrich_method: "error"`).
- **Tipi espliciti** sulle firme delle funzioni pubbliche.
- **No dipendenze nuove** senza discussione — il progetto usa `requests`, `pandas`, `pyyaml`, `duckdb`. Per parsing XML usa `xml.etree.ElementTree` stdlib.

## Aggiungere un nuovo enricher a bulk_source_check

1. Scrivi `_fetch_X()` e `_parse_X()` — restituiscono sempre il dict shape di `_EMPTY_ENRICH`
2. Aggiungi un branch in `_enrich()` con la condizione sul protocollo
3. Aggiungi la costante stringa `ENRICH_X = "x_method"` vicino a `_EMPTY_ENRICH`
4. Usa `observatory_get()` invece di `requests.get()`

## Pattern: dict shape degli enricher

Ogni enricher restituisce esattamente queste chiavi (valore `None` se non disponibile):

```python
{
    "enriched_title": str | None,
    "enriched_tags": str | None,
    "enriched_notes": str | None,
    "resource_url": str | None,
    "resource_format": str | None,
    "granularity": str | None,
    "year_min": int | None,
    "year_max": int | None,
    "enrich_method": str,   # mai None
}
```

`_EMPTY_ENRICH` in `bulk_source_check.py` è la definizione canonica di questo shape.

## Utility da collectors/base.py

### Funzioni HTTP
- `observatory_get(url, *, timeout=60, headers=None, **kwargs)` — GET con User-Agent coerente
- `get_observatory_session()` → `requests.Session` con header predefiniti

### Tipi
- `CollectorResult(rows, warning=None, summary=None)` — risultato di una collezione
- `now_utc_iso() → str` — timestamp UTC ISO per logging

### Parsing
- `strip_query(url: str) -> str` — rimuove query string
- `parse_int(value: str | None) -> int | None` — parsing sicuro
- `sparql_binding_value(binding, name) -> str | None` — estrae valore da SPARQL binding
- `compact_uri_name(uri: str | None) -> str | None` — estrae nome da URI compresso
- `append_unique(values: list[str], value: str | None)` — append non duplicato
- `inventory_cfg(source_cfg: dict) -> dict` — legge il blocco `inventory:` da config sorgente

## Schema colonne: catalog-inventory vs source-check

### Layer 1 — catalog-inventory (`catalog_inventory_latest.parquet`)
Contiene tutto ciò che è derivabile staticamente dall'inventory, senza chiamate attive alla fonte.

| Colonna | Fonte | Note |
|---|---|---|
| `source_id`, `source_kind`, `protocol` | registry | identificatori della fonte |
| `item_id`, `item_name`, `item_slug` | collector | `item_slug` = nome testuale CKAN per package_show |
| `title`, `organization`, `tags`, `notes_excerpt` | collector | metadati base dell'item |
| `issued`, `modified` | collector | date come stringhe ISO |
| `landing_page`, `distribution_url`, `format` | collector | URL e formato dichiarato |
| `api_base_url` | collector | endpoint API pre-calcolato (CKAN o SDMX root) |
| `source_url` | collector | URL endpoint di inventory |
| `captured_at` | build script | timestamp del run di inventory |

### Layer 2 — source-check (`source_check_results.parquet`)
Contiene tutto ciò che richiede chiamate attive alla fonte o inferenza sui metadati arricchiti.

| Colonna | Come si ottiene |
|---|---|
| `check_timestamp` | runtime al momento del check |
| `http_status`, `reachable`, `check_notes` | HTTP HEAD sull'URL risorsa |
| `enriched_title`, `enriched_tags`, `enriched_notes` | package_show (CKAN) / dataflow annotations (SDMX) |
| `resource_url`, `resource_format` | package_show resources / HTML scraping |
| `granularity` | inferenza regex su testo arricchito |
| `year_min`, `year_max` | extras DCAT-AP / TIME_PERIOD SDMX / regex su testo |
| `enrich_method` | stringa che identifica il metodo usato |
| `intake_score` | scoring 0-100 su granularità, anni, reachable, formato |
| `intake_candidate` | `score ≥ 40` AND `needs_review = False` |
| `needs_review` | granularità o anni non determinabili |

**Linea di confine:** se è derivabile dall'inventory senza chiamate esterne → layer 1. Se richiede una chiamata attiva alla fonte → layer 2.

## Fonti con scraping bloccato

Alcune fonti bloccano le richieste HTTP non-browser (reCAPTCHA, WAF). Sono marcate nel registry con `scraping_blocked: true`. Il source-check le salta automaticamente senza tentare HTML scraping.

Fonti attualmente bloccate: `dati_camera`, `anac`.

Per aggiungere una nuova fonte bloccata, aggiungi nel registry:
```yaml
source_id:
  scraping_blocked: true
  scraping_blocked_reason: "descrizione del blocco"
```
