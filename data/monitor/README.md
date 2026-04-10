# Dati Monitor

Stato canonico per il monitoraggio file/resource.

## Struttura

- `snapshots/`
  - snapshot JSON con timestamp scritti da `source-observatory/scripts/monitor/resource_monitor.py`
- `reports/latest.md`
  - ultimo report differenziale leggibile

## Perimetro

Quest'area traccia cambi su una lista corta di fonti già rilevanti:

- file nuovi
- file cambiati
- file rimossi
- errori di adapter

Non è un catalogo di scouting e non è il posto in cui si decide la qualità della fonte.

## Input

La config corrente del monitor vive in:

- `source-observatory/scripts/monitor/resource_monitor.sources.yml`
- `source-observatory/scripts/monitor/resource_monitor.sources.yml.example`

La config deve restare selettiva. Se una fonte non ha un next step plausibile dopo un cambio, non deve entrare nel set monitorato.

## Nota public v0

Nel perimetro attuale della v0 pubblica, quest'area è intenzionalmente secondaria.
Tenere solo un set Tier 1 molto piccolo ed evitare di trattare gli snapshot del monitor come prodotto principale del repo.

## Note collegate

- usage note: `source-observatory/docs/usage.md`
- config audit: `source-observatory/docs/config_audit_2026-03-27.md`
- architecture note: `source-observatory/docs/architecture.md`

## Stato del monitor

Il monitor e' congelato come utility legacy su poche fonti gia' presenti.

Regola pratica:

- nessuna nuova fonte va aggiunta qui come primo passo
- i nuovi portali passano da `portal-scout` / `source-check`
- i futuri source ping orientati al dataset vanno preferibilmente vicino ai candidate in `dataset-incubator`
