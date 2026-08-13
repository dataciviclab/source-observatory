# Stato Radar

Ultimo run: 2026-08-13

## Sommario

- Fonti controllate: 36
- GREEN: 18
- YELLOW: 0
- RED: 18

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
| anac | catalog | ckan | catalog-watch | RED | 500 | anac_aggiudicatari, anac_aggiudicazioni, anac_bandi_gara, anac_collaudo, anac_cup, anac_partecipanti, anac_stati_avanzamento, anac_subappalti |
| inps | catalog | ckan | catalog-watch | GREEN | 200 | inps_pensioni_trimestrale, pensioni_pa_dag |
| openbdap | catalog | ckan | catalog-watch | GREEN | 200 | bdap_anagrafe_enti, bdap_entrate_stato, bdap_lea, bdap_spese_stato, dipendenti_pubblici |
| inail_opendata | catalog | ckan | catalog-watch | RED | 500 | - |
| mim_opendata | catalog | html | catalog-watch | GREEN | 200 | mim_alunni_corso_eta, mim_anagrafica_scuole_statali, mim_scuola_infanzia |
| dati_camera | catalog | sparql | catalog-watch | GREEN | 200 | camera_deputati_legislature, camera_gruppi, camera_incarichi, camera_votazioni_sparql, membri_governo, silos_infrastrutture |
| dati_senato | catalog | sparql | catalog-watch | GREEN | 200 | senato_anagrafica, senato_ddl, senato_firmatari |
| dati_cultura | catalog | sparql | catalog-watch | GREEN | 200 | - |
| ispra_linked_data | catalog | sparql | catalog-watch | RED | 503 | ispra_consumo_suolo, ispra_ru_base, ispra_ru_costi_kg, ispra_ru_costi_procapite |
| consip_open_data | catalog | ckan | catalog-watch | GREEN | 200 | - |
| lavoro_opendata | catalog | ckan | catalog-watch | RED | 500 | - |
| mur_ustat | catalog | ckan | catalog-watch | RED | 500 | mur_contribuzione_universitaria, mur_immatricolati, mur_iscritti |
| opencoesione | catalog | ckan | catalog-watch | RED | 500 | opencoesione_progetti |
| mef_irpef | catalog | html | catalog-watch | GREEN | 200 | irpef_comunale, mef_irpef_regionale |
| opencivitas | catalog | html | catalog-watch | GREEN | 200 | opencivitas_fsc_2025_rso, opencivitas_fsc_enti_rso, opencivitas_glossario, opencivitas_indicatori |
| aifa | catalog | html | catalog-watch | GREEN | 200 | aifa_spesa_consumo |
| dait | catalog | html | radar-only | GREEN | 200 | dait_amministratori_locali |
| eligendo | catalog | html | radar-only | GREEN | 200 | elezioni_comunali, elezioni_europee, elezioni_referendum, elezioni_regionali |
| mit_opendata | catalog | ckan | catalog-watch | RED | 500 | mit_incidentalita_mensile, mit_opere_incompiute_2020 |
| openga | catalog | ckan | catalog-watch | GREEN | 200 | ga_decreti, ga_ordinanze, ga_sentenze, openga_ricorsi_appalto, openga_ricorsi_cds |
| giustizia_statistiche | catalog | html | catalog-watch | GREEN | 200 | civile_flussi, giustizia_penale_indicatori, intercettazioni, monitoraggio_mensile_civile, penale_flussi |
| cortecostituzionale | catalog | html | catalog-watch | GREEN | 200 | - |
| terna_opendata | catalog | rest | radar-only | GREEN | 200 | terna_electrical_energy_by_sector, terna_electricity_by_source |
| ministero_interno | catalog | ckan | catalog-watch | RED | 500 | - |
| agid | catalog | ckan | catalog-watch | RED | 500 | ipa_aree_organizzative_omogenee, ipa_enti, ipa_unita_organizzative |
| noipa_sparql | catalog | sparql | catalog-watch | GREEN | 200 | - |
| mimit_rna | catalog | ckan | catalog-watch | RED | 500 | rna_aiuti_stato, rna_misure |
| ministero_turismo_opendata | catalog | ckan | catalog-watch | RED | 500 | - |
| ministero_salute | catalog | ckan | catalog-watch | RED | 500 | farmacie, personale_ssn, reparti_ricovero, strutture_asl, strutture_ricovero_asl |
| agcm | catalog | ckan | catalog-watch | RED | 500 | - |
| unioncamere | catalog | ckan | radar-only | RED | 500 | - |
| pagopa | catalog | ckan | catalog-watch | RED | 500 | - |
| art_opendata | catalog | ckan | catalog-watch | RED | 500 | - |
| aci | catalog | ckan | catalog-watch | RED | 500 | aci_prime_iscrizioni_autovetture |
| adm_opendata | catalog | ckan | catalog-watch | RED | 500 | - |

## Note

- `anac`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (harvesting ANAC). I download raw vanno al portale diretto dati.anticorruzione.it con User-Agent browser (WAF blocca solo python-requests). 70 dataset: CIG (2007-2023), SMARTCIG, OCDS, stazioni appaltanti, aggiudicatari, subappalti, varianti, PNRR indicatori, SOA. CC-BY-SA 4.0.
- `inail_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. 102 dataset INAIL su infortuni sul lavoro e malattie professionali. Complementare al portale diretto dati.inail.it (protocollo AEM).
- `ispra_linked_data`: HTTP 503 | content-type: text/html; charset=iso-8859-1 | url finale: https://dati.isprambiente.it/sparql | Catalogo linked-data ISPRA con metadati DCAT interrogabili via SPARQL. Pilot per inventory SPARQL; non sostituisce le fonti operative ISPRA già usate per pipeline tabellari.
- `lavoro_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (harvesting Ministero del Lavoro). Sostituisce fonte diretta dati.lavoro.gov.it che aveva WAF. 83 dataset su lavoro (rapporti attivati/cessati, missioni, qualifiche professionali, genere, settore ATECO, ripartizione geografica).
- `mur_ustat`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (harvesting MUR). Sostituisce fonte diretta dati-ustat.mur.gov.it che aveva ConnectTimeout. 69 dataset su istruzione universitaria (contribuzione atenei, DSU regionale, collegi, AFAM).
- `opencoesione`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (harvesting PCM-OpenCoesione). Sostituisce accesso diretto a opencoesione.gov.it (API REST instabile: 403/timeout). 561 dataset totali su dati.gov.it; i 3 core sono progetti, soggetti, pagamenti (CSV + Parquet). Licenza CC BY 4.0. File raw su opencoesione.gov.it. Ultimo aggiornamento contenuti: 2026-02-28.

- `opencivitas`: HTTP 200 | content-type: text/html; charset=utf-8 | url finale: https://www.opencivitas.it/it/open-data | SSL verify failed; fallback verify=False used (SSLError)
- `mit_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Dataset del Ministero Infrastrutture e Trasporti via dati.gov.it (portale MIT dati.mit.gov.it non raggiungibile da 2026-05). 70 dataset: contratti pubblici, incidentalità, trasporti, opere pubbliche. CC-BY-4.0.
- `ministero_interno`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. Dati elezioni (Politiche 2022, Comunali 2024, Europee 2024, Regionali) per comune + ANPR (popolazione residente, cambi residenza, certificati, AIRE). Alto valore civico per analisi territoriale del voto.
- `agid`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. IPA — Indice delle PA: enti, unita organizzative, PEC, domicili digitali, responsabili transizione digitale, servizi digitali, fatturazione elettronica, cloud. Codice_IPA chiave di join con ANAC.
- `mimit_rna`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. RNA — Registro Nazionale Aiuti di Stato. 133 dataset mensili Aiuti (2017-2026, XML, ~14.500 record/mese) + 237 dataset Misure (1994-2023). File su www.rna.gov.it scaricabili (200 MB/mese, XML strutturato). Altissimo valore civico: tracciamento aiuti pubblici alle imprese con beneficiario, CF, importo, regione, CUP.
- `ministero_turismo_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (Ministero del Turismo). 16 dataset CSV su BDSR (Banca Dati Strutture Ricettive) in formato aggregato per regione/provincia, professioni turistiche (guide, accompagnatori, direttori tecnici), cammini religiosi. FOIA #17 aperta per dati micro BDSR e catalogo completo.
- `ministero_salute`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. Anagrafiche sanitarie nazionali: farmacie, parafarmacie, posti letto, personale SSN, ASL, dispositivi medici, fitosanitari. I file raw puntano a dati.salute.gov.it (portale in migrazione a Gatsby, alcuni URL aggiornati). Complementare a dati_salute (csv_magnet) per il catalogo completo del portale diretto.
- `agcm`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (AGCM). 53 dataset su concorrenza e mercato: rating di legalita' (elenchi settimanali imprese con rating), operazioni di concentrazione 2021-2025.

- `unioncamere`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (Unioncamere). 352 dataset su demografia d'impresa provincia-specifici, costo unione alto. Passato a radar-only: se il catalogo publlica dati aggregati nazionali, si rivaluta.
- `pagopa`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. 8 dataset: pagoPA (transazioni per anno, mese, fascia importo, categoria ente), IO App (messaggi, geografia enti e servizi), SEND (notifiche per ambito, geografia comuni, numero notifiche). Dati su digitalizzazione pagamenti PA e adozione piattaforme digitali (IO, SEND).
- `art_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (ART). 32 dataset CSV su trasporto ferroviario regionale (ritardi, soppressioni, ricavi), taxi/NCC per comune (licenze, tariffe, importi fissi 2002-2024), autostrade (traffico, pedaggi, manutenzioni, sicurezza), aeroporti, interporti, trasporto marittimo. CC BY 4.0. CSV su bdt.autorita-trasporti.it. Incrociabile con MIT incidentalità e ACI parco veicolare.
- `aci`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it. 35 dataset ACI su parco veicolare: prime iscrizioni autovetture (per comune, alimentazione, classe euro, 2017-2024), radiazioni per demolizione. CSV su lod.aci.it in formato tidy. Incrociabile con MIT incidentalità.
- `adm_opendata`: HTTP 500 | content-type: text/html; charset=utf-8 | url finale: https://dati.gov.it/opendata/api/3/action/package_list?limit=1 | Fonte via dati.gov.it (ADM). 31 dataset CSV su vigilanza giochi (scommesse, lotto, bingo, online, apparecchi), fiscalità giochi (raccolta, vincite, spesa), conti gioco attivi per regione/età/genere, vendite tabacchi, rete vendita, accise (energetici, gas, elettricità, alcolici), personale ADM. Copertura 2022-2023, granularità regionale. CSV su dati.gov.it. FOIA #16 aperta per catalogo completo.
