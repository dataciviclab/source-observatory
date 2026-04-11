# Stato Radar

Ultimo run: 2026-04-11

## Sommario

- Fonti controllate: 11
- GREEN: 7
- YELLOW: 3
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 8 |
| portal | 3 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 3 | Salute della fonte senza segnali di inventario |
| catalog-watch | 8 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | GREEN | 200 | popolazione-istat |
| anac | catalog | ckan | catalog-watch | YELLOW | 403 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | pens_2017, pens_2024 |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | dipendenti-pubblici, opencoesione-pagamenti-ue-2014-2020 |
| dati_salute | catalog | html | catalog-watch | RED | - | - |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | portal | html | radar-only | GREEN | 200 | mim-alunni-corso-eta |
| dati_camera | portal | sparql | radar-only | GREEN | 200 | - |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mim_ustat | catalog | ckan | catalog-watch | YELLOW | - | - |
| opencoesione | catalog | rest | catalog-watch | YELLOW | 403 | opencoesione-pagamenti-ue-2014-2020 |

## Note

- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | Catalogo CKAN piccolo ma pulito, adatto a segnali leggibili.
- `dati_salute`: SSL verify failed; fallback connection error (SSLError)
- `mim_ustat`: Timeout (ConnectTimeout)
- `opencoesione`: HTTP 403 | content-type: text/html; charset=utf-8 | url finale: https://opencoesione.gov.it/it/api/ | API REST custom con endpoint aggregati e data_aggiornamento. Usare per change detection e trigger re-run del candidate DI.
