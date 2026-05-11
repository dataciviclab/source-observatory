# Stato Radar

Ultimo run: 2026-05-11

## Sommario

- Fonti controllate: 16
- GREEN: 10
- YELLOW: 5
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 15 |
| portal | 1 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 3 | Salute della fonte senza segnali di inventario |
| catalog-watch | 13 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | GREEN | 200 | istat-gini-regionale, istat-housing-crowding, istat-ipab-aree |
| anac | catalog | ckan | radar-only | YELLOW | 403 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps-pensioni |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | dipendenti-pubblici, bdap-lea |
| dati_salute | catalog | html | catalog-watch | RED | - | - |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim-alunni-corso-eta |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | - |
| dati_cultura | catalog | sparql | catalog-watch | YELLOW | - | - |
| ispra_linked_data | catalog | sparql | catalog-watch | GREEN | 200 | - |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| lavoro_opendata | catalog | ckan | catalog-watch | YELLOW | 200 | - |
| mur_ustat | catalog | ckan | catalog-watch | YELLOW | - | - |
| opencoesione | catalog | rest | radar-only | YELLOW | 403 | - |
| mef_irpef | catalog | html | catalog-watch | GREEN | 200 | - |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | - |

## Note

- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | WAF blocca endpoint CKAN. Declassato a radar-only finche' non disponibile endpoint alternativo o accesso istituzionale.
- `dati_salute`: SSL verify failed; fallback connection error (SSLError)
- `dati_cultura`: Retry timeout/connection: Timeout (ConnectTimeout)
- `lavoro_opendata`: HTTP 200 | content-type: text/html | url finale: https://dati.lavoro.gov.it/SpodCkanApi/api/3/action/package_list?limit=1 | CKAN API returned non-JSON content
- `mur_ustat`: Retry timeout/connection: Timeout (ConnectTimeout)
- `opencoesione`: HTTP 403 | content-type: text/html; charset=utf-8 | url finale: https://opencoesione.gov.it/it/api/ | Portale disabilitato/ritirato. CKAN API non piu' raggiungibile (redirect a /it/ con 404 "Pagina non trovata"). Mantenuto in radar-only per eventuale monitoraggio futuro.

- `opencivitas`: HTTP 200 | content-type: text/html; charset=utf-8 | url finale: https://www.opencivitas.it/it/open-data | SSL verify failed; fallback verify=False used (SSLError)
