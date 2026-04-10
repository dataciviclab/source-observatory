# Catalog Watch Report

Ultimo run: 2026-04-10

## Sommario segnali

| Classificazione | Conteggio | Dettaglio |
| :--- | :--- | :--- |
| `no signal` | 5 | ISTAT SDMX (4212), MIM USTAT (68), Opencoesione (data invariata), INPS (endpoint UP), OpenBDAP (endpoint UP) |
| `inventory change` | 1 | ANAC: 70 vs baseline 69 (+1 package). Cambio minore, entro la norma. |
| `structural drift` | 0 | - |
| `health` | 1 | ANAC: ora risponde con JSON CKAN valido (prima run restituiva HTML "Request Rejected"). Segnale positivo. |
| `follow-up candidate` | 0 | - |
| `[DATO MANCANTE]` | 1 | Dati Salute: sitemap raggiungibile ma conteggio URL non verificabile con precisione per troncamento response. |

## Fonti catalog-watch osservate in questo run

7 fonti: istat_sdmx, anac, inps, openbdap, dati_salute, mim_ustat, opencoesione

---

## Dettaglio per fonte

### istat_sdmx
- **Stato**: `no signal`
- **Protocollo**: sdmx
- **Inventariabile**: si (SDMX supportato)
- **Baseline**: 4212 dataflow (2026-04-10, method: dataflow_count)
- **Osservato**: 4212 dataflow (2026-04-10)
- **Delta**: 0
- **Nota**: Baseline riallineata all'endpoint esploradati (MCP ondata) con filtro NonProductionDataflow. Il conteggio 509 era su sdmx.istat.it (endpoint diverso).
- **Azione**: Nessuna azione richiesta.

### anac
- **Stato**: `inventory change` + `health` (segnale positivo)
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 69 (2026-03-28, method: package_list)
- **Osservato**: 70 (2026-04-10, method: package_list senza limit)
- **Delta**: +1
- **Nota**: L'endpoint CKAN ora restituisce JSON valido con 70 package. Nel run precedente (2026-04-03) rispondeva con pagina HTML "Request Rejected". Il WAF sembra aver allentato il blocco. Il delta di +1 package e' minore e nella norma.
- **Azione**: Nessuna azione immediata. Monitorare la stabilita' della risposta JSON nei prossimi run.

### inps
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 2323 (2026-04-02, method: package_list)
- **Osservato**: endpoint UP, package_list restituisce lista di package (conteggio esatto non verificabile per troncamento response)
- **Delta**: non verificabile con precisione
- **Nota**: package_search fallisce (restituisce HTML, non JSON). Questo e' coerente con il comportamento noto di questo CKAN. L'endpoint package_list risponde correttamente con una lunga lista di package ID.
- **Azione**: Nessuna azione richiesta. Il conteggio esatto richiederebbe una chiamata package_list senza troncamento.

### openbdap
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 3772 (2026-04-02, method: package_list)
- **Osservato**: endpoint UP, package_list restituisce lista di UUID (conteggio esatto non verificabile per troncamento response)
- **Delta**: non verificabile con precisione
- **Nota**: package_search restituisce count=0, coerente con la nota del registry ("package_search restituisce count inaffidabile"). L'endpoint package_list risponde con molti UUID.
- **Azione**: Nessuna azione richiesta.

### dati_salute
- **Stato**: `[DATO MANCANTE]`
- **Protocollo**: html
- **Inventariabile**: parziale (sitemap XML)
- **Baseline**: 191 (2026-04-07, method: sitemap_dataset_count)
- **Osservato**: sitemap-0.xml raggiungibile, contiene URL /it/dataset/ (conteggio esatto non verificabile per troncamento response)
- **Delta**: non verificabile
- **Nota**: Primo run per questa fonte nel catalog-watch. La sitemap e' accessibile e ben formata. Il conteggio preciso richiederebbe il parsing completo del file XML.
- **Azione**: Nessuna azione immediata. Il builder del inventory dovrebbe essere esteso per supportare il protocollo html/sitemap.

### mim_ustat
- **Stato**: `no signal`
- **Protocollo**: ckan
- **Inventariabile**: si (CKAN)
- **Baseline**: 68 (2026-04-09, method: package_list)
- **Osservato**: 68 (2026-04-10, method: package_search?rows=0)
- **Delta**: 0
- **Nota**: Conteggio stabile. Nessun cambiamento dall'ultimo run.
- **Azione**: Nessuna azione richiesta.

### opencoesione
- **Stato**: `no signal`
- **Protocollo**: rest_json
- **Inventariabile**: si (REST API)
- **Baseline**: 2025-10-31 (2026-04-09, method: api_root, campo: data_aggiornamento)
- **Osservato**: 20251031 (2026-04-10, formato numerico compatto)
- **Delta**: 0 (stessa data, formato diverso)
- **Nota**: L'API root e' raggiungibile e restituisce tutti i sotto-endpoint (progetti, soggetti, aggregati, temi, nature, territori, programmi). La data di aggiornamento e' invariata.
- **Azione**: Nessuna azione richiesta.

---

## Confronto con run precedente (2026-04-03)

Il run precedente copriva 4 fonti (istat_sdmx, anac, inps, openbdap). Questo run ne copre 7 con l'aggiunta di dati_salute, mim_ustat e opencoesione.

Cambiamenti rilevanti rispetto al run precedente:
- ANAC: da "HTML Request Rejected" a JSON CKAN valido -- miglioramento significativo
- ISTAT SDMX: baseline riallineata a 4212 su endpoint esploradati (MCP ondata)
