# Skills — Source Observatory

Procedure ripetibili per osservare, inventariare e valutare fonti pubbliche.

## Le 3 skill

| Skill | Entry | Output |
|---|---|---|---|
| [portal-scout.md](./portal-scout.md) | URL portale | go registry / no-go / need-more-info |
| [catalog-inventory-scout.md](./catalog-inventory-scout.md) | source_id o tema | issue SO → source-check |
| [source-check.md](./source-check.md) | item specifico | go intake / watchlist / no-go |

## Flusso

```
proposta / URL
    ↓
portal-scout        → identifica protocollo, decide se aggiungere al registry
    ↓
catalog-inventory   → triage item → issue SO per source-check
    ↓
source-check        → verifica singolo item → go intake / watchlist / no-go
    ↓
    → DI (issue intake)
    → watchlist
    → archivio
```
proposta / URL
    ↓
portal-scout        → identifica protocollo, decide se aggiungere al registry
    ↓
catalog-inventory   → enumerare item (se catalog-watch)
    ↓
source-check        → verifica singolo item → go DI / watchlist / no-go
    ↓
    → DI (go intake / candidate)
    → watchlist
    → archivio
```

## MCP Tools

I tool MCP (`so_*`) sono il layer di lettura degli artifact SO.
Vengono usati dentro le skill per consultare radar, inventory e registry.
Non sono skill themselves — sono strumenti a disposizione di chi esegue una skill.

## Boundary rapido

- `portal-scout` — questo portale è osservabile?
- `catalog-inventory-scout` — cosa c'è in questo catalogo?
- `source-check` — questo dataset merita il funnel del Lab?

## Runbook operativo

Vedi [docs/runbook.md](../docs/runbook.md) per dettagli su radar, catalog-watch e inventory.