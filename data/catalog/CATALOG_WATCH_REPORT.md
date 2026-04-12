# Catalog Watch Report

Ultimo run: 2026-04-12

## Sommario segnali

| Classificazione | Conteggio | Dettaglio |
| :--- | :--- | :--- |
| `no signal` | 9 | ISTAT SDMX (4212), INPS (endpoint UP), OpenBDAP (3772), Dati Salute (191), Camera SPARQL (104), ISPRA Linked Data (66), Consip (17), Lavoro OpenData (159), MIM USTAT (68), Opencoesione (data invariata) |
| `health` | 1 | ANAC: WAF "Request Rejected" torna attivo (prima restituiva HTML). Regressione rispetto al run 2026-04-10 che mostrava JSON valido. |
| `inventory change` | 0 | - |
| `structural drift` | 0 | - |
| `follow-up candidate` | 0 | - |
| `[DATO MANCANTE]` | 0 | - |

## Fonti catalog-watch osservate in questo run

11 fonti: istat_sdmx, anac, inps, openbdap, dati_salute, dati_camera, ispra_linked_data, consip_open_data, lavoro_opendata, mim_ustat, opencoesione

---

## Dettaglio per fonte

### istat_sdmx
- **Stato**: `no signal`
- **Protocollo**: sdmx
- **Inventariabile**: si (SDMX supportato)
- **Baseline**: 4212 dataflow (2026-04-10, method: dataflow_count)
- **Osservato**: 4212 dataflow (2026-04-12, method: discover_dataflows MCP)
- **Delta**: 0
- **Nota**: Conteggio stabile. Endpoint esploradati risponde correttamente.
- **Azione**: Nessuna azione richiesta.

### anac
- **Stato**: `health` (regressione)
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 69 (2026-03-28, method: package_list)
- **Osservato**: WAF "Request Rejected" -- risposta HTML, non JSON
- **Delta**: non verificabile
- **Nota**: L'endpoint CKAN torna a restituire pagina HTML "Request Rejected" (support ID: aa3c7223-1749-4b9f-b110-e9c421b37be0). Nel run 2026-04-10 rispondeva con JSON valido (70 package). Il WAF ha riattivato il blocco. Situazione instabile.
- **Azione**: Monitorare nei prossimi run. Se il blocco WAF persiste, valutare declassamento a `radar-only` o ricerca di endpoint alternativo.

### inps
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 2323 (2026-04-02, method: package_list)
- **Osservato**: package_search restituisce payload vuoto (comportamento noto); package_list con limit=1 conferma endpoint UP e response success=true
- **Delta**: non applicabile (package_search inaffidabile per questa fonte)
- **Nota**: package_search restituisce payload vuoto, coerente con il comportamento noto di questo CKAN. L'endpoint package_list risponde correttamente.
- **Azione**: Nessuna azione richiesta.

### openbdap
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 3772 (2026-04-02, method: package_list)
- **Osservato**: package_search restituisce count=0 (comportamento noto); package_list con limit=1 restituisce 3772 items (truncated)
- **Delta**: 0
- **Nota**: package_search restituisce count=0, coerente con la nota del registry ("package_search restituisce count inaffidabile"). Il package_list conferma 3772 items, in linea con la baseline.
- **Azione**: Nessuna azione richiesta.

### dati_salute
- **Stato**: `no signal`
- **Protocollo**: html
- **Inventariabile**: si (sitemap XML)
- **Baseline**: 191 (2026-04-07, method: sitemap_dataset_count)
- **Osservato**: 191 URL /it/dataset/ dal sitemap-0.xml (2026-04-12)
- **Delta**: 0
- **Nota**: Sitemap raggiungibile e ben formata. Conteggio stabile.
- **Azione**: Nessuna azione richiesta.

### dati_camera
- **Stato**: `no signal`
- **Protocollo**: sparql
- **Inventariabile**: si (SPARQL)
- **Baseline**: 104 (2026-04-11, method: sparql_query, query: camera_dcat)
- **Osservato**: 104 dataset (2026-04-12)
- **Delta**: 0
- **Nota**: Endpoint SPARQL risponde correttamente. Conteggio stabile.
- **Azione**: Nessuna azione richiesta.

### ispra_linked_data
- **Stato**: `no signal`
- **Protocollo**: sparql
- **Inventariabile**: si (SPARQL)
- **Baseline**: 66 (2026-04-11, method: sparql_query, query: dcat_datasets)
- **Osservato**: 66 dataset (2026-04-12)
- **Delta**: 0
- **Nota**: Endpoint SPARQL risponde correttamente. Conteggio stabile.
- **Azione**: Nessuna azione richiesta.

### consip_open_data
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 17 (2026-04-10, method: package_list)
- **Osservato**: 17 (2026-04-12, method: package_search?rows=0)
- **Delta**: 0
- **Nota**: package_search risponde correttamente con count=17. Valore in linea con la baseline.
- **Azione**: Nessuna azione richiesta.

### lavoro_opendata
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN, SPOD)
- **Baseline**: 159 (2026-04-11, method: package_list)
- **Osservato**: package_search restituisce count=0 (comportamento noto); package_list con limit=1 conferma 159 items (truncated)
- **Delta**: 0
- **Nota**: package_search restituisce count=0, coerente con la configurazione CKAN_SKIP_PACKAGE_SEARCH. Il package_list conferma 159 items, stabile rispetto alla baseline.
- **Azione**: Nessuna azione richiesta.

### mim_ustat
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 68 (2026-04-09, method: package_list)
- **Osservato**: 68 (2026-04-12, method: package_search?rows=0)
- **Delta**: 0
- **Nota**: Conteggio stabile. Risposta JSON valida.
- **Azione**: Nessuna azione richiesta.

### opencoesione
- **Stato**: `no signal`
- **Protocollo**: rest_json
- **Inventariabile**: si (REST API)
- **Baseline**: 2025-10-31 (2026-04-09, method: api_root, campo: data_aggiornamento)
- **Osservato**: 20251031 (2026-04-12, formato numerico compatto)
- **Delta**: 0 (stessa data, formato diverso)
- **Nota**: L'API root e' raggiungibile e restituisce tutti i sotto-endpoint. La data di aggiornamento e' invariata.
- **Azione**: Nessuna azione richiesta.

---

## Confronto con run precedente (2026-04-10)

Il run precedente copriva 7 fonti. Questo run copre 11 fonti con l'aggiunta di dati_camera, ispra_linked_data, consip_open_data e lavoro_opendata.

Cambiamenti rilevanti rispetto al run precedente:
- ANAC: da JSON CKAN valido a "Request Rejected" HTML -- regressione WAF significativa
- ISTAT SDMX: conteggio stabile a 4212
- Opencoesione: data invariata
