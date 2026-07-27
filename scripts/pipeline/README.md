# Pipeline SO — Architettura per protocollo

## Principio

Ogni protocollo (CKAN, HTML, SDMX, SPARQL, REST) produce tipi di dato
diversi e va validato diversamente. Un validatore uniforme (HEAD + sniff CSV)
funziona per CKAN/HTML ma produce falsi negativi su SDMX e SPARQL.

## Flusso

```
registry → collector (per protocollo) → inventory.parquet
  → merge (raggruppa item in dataset logici)
    → dispatcher (per protocollo):
      ├── validate_ckan.py     → HEAD CSV + sniff colonne
      ├── validate_html.py     → HEAD CSV + sniff colonne (come CKAN)
      ├── validate_sdmx.py     → verifica endpoint dataflow + dimensioni
      ├── validate_sparql.py   → COUNT query + classi disponibili
      └── validate_rest.py     → HEAD endpoint + sample response
    → validated.parquet
```

## Contratto output comune

Tutti i validator producono un dict con questi campi:

```python
{
    # Comuni (sempre presenti)
    "dataset_group": str,       # gruppo logico dopo merge
    "source_id": str,           # fonte di origine
    "protocol": str,            # ckan | html | sdmx | sparql | rest
    "item_count": int,          # quanti item raw in questo gruppo
    "reachable": bool,          # il dato è accessibile?
    "format": str | None,       # formato del dato
    "error": str | None,        # se reachable=False, perché
    "validated_at": str,        # timestamp ISO

    # Per protocolli tabulari (CKAN, HTML, REST-CSV)
    "url": str | None,          # URL del file
    "columns": list[str] | None,# nomi colonna sniffati
    "num_columns": int | None,  # conteggio colonne
    "delimiter": str | None,    # separatore CSV
    "content_type": str | None, # Content-Type HTTP
    "encoding": str | None,     # encoding rilevato

    # Per SDMX
    "endpoint": str | None,     # URL endpoint dataflow
    "dataflow_id": str | None,  # ID del dataflow
    "dimensions": list[str],    # dimensioni disponibili
    "year_min": int | None,     # copertura temporale
    "year_max": int | None,
    "granularity": str | None,  # nuts0 | nuts1 | nuts2 | nuts3

    # Per SPARQL
    "sparql_endpoint": str | None,
    "triple_count": int | None, # risultati COUNT
    "classes": list[str],       # classi disponibili
}
```

## Dispatcher

`run_pipeline.py` raggruppa per `dataset_group`, determina il protocollo
dal primo item del gruppo, e chiama il validator corrispondente.

```python
VALIDATORS = {
    "ckan":  validate_ckan_group,
    "html":  validate_html_group,
    "sdmx":  validate_sdmx_group,
    "sparql": validate_sparql_group,
    "rest":  validate_rest_group,
}
```

Cada validatore è un modulo separato in `pipeline/validate_*.py`,
importabile indipendentemente e testabile con i propri test.

## Vantaggi

1. SDMX non viene segnato "0% reachable" — viene validato con metriche SDMX
2. SPARQL non viene ignorato — si sa quante triple ha
3. Ogni protocollo evolve indipendentemente
4. I test sono isolati per validatore
5. Aggiungere un nuovo protocollo = nuovo modulo + dispatcher
