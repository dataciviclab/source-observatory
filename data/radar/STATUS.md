# Stato Radar

Ultimo run: 2026-04-01

## Sommario

- Fonti controllate: 3
- GREEN: 2
- YELLOW: 1
- RED: 0

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 3 |
| portal | 0 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 0 | Salute della fonte senza segnali di inventario |
| catalog-watch | 3 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | GREEN | 200 | popolazione-istat |
| anac | catalog | ckan | catalog-watch | YELLOW | 403 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | pens_2017, pens_2024 |

## Note

- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | Catalogo CKAN piccolo ma pulito, adatto a segnali leggibili.
