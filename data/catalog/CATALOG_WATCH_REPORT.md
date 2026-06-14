# Catalog Watch Report

_Generato: 2026-06-14T09:21:11+00:00 — 28 fonti controllate_

## Segnali attivi

### • `mim_opendata` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 1116 link data (CSV 372, JSON 372, XML 372), years 2015-2026 — top prefixes: INFANZIA=192, ALUCORSO=120, SCUANAGR=66, SCUANAAU=66, ALUITAST=60
- **Item**: 1116
- **Azione**: catalog-watch-ready

### 📦 `ispra_linked_data` — inventory change

- **Protocollo**: sparql
- **Dettaglio**: 69 item (sparql_query), delta +2 rispetto al run precedente (67).
- **Item**: 69
- **Azione**: verificare se variazione attesa; avviare inventory-triage se nuovi dataset

### • `mef_irpef` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: HTTPSConnectionPool(host='www1.finanze.gov.it', port=443): Max retries exceeded with url: /finanze/analisi_stat/public/index.php?opendata=yes (Caused by ConnectTimeoutError(<HTTPSConnection(host='www1.finanze.gov.it', port=443) at 0x7f7d01035d30>, 'Connection to www1.finanze.gov.it timed out. (connect timeout=5)'))
- **Azione**: verificare raggiungibilità del portale

### • `opencivitas` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 748 link data (ZIP 748), years 2010-2025 — top prefixes: 2010=90, 2013=72, Metadati=64, 2022=63, 2018=59
- **Item**: 748
- **Azione**: catalog-watch-ready

### • `aifa` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 42 link data (CSV 38, XML 1, ZIP 3), years 2010-2027 — top prefixes: provvedimenti=8, Classe=4, sc=3, elenco=2, Elenco=2
- **Item**: 42
- **Azione**: catalog-watch-ready

### • `giustizia_statistiche` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 9 link data (XLS 9), years 2014-2025 — top prefixes: Indicatori=2, Durata=2, Civile=1, Sorveg=1, Sorveglianza=1
- **Item**: 9
- **Azione**: low signal

### • `cortecostituzionale` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 33 link data (ZIP 33)
- **Item**: 33
- **Azione**: catalog-watch-ready

### 📦 `unioncamere` — inventory change

- **Protocollo**: ckan
- **Dettaglio**: 371 item (package_search), delta +19 rispetto al run precedente (352).
- **Item**: 371
- **Azione**: verificare se variazione attesa; avviare inventory-triage se nuovi dataset

## Fonti stabili / skipped

_20 fonti senza segnali inventariali in questo run._

Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.
