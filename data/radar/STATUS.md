# Stato Radar

Ultimo run: 2026-06-12

## Sommario

- Fonti controllate: 31
- GREEN: 27
- YELLOW: 4
- RED: 0

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 30 |
| portal | 1 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 4 | Salute della fonte senza segnali di inventario |
| catalog-watch | 27 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | YELLOW | - | istat_gini_regionale, istat_housing_crowding, istat_ipab_aree, istat_pil_territoriale, popolazione_istat_comunale_2019_2025 |
| anac | catalog | ckan | catalog-watch | GREEN | 200 | - |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps_pensioni_trimestrale, pensioni_pa_dag |
| openbdap | catalog | ckan | catalog-watch | YELLOW | - | bdap_anagrafe_enti, bdap_entrate_stato, bdap_lea, bdap_spese_stato, dipendenti_pubblici |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim_alunni_corso_eta, mim_anagrafica_scuole_statali |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | camera_deputati_legislature, camera_votazioni_sparql |
| dati_senato | catalog | sparql | catalog-watch | GREEN | 200 | - |
| dati_cultura | catalog | sparql | catalog-watch | GREEN | 200 | - |
| ispra_linked_data | catalog | sparql | catalog-watch | GREEN | 200 | ispra_consumo_suolo, ispra_ru_base, ispra_ru_costi_kg, ispra_ru_costi_procapite |
| consip_open_data | catalog | ckan | catalog-watch | YELLOW | - | - |
| lavoro_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mur_ustat | catalog | ckan | catalog-watch | GREEN | 200 | mur_contribuzione_universitaria |
| opencoesione | catalog | ckan | catalog-watch | GREEN | 200 | opencoesione_progetti |
| mef_irpef | catalog | html | catalog-watch | YELLOW | - | irpef_comunale, mef_irpef_regionale |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | opencivitas_fsc_2025_rso |
| aifa | catalog | html | catalog-watch | GREEN | 200 | aifa_spesa_consumo |
| dait | catalog | html | radar-only | GREEN | 200 | - |
| mit_opendata | catalog | ckan | catalog-watch | GREEN | 200 | mit_incidentalita_mensile, mit_opere_incompiute_2020 |
| openga | catalog | ckan | catalog-watch | GREEN | 200 | openga_ricorsi_cds |
| giustizia_statistiche | catalog | html | catalog-watch | GREEN | 200 | civile_flussi, giustizia_penale_indicatori |
| cortecostituzionale | catalog | html | catalog-watch | GREEN | 200 | - |
| terna_opendata | catalog | rest | radar-only | GREEN | 200 | terna_electricity_by_source |
| ministero_interno | catalog | ckan | catalog-watch | GREEN | 200 | - |
| agid | catalog | ckan | catalog-watch | GREEN | 200 | - |
| noipa_sparql | catalog | sparql | radar-only | GREEN | 200 | - |
| mimit_rna | catalog | ckan | catalog-watch | GREEN | 200 | - |
| ministero_salute | catalog | ckan | catalog-watch | GREEN | 200 | reparti_ricovero, strutture_asl, strutture_ricovero_asl |
| agcm | catalog | ckan | catalog-watch | GREEN | 200 | - |
| unioncamere | catalog | ckan | catalog-watch | GREEN | 200 | - |
| pagopa | catalog | ckan | catalog-watch | GREEN | 200 | - |

## Note

- `istat_sdmx`: Timeout (ConnectTimeout)
- `openbdap`: Retry timeout/connection: Timeout (ConnectTimeout)
- `consip_open_data`: Retry timeout/connection: Timeout (ConnectTimeout)
- `mef_irpef`: Retry timeout/connection: Timeout (ConnectTimeout)
- `opencivitas`: HTTP 200 | content-type: text/html; charset=utf-8 | url finale: https://www.opencivitas.it/it/open-data | SSL verify failed; fallback verify=False used (SSLError)
- `aifa`: HTTP 200 | content-type: text/html;charset=UTF-8 | url finale: https://www.aifa.gov.it/dati-aifa | SSL verify failed; fallback verify=False used (SSLError)
