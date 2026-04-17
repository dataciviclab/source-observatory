---
name: portal-scout
description: Workflow light per classificare portali e superfici web nel funnel del Lab.
license: MIT
metadata:
  version: "0.2"
  owner: "DataCivicLab"
---

# Workflow: portal-scout

**Stato: Operativo (Compact Mode)**
Identifica il tipo di superficie tecnica di un portale e il metodo di osservazione ideale.

## 1. Obiettivo e Boundary

- **SÌ**: Capire se è un catalogo strutturato o un listing statico.
- **SÌ**: Individuare la superficie tecnica reale (API, sitemap, listing) per l'osservazione.
- **SÌ**: Valutare l'inventariabilità per futuro `catalog-watch`.
- **NO**: Verificare singoli dataset (usare `source-check`).
- **NO**: Costruire inventory completi o monitoraggio continuo.

## 2. Quando usarlo

- [ ] Portale nuovo entra nel radar.
- [ ] Landing page dati non chiara (non è palesemente CKAN/SDMX).
- [ ] Serve classificazione prima di aggiornare `sources_registry.yaml`.
- **STOP**: Se devi seguire una risorsa specifica Tier 1.
- **STOP**: Se il portale è già in `catalog-watch`.

## 3. Workflow Minimo (Checklist)

1. **Inquadramento**: Annota URL base, publisher e superfici secondarie.
2. **Classificazione Tipo**: `ckan`, `sdmx`, `html/sitemap`, `sparql`, `custom`.
3. **Punto di Osservazione**: Distingui tra branding (UI) e superficie tecnica (API, endpoint API, sitemap).
4. **Inventariabilità**:
   - [ ] Gli item sono enumerabili?
   - [ ] Il metodo è riproducibile e il conteggio difendibile?
   - [ ] La superficie è stabile per una baseline?
5. **Deduplica**: Verifica presenza leggera in `sources_registry.yaml`.
6. **Verdetto**: Esprimi un esito unico.

## 4. Verdetti Ammessi

- `portale pronto per catalog-watch`: Superficie stabile e inventariabile.
- `portale da tenere radar-only`: Osservabile ma non enumerabile in modo affidabile.
- `portale utile solo per source-check`: Utile solo per verifiche item-based.
- `superficie non abbastanza chiara`: Da rivalutare o scartare.

---
**Next Step**: Proponi aggiornamento di `sources_registry.yaml` o passa a `source-check` su item specifici.
**Done**: Superficie classificata, metodo di osservazione fissato.
