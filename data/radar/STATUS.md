# Stato Radar

Ultimo run: 2026-11-07

## Sommario

- Fonti controllate: 35
- GREEN: 32
- YELLOW: 3
- RED: 0

## Tipi sorgente

| Tipo | Conteggio |
| --- | --- |
| catalog | 35 |
| portal | 0 |
| source | 0 |

## Modalita' osservazione

| Modalita' | Conteggio | Significato |
| --- | --- | --- |
| radar-only | 8 | Salute della fonte senza segnali di inventario |
| catalog-watch | 27 | Inventario e drift strutturale del catalogo |
| monitor-active | 0 | Caso ristretto con monitoraggio piu' vicino alla risorsa |

Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.

## Stato per fonte

| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |
| --- | --- | --- | --- | --- | --- | --- |
| istat_sdmx | catalog | sdmx | catalog-watch | GREEN | 200 | istat_gini_regionale, istat_housing_crowding, istat_ipab_aree, istat_occupazione_provinciale, istat_pil_territoriale, istat_prezzi_agricoli, popolazione_istat_comunale_2019_2025 |
| anac | catalog | ckan | catalog-watch | YELLOW | 403 | anac_aggiudicatari, anac_aggiudicazioni, anac_avvio_contratto, anac_bandi_gara, anac_collaudo, anac_cup, anac_fine_contratto, anac_partecipanti, anac_sospensioni, anac_stati_avanzamento, anac_subappalti, anac_varianti |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps_assegno_unico, inps_bilancio_ce, inps_bilancio_gestionale, inps_bilancio_missioni, inps_cig, inps_dipendenti_pubblici, inps_dis_coll, inps_flussi_settore, inps_lavoratori_pubblici, inps_lavoratori_redditi, inps_naspi, inps_pensionamento_flussi, inps_pensioni_liquidate, inps_pensioni_serie, inps_pensioni_trimestrale, inps_pensioni_vigenti, inps_rapporti_cessazioni, inps_rapporti_lavoro, inps_rdc_pdc, inps_retribuzioni, pensioni_pa_dag |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | bdap_anagrafe_enti, bdap_dlb_spese_serie, bdap_entrate_stato, bdap_lb_spese_missione, bdap_lb_spese_serie, bdap_lea, bdap_ni_amministrazioni, bdap_ni_azioni, bdap_ni_indicatori, bdap_ni_obiettivi, bdap_ni_priorita, bdap_pagamenti_stato, bdap_rnd_entrate_articolo, bdap_rnd_spese_capitolo, bdap_rnd_spese_serie, bdap_saldi_stato, bdap_spesa_statale_regionalizzata, bdap_spese_stato, dipendenti_pubblici |
| inail_opendata | catalog | ckan | catalog-watch | GREEN | 200 | inail_malattie_professionali |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim_alunni_corso_eta, mim_anagrafica_scuole_statali, mim_docenti_supplenti, mim_docenti_titolari, mim_personale_ata, mim_personale_ata_supplenti, mim_scuola_infanzia |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | camera_atti_dibattito, camera_commissioni, camera_ddl, camera_deputati_legislature, camera_firmatari, camera_gruppi, camera_incarichi, camera_interventi, camera_iter, camera_leggi, camera_relatori, camera_sindisp, camera_sindisp_destinatari, camera_sindisp_firmatari, camera_votazioni_sparql, camera_voti, membri_governo, silos_infrastrutture |
| dati_senato | catalog | sparql | catalog-watch | GREEN | 200 | senato_anagrafica, senato_commissioni, senato_ddl, senato_emendamenti_lod, senato_firmatari, senato_gruppi, senato_interventi, senato_relatori, senato_sindisp, senato_votazioni, senato_votazioni_oggetto |
| ispra_linked_data | catalog | sparql | catalog-watch | GREEN | 200 | ispra_bathw, ispra_pest, ispra_pest_stations, ispra_places, ispra_rmn, ispra_rs_export, ispra_rs_gestione, ispra_rs_gestione_regionale, ispra_rs_impianti, ispra_rs_impianti_regionali, ispra_rs_import, ispra_rs_produzione, ispra_rs_produzione_regionale, ispra_ru_base, ispra_ru_costi_kg, ispra_ru_costi_procapite, ispra_ru_export, ispra_ru_flussi, ispra_ru_gestione, ispra_ru_gestione_impianti, ispra_ru_gestione_regionale, ispra_ru_import, ispra_urban |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | consip_amministrazioni, consip_bandi_e_gare, consip_cataloghi, consip_consumi_convenzione, consip_gare_asp, consip_operatori_economici, consip_ordini_convenzione, consip_ordini_mepa, consip_partecipazioni, consip_rdo_td_stipulate |
| lavoro_opendata | catalog | ckan | catalog-watch | GREEN | 200 | minlavoro_agevolazioni, minlavoro_flussi |
| mur_ustat | catalog | ckan | catalog-watch | YELLOW | - | mur_afam_diplomati, mur_afam_iscritti, mur_afam_istituti, mur_afam_personale, mur_anagrafica_atenei, mur_contribuzione_universitaria, mur_crosswalk_stem, mur_esoneri, mur_formazione_post_laurea, mur_immatricolati, mur_interventi, mur_iscritti, mur_laureati, mur_laureati_voto, mur_offerta_formativa, mur_personale, mur_personale_ateneo, mur_tasso_abbandono |
| opencoesione | catalog | ckan | catalog-watch | GREEN | 200 | opencoesione_fasi, opencoesione_impegni, opencoesione_indicatori, opencoesione_localizzazioni, opencoesione_pagamenti, opencoesione_progetti, opencoesione_progetti_esteso, opencoesione_soggetti |
| mef_finanze | catalog | html | catalog-watch | GREEN | 200 | abpf_titolari_piva_regione, acsp_imprese_regione, acsp_professionisti_regione, acsp_tutte_classi_reddito, acsp_tutte_classi_volume, acsp_tutte_regione, irap_imposta_pa_regione, irap_imposta_regione, irap_imposta_settore, irap_italia_estero, irap_vp_regime, ires_redditi_regione, irpef_calcolo_tipologia, irpef_comunale, irpef_imposta_tipologia, iva_regionale, iva_sez_attivita, mef_irpef_regionale |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | opencivitas_determinanti, opencivitas_fprcm, opencivitas_fprcm_enti, opencivitas_fsc_enti_rso, opencivitas_fsc_rso, opencivitas_glossario, opencivitas_indicatori |
| aifa | catalog | html | catalog-watch | YELLOW | - | aifa_spesa_consumo |
| dait | catalog | html | radar-only | GREEN | 200 | dait_amministratori_locali, dait_amministratori_storico |
| eligendo | catalog | html | radar-only | GREEN | 200 | elezioni_comunali, elezioni_europee, elezioni_politiche, elezioni_provinciali, elezioni_referendum, elezioni_regionali |
| mit_opendata | catalog | ckan | catalog-watch | GREEN | 200 | mit_incidentalita_mensile, mit_opere_incompiute_2020 |
| openga | catalog | ckan | catalog-watch | GREEN | 200 | ga_decreti, ga_ordinanze, ga_pareri, ga_provvedimenti, ga_ricorsi_definiti, ga_ricorsi_pendenti, ga_ricorsi_pervenuti_class, ga_ricorsi_tipo_decisione, ga_sentenze, ga_sentenze_brevi, openga_ricorsi_appalto |
| giustizia_statistiche | catalog | html | catalog-watch | GREEN | 200 | civile_flussi, durata_civile, durata_penale_classi, durata_penale_medie, giustizia_civile_indicatori, giustizia_penale_indicatori, intercettazioni, mediazione_civile, monitoraggio_mensile_civile, monitoraggio_occ, monitoraggio_pnrr_giustizia, penale_flussi, sorveglianza_esecuzione, sorveglianza_misure, spese_giustizia, ucp_dettaglio, ucp_numero |
| corte_costituzionale | catalog | html | catalog-watch | GREEN | 200 | atti_promovimento_corte_costituzionale, giudici_corte_costituzionale, massime_corte_costituzionale, pronunce_corte_costituzionale, sentenze_complete |
| terna_opendata | catalog | rest | radar-only | GREEN | 200 | terna_bilancio_elettrico, terna_capacita_rinnovabile, terna_copertura_domanda, terna_elettricita_per_fonte, terna_elettricita_per_settore, terna_emissioni_co2, terna_generation_oraria, terna_hydro_power, terna_load_oraria, terna_storage_accumuli |
| ministero_interno | catalog | ckan | radar-only | GREEN | 200 | - |
| agid | catalog | ckan | catalog-watch | GREEN | 200 | ipa_aree_organizzative_omogenee, ipa_categorie_enti, ipa_domicili_digitali, ipa_domicili_digitali_uo, ipa_enti, ipa_rtd, ipa_servizi_digitali, ipa_servizi_uo, ipa_unita_organizzative |
| noipa_sparql | catalog | sparql | catalog-watch | GREEN | 200 | noipa_amministrati, noipa_assenze, noipa_contratti, noipa_pendolarismo, noipa_ritenute_fiscali, noipa_ritenute_previdenziali |
| mimit_rna | catalog | ckan | catalog-watch | GREEN | 200 | rna_aiuti_stato, rna_misure |
| ministero_turismo_opendata | catalog | ckan | radar-only | GREEN | 200 | - |
| ministero_salute | catalog | ckan | catalog-watch | GREEN | 200 | farmacie, personale_ssn, reparti_ricovero, strutture_asl, strutture_ricovero_asl |
| agcm | catalog | ckan | radar-only | GREEN | 200 | - |
| unioncamere | catalog | ckan | radar-only | GREEN | 200 | - |
| pagopa | catalog | ckan | radar-only | GREEN | 200 | - |
| art_opendata | catalog | ckan | catalog-watch | GREEN | 200 | art_taxi_ncc |
| aci | catalog | ckan | catalog-watch | GREEN | 200 | aci_autotrend_mensile, aci_parco_comune, aci_parco_comune_classe_euro, aci_parco_provincia_eta, aci_parco_provincia_soggetto, aci_parco_regione_alimentazione, aci_parco_veicolare, aci_prime_iscrizioni_autovetture, aci_radiazioni_classe_euro, aci_usato_proprieta |
| adm_opendata | catalog | ckan | catalog-watch | GREEN | 200 | adm_accertato_accise |

## Note

- `anac`: HTTP 403 | content-type: text/html; charset=UTF-8 | url finale: https://dati.anticorruzione.it/opendata/api/3/action/package_list?limit=1 | Portale CKAN diretto ANAC (dati.anticorruzione.it). WAF: richiede User-Agent browser. 70 dataset: CIG (2007-2023), SMARTCIG, OCDS, stazioni appaltanti, aggiudicatari, subappalti, varianti, PNRR indicatori, SOA. CC-BY-SA 4.0.
- `mur_ustat`: Retry timeout/connection: Timeout (ConnectTimeout)
- `aifa`: Retry timeout/connection: Timeout (ReadTimeout)
