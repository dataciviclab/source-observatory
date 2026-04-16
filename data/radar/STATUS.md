# Stato Radar

Ultimo run: 2026-04-16

## Sommario

- Fonti controllate: 13
- GREEN: 8
- YELLOW: 4
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 11 |
| portal | 2 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 4 | Salute della fonte senza segnali di inventario |
| catalog-watch | 9 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | YELLOW | - | istat-gini-regionale, istat-housing-crowding, istat-ipab-aree |
| anac | catalog | ckan | radar-only | YELLOW | 403 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps-pensioni |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | dipendenti-pubblici, bdap-lea |
| dati_salute | catalog | html | radar-only | RED | - | - |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | portal | html | radar-only | GREEN | 200 | mim-alunni-corso-eta |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | - |
| ispra_linked_data | catalog | sparql | catalog-watch | GREEN | 200 | - |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| lavoro_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mur_ustat | catalog | ckan | catalog-watch | YELLOW | - | - |
| opencoesione | catalog | rest | catalog-watch | YELLOW | 403 | opencoesione-pagamenti-ue-2014-2020 |

## Note

- `istat_sdmx`: Timeout (ReadTimeout)
- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | WAF blocca endpoint CKAN. Declassato a radar-only finche' non disponibile endpoint alternativo o accesso istituzionale.
- `dati_salute`: SSL verify failed; fallback connection error (SSLError)
- `mur_ustat`: Timeout (ConnectTimeout)
- `opencoesione`: HTTP 403 | content-type: text/html; charset=utf-8 | url finale: https://opencoesione.gov.it/it/api/ | API REST custom con endpoint aggregati e data_aggiornamento. Usare per change detection e trigger re-run del candidate DI.
