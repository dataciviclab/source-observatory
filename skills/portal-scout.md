---
name: portal-scout
description: Dato un URL, identifica protocollo, verifica se è catalogo osservabile e decide se aggiungere al registry.
license: MIT
metadata:
  version: "1.0"
  owner: "DataCivicLab"
---

# Skill: portal-scout

Verifica se un portale è un catalogo osservabile e merita di essere aggiunto al registry.

## Entry

- **Input**: URL di un portale (`https://...`)
- **Precondizione**: URL fornito, non ancora nel registry (verificato con pre-check)

## Pre-check obbligatorio

Prima di qualsiasi probe, verifica che il portale non sia già nel sistema:

```
1. so_find_by_url(<URL>)     → è già in source_check o inventory?
2. so_source_report(<source_id>) → già nel registry? (identity + verdict inclusi)
```

**Se già catalogato (source_id noto)**: invece dei passaggi separati, usa
`so_source_report(<source_id>)` per un quadro completo (identity + health +
inventory + source_check + signals + verdict) in una chiamata sola.
Poi restituisci `already_known` con riferimento all'entry registry.

## Steps

### 1. Probe base

```
toolkit_probe_url(<URL>)       → status, content-type, reachability
```

Se non raggiungibile → `no-go` (fonte down).

### 2. Rileva protocollo

Usa `toolkit_html_extract_links` per vedere se la pagina è HTML con link a dati:

```
toolkit_html_extract_links(<URL>) → lista link, formati, total
```

Poi testa i protocolli noti nell'ordine:

**CKAN** — prova `/api/3/action/package_list`:
```
toolkit_probe_url(<base_url>/api/3/action/package_list?limit=1)
   → se 200 + JSON: CKAN confermato
```

**CKAN — verifica enumerateabilità** (solo se confermato CKAN):
```
toolkit_ckan_package_show(<base_url>, '<un_package_id_noto>')
   → se success: catalog-watch confermato
```

**SDMX** — prova l'endpoint REST:
```
toolkit_probe_url(<base_url>/rest/dataflow)
   → se 200 + XML/JSON: SDMX confermato
```

**SPARQL** — verifica endpoint su path standard:
```
toolkit_probe_url(<base_url>/sparql?query=SELECT+1)
   → se 200 + content-type application/sparql-results+json: sparql confermato
   → se 200 + text/html: prova <base_url>/query o <base_url>/sparql
   → se 400 + JSON: sparql presente (richiede query valida)
```

**HTML generico** — se CKAN/SPARQL/SDMX falliti ma `toolkit_html_extract_links` trova link CSV/JSON/XLSX:
```
→ HTML confermato, osservabile ma enumerateabilità limitata
→ observation_mode suggerito: radar-only
```

## Decisione

| Condizione | Verdict |
|---|---|
| CKAN + package_list funziona | `go registry — catalog-watch` |
| SDMX + dataflow accessibili | `go registry — catalog-watch` |
| SPARQL endpoint risponde | `go registry — catalog-watch` |
| HTML con link dati, enumerateabilità limitata | `go registry — radar-only` |
| Rilevato ma enumerate non difendibile | `need-more-info` |
| Non raggiungibile / WAF / errore strutturale | `no-go` |

## Output

```markdown
## portal-scout: <URL>

**Protocollo rilevato**: [CKAN / SDMX / SPARQL / HTML / unknown]
**Catalogo**: [sì / no / parziale]
**Enumerateabile**: [sì / no / limitato]
**Già in registry**: [sì / no]
**Observation mode suggerito**: [catalog-watch / radar-only]

**Probe results**:
- reachability: [200 / timeout / errore]
- content-type: [...]
- protocollo confermato da: [package_list / dataflow / endpoint / link]

**Verdict**: [go registry / no-go / need-more-info / already_known]

**Next step**: [aprire issue per aggiungere / skip / probe ulteriore]
```

## Exit

- `go registry` → aprire issue SO con richiesta di aggiunta al registry (observation_mode suggerito)
- `already_known` → indicare source_id esistente e suo stato
- `no-go` / `need-more-info` → stop, nessuna azione ulteriore
