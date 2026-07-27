# validated.parquet — Schema

Prodotto da `scripts/pipeline/run_pipeline.py` (merge + validate).
Sostituisce il vecchio `source_check_results.parquet`.

## Colonne

| Colonna | Tipo | Sempre? | Descrizione |
|---|---|---|---|
| `dataset_group` | VARCHAR | ✅ | Slug logico del dataset (`source_id/nome-normalizzato`) |
| `source_id` | VARCHAR | ✅ | Fonte di origine |
| `protocol` | VARCHAR | ✅ | Protocollo (ckan, sdmx, sparql, html) |
| `item_count` | BIGINT | ✅ | Numero di item aggregati in questo gruppo |
| `url` | VARCHAR | solo CSV | URL della risorsa migliore (per formato) |
| `format` | VARCHAR | ✅ | Formato della risorsa (es. "csv", "csv,json") |
| `reachable` | BOOLEAN | ✅ | True/False/None (non verificato per non-CSV) |
| `status_code` | DOUBLE | solo HTTP probed | HTTP status code dalla HEAD probe |
| `content_type` | VARCHAR | solo HTTP probed | Content-Type response |
| `error` | VARCHAR | solo falliti | Messaggio errore se non reachable |
| `dataset_group_size` | DOUBLE | ✅ | Numero item nel gruppo logico |
| `dataset_group_year_min` | DOUBLE | se disponibile | Anno minimo dal merge |
| `dataset_group_year_max` | DOUBLE | se disponibile | Anno massimo dal merge |
| `note` | VARCHAR | solo non-CSV | Nota operativa (es. "Non-CSV format: zip") |
| `readiness_score` | BIGINT | ✅ | Score 0-10 |
| `columns` | VARCHAR[] | solo CSV sniffati | Nomi colonne sniffate |
| `num_columns` | DOUBLE | solo CSV sniffati | Numero colonne |
| `num_sample_rows` | DOUBLE | solo CSV sniffati | Righe campionate |
| `delimiter` | VARCHAR | solo CSV sniffati | Delimitatore sniffato |
| `encoding` | VARCHAR | solo CSV sniffati | Encoding sniffato |
| `sniff_error` | VARCHAR | solo sniff falliti | Errore sniff CSV |
| `endpoint` | VARCHAR | solo SPARQL | Endpoint SPARQL |
| `graph_uri` | VARCHAR | solo SPARQL | Named graph URI |
| `triple_count` | DOUBLE | solo SPARQL | Triple count dalla COUNT query |

## readiness_score (0-10)

```
reachable (2) + is_csv (2) + num_columns>=3 (2)/>0 (1)
+ status=200 (1) + delimiter (1) + encoding utf-8 (1) + anni_noti (1)
= 0-10

Penalità:
- sniff_error AND num_columns=0: -3  (falso CSV, es. XLSX con metadati sbagliati)
- content-type non-CSV: -1
```

## Lettura

```python
import duckdb
con = duckdb.connect()
con.execute("SELECT dataset_group, readiness_score FROM 'validated.parquet' WHERE reachable = true")
```

## Differenze col vecchio source_check_results.parquet

| Vecchio | Nuovo | Note |
|---|---|---|
| `intake_score` 0-100 | `readiness_score` 0-10 | Più semplice, 8 componenti |
| `paqa_score` | ❌ rimosso | Sostituito da sniff leggero |
| `granularity` | ❌ rimosso | Non più inferito |
| `intake_candidate` | ❌ rimosso | Sostituibile da `readiness_score >= 6` |
| `check_notes` | ❌ rimosso | Sostituito da `error` + `sniff_error` |
| — | `dataset_group` | Merge/dedup logico — nuovo |
| — | `columns[]` | Colonne sniffate — nuovo |
