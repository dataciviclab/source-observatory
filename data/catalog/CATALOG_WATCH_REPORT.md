# Catalog Watch Report

_Generato: 2026-05-08T18:15:59+00:00 — 13 fonti controllate_

## Segnali attivi

### 📦 `istat_sdmx` — inventory change

- **Protocollo**: sdmx
- **Dettaglio**: 4836 item (dataflow_count), delta +1 rispetto al run precedente (4835).
- **Item**: 4836
- **Azione**: verificare se variazione attesa; avviare catalog-inventory-scout se nuovi dataset

### • `dati_salute` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: sitemap failed: primary failed with SSLError; fallback failed with SSLError
- **Azione**: verificare raggiungibilità del portale

### • `mim_opendata` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 1116 link data (CSV 372, JSON 372, XML 372), years 2015-2025 — top prefixes: INFANZIA=192, ALUCORSO=120, SCUANAGR=66, SCUANAAU=66, ALUITAST=60
- **Item**: 1116
- **Azione**: catalog-watch-ready

### 📦 `consip_open_data` — inventory change

- **Protocollo**: ckan
- **Dettaglio**: 16 item (package_list), delta -1 rispetto al run precedente (17).
- **Item**: 16
- **Azione**: verificare se variazione attesa; avviare catalog-inventory-scout se nuovi dataset

### • `mef_irpef` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 147 link data (no format)
- **Item**: 147
- **Azione**: catalog-watch-ready

### • `opencivitas` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 748 link data (ZIP 748), years 2010-2025 — top prefixes: 2010=90, 2013=72, Metadati=64, 2022=63, 2018=59
- **Item**: 748
- **Azione**: catalog-watch-ready

## Fonti stabili / skipped

_7 fonti senza segnali inventariali in questo run._

Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.
