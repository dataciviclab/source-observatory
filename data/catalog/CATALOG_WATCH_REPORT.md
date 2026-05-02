# Catalog Watch Report

_Generato: 2026-05-02T18:26:58+00:00 — 12 fonti controllate_

## Segnali attivi

### • `dati_salute` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: sitemap failed: SSL failed (HTTPSConnectionPool(host='www.dati.salute.gov.it', port=443): Max retries exceeded with url: /sitemap-0.xml (Caused by SSLError(SSLError(1, '[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1010)')))) then fallback failed (HTTPSConnectionPool(host='www.dati.salute.gov.it', port=443): Max retries exceeded with url: /sitemap-0.xml (Caused by SSLError(SSLError(1, '[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1010)'))))
- **Azione**: verificare raggiungibilità del portale

### • `mim_opendata` — csv_magnet

- **Protocollo**: html
- **Dettaglio**: 1116 link data (CSV 372, JSON 372, XML 372), years 2015-2025 — top prefixes: INFANZIA=192, ALUCORSO=120, SCUANAGR=66, SCUANAAU=66, ALUITAST=60
- **Item**: 1116
- **Azione**: catalog-watch-ready

### 🚨 `istat_sdmx` — endpoint unstable

- **Protocollo**: sdmx
- **Dettaglio**: 4835 item (dataflow_count), ma radar RED — endpoint irraggiungibile o errore. Dati potrebbero essere stale. Verificare radar_summary.json.
- **Item**: 4835
- **Azione**: verificare radar RED; non fidarsi dell'inventario se non confermato da run recente

### 🚨 `dati_camera` — endpoint unstable

- **Protocollo**: sparql
- **Dettaglio**: 104 item (sparql_query), ma radar RED — endpoint irraggiungibile o errore. Dati potrebbero essere stale. Verificare radar_summary.json.
- **Item**: 104
- **Azione**: verificare radar RED; non fidarsi dell'inventario se non confermato da run recente

## Fonti stabili / skipped

_8 fonti senza segnali inventariali in questo run._

Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.
