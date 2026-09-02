# Stato Radar

Ultimo run: 2026-09-02

## Sommario

- Fonti controllate: 36
- GREEN: 35
- YELLOW: 0
- RED: 1

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 36 |
| portal | 0 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 4 | Salute della fonte senza segnali di inventario |
| catalog-watch | 32 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | GREEN | 200 | istat_gini_regionale, istat_housing_crowding, istat_ipab_aree, istat_occupazione_provinciale, istat_pil_territoriale, popolazione_istat_comunale_2019_2025 |
| anac | catalog | ckan | catalog-watch | GREEN | 200 | anac_aggiudicatari, anac_aggiudicazioni, anac_bandi_gara, anac_collaudo, anac_cup, anac_partecipanti, anac_stati_avanzamento, anac_subappalti |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps_pensioni_trimestrale, pensioni_pa_dag |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | bdap_anagrafe_enti, bdap_entrate_stato, bdap_lea, bdap_pagamenti_stato, bdap_spese_stato, dipendenti_pubblici |
| inail_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim_alunni_corso_eta, mim_anagrafica_scuole_statali, mim_scuola_infanzia |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | silos_infrastrutture |
| dati_senato | catalog | sparql | catalog-watch | GREEN | 200 | senato_anagrafica, senato_ddl, senato_firmatari |
| dati_cultura | catalog | sparql | catalog-watch | GREEN | 200 | - |
| ispra_linked_data | catalog | sparql | catalog-watch | RED | - | ispra_consumo_suolo, ispra_ru_base, ispra_ru_costi_kg, ispra_ru_costi_procapite |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| lavoro_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| mur_ustat | catalog | ckan | catalog-watch | GREEN | 200 | mur_contribuzione_universitaria, mur_immatricolati, mur_iscritti |
| opencoesione | catalog | ckan | catalog-watch | GREEN | 200 | opencoesione_progetti |
| mef_irpef | catalog | html | catalog-watch | GREEN | 200 | irpef_comunale, mef_irpef_regionale |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | opencivitas_fsc_2025_rso, opencivitas_fsc_enti_rso, opencivitas_glossario, opencivitas_indicatori |
| aifa | catalog | html | catalog-watch | GREEN | 200 | aifa_spesa_consumo |
| dait | catalog | html | radar-only | GREEN | 200 | dait_amministratori_locali |
| eligendo | catalog | html | radar-only | GREEN | 200 | elezioni_comunali, elezioni_europee, elezioni_referendum, elezioni_regionali |
| mit_opendata | catalog | ckan | catalog-watch | GREEN | 200 | mit_incidentalita_mensile, mit_opere_incompiute_2020 |
| openga | catalog | ckan | catalog-watch | GREEN | 200 | ga_decreti, ga_ordinanze, ga_sentenze, openga_ricorsi_appalto, openga_ricorsi_cds |
| giustizia_statistiche | catalog | html | catalog-watch | GREEN | 200 | civile_flussi, giustizia_penale_indicatori, intercettazioni, monitoraggio_mensile_civile, penale_flussi |
| cortecostituzionale | catalog | html | catalog-watch | GREEN | 200 | - |
| terna_opendata | catalog | rest | radar-only | GREEN | 200 | terna_electrical_energy_by_sector, terna_electricity_by_source |
| ministero_interno | catalog | ckan | catalog-watch | GREEN | 200 | - |
| agid | catalog | ckan | catalog-watch | GREEN | 200 | ipa_aree_organizzative_omogenee, ipa_enti, ipa_unita_organizzative |
| noipa_sparql | catalog | sparql | catalog-watch | GREEN | 200 | - |
| mimit_rna | catalog | ckan | catalog-watch | GREEN | 200 | rna_aiuti_stato, rna_misure |
| ministero_turismo_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| ministero_salute | catalog | ckan | catalog-watch | GREEN | 200 | farmacie, personale_ssn, reparti_ricovero, strutture_asl, strutture_ricovero_asl |
| agcm | catalog | ckan | catalog-watch | GREEN | 200 | - |
| unioncamere | catalog | ckan | radar-only | GREEN | 200 | - |
| pagopa | catalog | ckan | catalog-watch | GREEN | 200 | - |
| art_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |
| aci | catalog | ckan | catalog-watch | GREEN | 200 | aci_prime_iscrizioni_autovetture |
| adm_opendata | catalog | ckan | catalog-watch | GREEN | 200 | - |

## Note

- `ispra_linked_data`: Connection error (ConnectionError)
- `opencivitas`: HTTP 200 | content-type: text/html; charset=utf-8 | url finale: https://www.opencivitas.it/it/open-data | SSL verify failed; fallback verify=False used (SSLError)
