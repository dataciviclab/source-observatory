# Stato Radar

Ultimo run: 2026-06-19

## Sommario

- Fonti controllate: 32
- GREEN: 30
- YELLOW: 1
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 31 |
| portal | 1 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 4 | Salute della fonte senza segnali di inventario |
| catalog-watch | 28 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | YELLOW | - | istat_gini_regionale, istat_housing_crowding, istat_ipab_aree, istat_pil_territoriale, popolazione_istat_comunale_2019_2025 |
| anac | catalog | ckan | catalog-watch | GREEN | 200 | anac_bandi_gara |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps_pensioni_trimestrale, pensioni_pa_dag |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | bdap_anagrafe_enti, bdap_entrate_stato, bdap_lea, bdap_spese_stato, dipendenti_pubblici |
| inail_opendata | portal | aem | radar-only | GREEN | 200 | - |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim_alunni_corso_eta, mim_anagrafica_scuole_statali |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | camera_deputati_legislature, camera_votazioni_sparql |
| dati_senato | catalog | sparql | catalog-watch | GREEN | 200 | - |
| dati_cultura | catalog | sparql | catalog-watch | GREEN | 200 | - |
| ispra_linked_data | catalog | sparql | catalog-watch | GREEN | 200 | ispra_consumo_suolo, ispra_ru_base, ispra_ru_costi_kg, ispra_ru_costi_procapite |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| lavoro_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mur_ustat | catalog | ckan | catalog-watch | GREEN | 200 | mur_contribuzione_universitaria |
| opencoesione | catalog | ckan | catalog-watch | GREEN | 200 | opencoesione_progetti |
| mef_irpef | catalog | html | catalog-watch | GREEN | 200 | irpef_comunale, mef_irpef_regionale |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | opencivitas_fsc_2025_rso |
| aifa | catalog | html | catalog-watch | GREEN | 200 | aifa_spesa_consumo |
| dait | catalog | html | radar-only | GREEN | 200 | dait_amministratori_locali |
| mit_opendata | catalog | ckan | catalog-watch | RED | 500 | mit_incidentalita_mensile, mit_opere_incompiute_2020 |
| openga | catalog | ckan | catalog-watch | GREEN | 200 | openga_ricorsi_appalto, openga_ricorsi_cds |
| giustizia_statistiche | catalog | html | catalog-watch | GREEN | 200 | civile_flussi, giustizia_penale_indicatori |
| cortecostituzionale | catalog | html | catalog-watch | GREEN | 200 | - |
| terna_opendata | catalog | rest | radar-only | GREEN | 200 | terna_electricity_by_source |
| ministero_interno | catalog | ckan | catalog-watch | GREEN | 200 | - |
| agid | catalog | ckan | catalog-watch | GREEN | 200 | ipa_istat_mapping |
| noipa_sparql | catalog | sparql | radar-only | GREEN | 200 | - |
| mimit_rna | catalog | ckan | catalog-watch | GREEN | 200 | - |
| ministero_salute | catalog | ckan | catalog-watch | GREEN | 200 | reparti_ricovero, strutture_asl, strutture_ricovero_asl |
| agcm | catalog | ckan | catalog-watch | GREEN | 200 | - |
| unioncamere | catalog | ckan | catalog-watch | GREEN | 200 | - |
| pagopa | catalog | ckan | catalog-watch | GREEN | 200 | - |
| aci | catalog | ckan | catalog-watch | GREEN | 200 | - |

## Note

- `istat_sdmx`: Timeout (ReadTimeout)
- `opencivitas`: HTTP 200 | content-type: text/html; charset=utf-8 | url finale: https://www.opencivitas.it/it/open-data | SSL verify failed; fallback verify=False used (SSLError)
- `aifa`: HTTP 200 | content-type: text/html;charset=UTF-8 | url finale: https://www.aifa.gov.it/dati-aifa | SSL verify failed; fallback verify=False used (SSLError)
- `mit_opendata`: HTTP 500 | content-type: text/plain; charset=UTF-8 | url finale: https://dati.mit.gov.it/catalog/api/3/action/package_list?limit=1 | Portale CKAN MIT — 67 dataset su trasporti, infrastrutture, incidentalità, veicoli, opere pubbliche. Include dataset già in uso dal Lab (mit_incidentalita_mensile, mit_opere_incompiute).

- `openga`: HTTP 200 | content-type: application/json;charset=utf-8 | url finale: https://openga.giustizia-amministrativa.it/api/3/action/package_list?limit=1 | SSL verify failed; fallback verify=False used (SSLError)
