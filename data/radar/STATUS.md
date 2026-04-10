# Stato Radar

Ultimo run: 2026-04-10

## Sommario

- Fonti controllate: 11
- GREEN: 8
- YELLOW: 2
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 7 |
| portal | 4 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 4 | Salute della fonte senza segnali di inventario |
| catalog-watch | 7 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | YELLOW | - | popolazione-istat |
| anac | catalog | ckan | catalog-watch | YELLOW | 200 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | pens_2017, pens_2024 |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | dipendenti-pubblici, opencoesione-pagamenti-ue-2014-2020 |
| dati_salute | catalog | html | catalog-watch | RED | - | - |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | portal | html | radar-only | GREEN | 200 | mim-alunni-corso-eta |
| dati_camera | portal | sparql | radar-only | GREEN | 200 | - |
| consip_open_data | portal | ckan | radar-only | GREEN | 200 | - |
| mim_ustat | catalog | ckan | catalog-watch | GREEN | 200 | - |
| opencoesione | catalog | rest | catalog-watch | GREEN | 200 | opencoesione-pagamenti-ue-2014-2020 |

## Note

- `istat_sdmx`: Timeout (ReadTimeout)
- `anac`: HTTP 200 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | CKAN API returned non-JSON content
- `dati_salute`: Connection error (ConnectionError)
