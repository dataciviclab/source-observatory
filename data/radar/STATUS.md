# Stato Radar

Ultimo run: 2026-04-05

## Sommario

- Fonti controllate: 5
- GREEN: 3
- YELLOW: 1
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 4 |
| portal | 1 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 1 | Salute della fonte senza segnali di inventario |
| catalog-watch | 4 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | RED | 500 | popolazione-istat |
| anac | catalog | ckan | catalog-watch | YELLOW | 403 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | pens_2017, pens_2024 |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | dipendenti-pubblici, opencoesione-pagamenti-ue-2014-2020 |
| dati_camera | portal | sparql | radar-only | GREEN | 200 | - |

## Note

- `istat_sdmx`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://sdmx.istat.it/SDMXWS/rest/dataflow/IT1 | Endpoint SDMX ricco e ad alto valore per scouting e source-check.
- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | Catalogo CKAN piccolo ma pulito, adatto a segnali leggibili.
