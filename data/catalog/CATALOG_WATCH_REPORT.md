# Catalog Watch Report

Ultimo run: 2026-03-31

## Sommario segnali

| Classificazione | Conteggio | Dettaglio |
| :--- | :--- | :--- |
| `no signal` | 1 | ANAC stabile a quota 69. |
| `inventory change` | 2 | ISTAT (calo drastico?) e INPS (crescita esplosiva). |
| `structural drift` | 0 | - |
| `health` | 0 | - |
| `follow-up candidate` | 1 | INPS merita ispezione per capire il delta +1779. |
| `[DATO MANCANTE]` | 1 | ISTAT richiede verifica su endpoint SDMX completo. |

---

## Dettaglio per fonte

### istat_sdmx
- **Stato**: `inventory change` / `[ATTENZIONE]`
- **Baseline**: 4787 (2026-03-28)
- **Osservato**: 509 (2026-03-31)
- **Delta**: -4278
- **Nota**: Il conteggio rilevato tramite `istat_list_dataflows` è drasticamente inferiore alla baseline. È possibile che l'endpoint `.../rest/dataflow/IT1` restituisca solo un subset o che la struttura SDMX sia cambiata.
- **Azione**: [DATO MANCANTE] - Verificare se la baseline originale includeva versioni o se l'endpoint completo `.../rest/dataflow/all/all` dia risultati diversi.

### anac
- **Stato**: `no signal`
- **Baseline**: 69 (2026-03-28)
- **Osservato**: 69 (2026-03-31)
- **Delta**: 0
- **Nota**: Catalogo CKAN perfettamente allineato alla baseline.
- **Azione**: Nessuna azione richiesta.

### inps
- **Stato**: `inventory change` / `follow-up candidate`
- **Baseline**: 544 (2026-03-28)
- **Osservato**: 2323 (2026-03-31)
- **Delta**: +1779
- **Nota**: Incremento massivo del numero di package rilevati tramite `package_list`. I nomi dei package continuano a essere identificativi numerici (es. "544", "6002").
- **Azione**: Eseguire uno `source-check` a campione sui nuovi ID per capire se si tratta di nuovi dataset reali o di una diversa esposizione granulare (es. singoli file esposti come package).

---

## STOP POINT
Report pronto per revisione editoriale di Gabri.
Non sono state effettuate modifiche ai dataset o ai candidate.
