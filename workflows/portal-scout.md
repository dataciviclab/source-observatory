---
name: portal-scout
description: Workflow per classificare un portale PA (o un tema di portali) e decidere se merita il registry SO.
license: MIT
metadata:
  version: "0.4"
  owner: "DataCivicLab"
---

# Workflow: portal-scout

**Stato: Operativo**
Classifica la superficie tecnica di un portale PA nazionale e decide se e come aggiungerlo al registry SO.

## 1. Obiettivo e Boundary

- **SÌ**: Classificare protocollo reale, sondare copertura metadata, decidere `observation_mode`.
- **NO**: Verificare singoli dataset (→ `source-check`). NO inventory completi o monitoraggio.

## 2. Quando usarlo

- [ ] Portale nuovo nel radar (segnalazione, discovery, suggerimento).
- [ ] Tema da sondare in batch (es. "portali MEF", "portali cultura.gov.it").
- **STOP**: Già nel registry con `observation_mode` definitivo.
- **STOP**: Serve verifica dataset specifici → `source-check`.

## 3. Passi Canonici

1. **Scope**: singolo URL o tema. Per temi: `discover_portals.py --no-probe`, poi filtra manualmente.
2. **Protocol detection**: probe via script o curl diretto (`/api/3/action/package_list`, `/SDMXWS/rest/dataflow`).
3. **Scout strutturale** (solo CKAN/SDMX/SPARQL): `portal_scout.py --registry-path /tmp/candidate.yaml --dry-run`. Leggi copertura temporale e formati.
4. **Classificazione**: protocollo confermato? enumerabile? temporale popolato? duplicato?
5. **Verdict** (vedi soglie §4) + output §5.

## 4. Soglie Minime

| Verdict | Condizioni (tutte per catalog-watch, ≥ 2 per radar-only) |
|---|---|
| `catalog-watch` | Probe reale confermato · enumerabile senza WAF/login · temporale ≥ 80% (valutazione umana su campione scout) · ≥ 20 dataset strutturati (CSV/JSON/XML) · non duplicato |
| `radar-only` | Raggiungibile · PA nazionale rilevante · non automatizzabile ora (HTML / WAF / < 20 dataset / prevalenza PDF) |
| `source-check-only` | Strutturato ma < 20 dataset o > 50% PDF |
| `scarta` | Falso positivo probe · WAF strutturale · fuori scope · duplicato esatto |

**Azioni post-verdict**:
- `catalog-watch` → proponi YAML per registry + apri issue SO (`portal-scout`).
- `radar-only` → aggiorna registry direttamente, nessuna issue.
- `source-check-only` / `scarta` → nessuna azione.

## 5. Output

```
**Portale**: [domain]
**Protocollo**: [ckan / sdmx / sparql / html]
**Dataset totali**: [N]
**Copertura metadata**: [temporale ≥ 80%? formati prevalenti?]
**Verdict**: [catalog-watch / radar-only / source-check-only / scarta]
**Motivo**: [soglia determinante]
**Next step**: [apri issue / aggiorna registry / nessuna azione]
```

## 6. Strumenti

| Script | Flag utili |
|---|---|
| `discover_portals.py` | `--protocols sdmx` · `--only-matched` · `--no-probe` |
| `portal_scout.py` | `--registry-path /tmp/x.yaml` · `--dry-run` |

Output: `data/portal_scout/discovered_portals.parquet`, `data/portal_scout/scout_results/`.

---
**Done**: Ogni portale ha verdict + motivo. `catalog-watch` → YAML + issue. `radar-only` → registry aggiornato.
