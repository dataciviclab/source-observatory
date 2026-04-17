---
name: catalog-watch
description: Workflow per osservare i delta di cataloghi (SDMX, CKAN, etc.) senza avviare pipeline.
license: MIT
metadata:
  version: "1.6"
  owner: "DataCivicLab"
---

# Workflow: catalog-watch

**Stato: Operativo (Compact Mode)**
Monitora inventario e struttura dei cataloghi nel registry. Produce report di intelligence per follow-up umani.

## 1. Obiettivo e Boundary

- **SÌ**: Osservare l'inventario e confrontare con la baseline.
- **SÌ**: Segnalare cambi di struttura o nuovi dataflow/package.
- **SÌ**: Suggerire next step umani (non eseguirli).
- **NO**: Fare `source-check` automatici o aprire Issue/PR.
- **NO**: Monitorare singoli file (usare `resource-monitor`).

## 2. Preconditions e Stop Rules

- [ ] Registry `data/radar/sources_registry.yaml` con `observation_mode: catalog-watch`.
- [ ] Baseline (`catalog_baseline.metric/.value`) leggibile.
- [ ] **STOP**: Se il protocollo non è chiaro o l'endpoint è instabile (mismatch di metodo).
- [ ] **STOP**: Se il catalogo è troppo fragile per distinguere tra health e inventory change.

## 3. Passi Canonici (Checklist)

1. **Lettura Registry**: Filtra fonti `catalog-watch`. Annota `protocol`, `base_url`, `last_probed`.
2. **Check Protocollo**:
   - `sdmx`: Listing dataflow -> conteggio -> verifica `datasets_in_use`.
   - `ckan`: Package search/list -> confronto solo se i metodi di conteggio coincidono.
   - `rest_json/html`: Verifica raggiungibilità e struttura link/schema.
3. **Comparabilità**: Confronta `catalog_baseline.method` col metodo osservato. Se non coincidono, usa `[DATO MANCANTE]`, non `inventory change`.
4. **Classifica Segnale**: Usa un solo segnale primario (`no signal`, `health`, `inventory change`, `structural drift`, `follow-up candidate`).
5. **Report**: Scrivi `data/catalog/CATALOG_WATCH_REPORT.md` e aggiorna `data/catalog/catalog_signals.json`.
6. **Update Registry**: Aggiorna `last_probed`. **NON** toccare baseline, method o reliability senza autorizzazione.

## 4. Segnali Ammessi

- `inventory change`: Nuovi dataset rilevati. Seleziona [catalog-inventory-scout.md](./catalog-inventory-scout.md) per triage.
- `structural drift`: Cambio schema o endpoint (non rottura totale).
- `follow-up candidate`: Suggerimento esplicito di intervento umano.
- `health`: Problemi di rete o timeout (prevale su inventory).
- `[DATO MANCANTE]`: Mismatch di metodo o baseline non comparabile.

## 5. Integrazione CI

La GH Action `catalog-inventory.yml` (schedulata ogni lunedì) produce automaticamente:
- `data/catalog_inventory/generated/catalog_inventory_latest.parquet`
- diff rispetto al run precedente → issue `catalog-alert` se ci sono variazioni

Quando invochi questo workflow, **parti dal diff CI se disponibile** invece di interrogare i cataloghi da zero. Il passo 2 (Check Protocollo) serve per fonti non coperte dall'inventory automatico o quando il diff è ambiguo.

---
**Output**: `CATALOG_WATCH_REPORT.md` e `catalog_signals.json` aggiornati, segnale primario per fonte espresso.
**Done**: Registry aggiornato, report pronto per review umana.
