# Catalog Watch Report

_Generato: 2026-05-02T13:24:09+00:00 — 12 fonti controllate_

## Segnali attivi

### 📦 `istat_sdmx` — inventory change

- **Protocollo**: sdmx
- **Dettaglio**: 4835 item (dataflow_count), delta +1 rispetto al run precedente (4834).
- **Item**: 4835
- **Azione**: verificare se variazione attesa; avviare catalog-inventory-scout se nuovi dataset

### • `dati_salute` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: sitemap failed: SSL failed (HTTPSConnectionPool(host='www.dati.salute.gov.it', port=443): Max retries exceeded with url: /sitemap-0.xml (Caused by SSLError(SSLError(1, '[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1010)')))) then fallback failed (HTTPSConnectionPool(host='www.dati.salute.gov.it', port=443): Max retries exceeded with url: /sitemap-0.xml (Caused by SSLError(SSLError(1, '[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1010)'))))
- **Azione**: verificare raggiungibilità del portale

### • `mim_opendata` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 1116 link data (CSV 372, JSON 372, XML 372), years 2015-2025 — top prefixes: INFANZIA=192, ALUCORSO=120, SCUANAGR=66, SCUANAAU=66, ALUITAST=60
- **Item**: 1116
- **Azione**: catalog-watch-ready

## Fonti stabili / skipped

_9 fonti senza segnali inventariali in questo run._

Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.
