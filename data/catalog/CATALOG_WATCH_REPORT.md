# Catalog Watch Report

_Generato: 2026-06-08T08:25:35+00:00 — 26 fonti controllate_

## Segnali attivi

### • `mim_opendata` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 1116 link data (CSV 372, JSON 372, XML 372), years 2015-2026 — top prefixes: INFANZIA=192, ALUCORSO=120, SCUANAGR=66, SCUANAAU=66, ALUITAST=60
- **Item**: 1116
- **Azione**: catalog-watch-ready

### 📦 `ispra_linked_data` — inventory change

- **Protocollo**: sparql
- **Dettaglio**: 67 item (sparql_query), delta +1 rispetto al run precedente (66).
- **Item**: 67
- **Azione**: verificare se variazione attesa; avviare inventory-triage se nuovi dataset

### • `mef_irpef` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: HTTPSConnectionPool(host='www1.finanze.gov.it', port=443): Max retries exceeded with url: /finanze/analisi_stat/public/index.php?opendata=yes (Caused by ConnectTimeoutError(<HTTPSConnection(host='www1.finanze.gov.it', port=443) at 0x7f6620168200>, 'Connection to www1.finanze.gov.it timed out. (connect timeout=5)'))
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
- **Dettaglio**: 8 link data (XLS 8), years 2014-2025 — top prefixes: Indicatori=2, Durata=2, Civile=1, Sorveg=1, Interc=1
- **Item**: 8
- **Azione**: low signal

### • `cortecostituzionale` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 33 link data (ZIP 33)
- **Item**: 33
- **Azione**: catalog-watch-ready

## Fonti stabili / skipped

_19 fonti senza segnali inventariali in questo run._

Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.
