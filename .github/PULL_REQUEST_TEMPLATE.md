## Sintesi

Descrivi in poche righe cosa cambia e perché.

## Contesto collegato

Closes #

## Cosa cambia

- [ ] Nuova fonte o modifica registro (sources_registry.yaml)
- [ ] Source-check o inventory-triage
- [ ] Modifica script (radar, inventory, source-check, MCP)
- [ ] Modifica funnel o criteri di osservazione
- [ ] Workflow CI (radar.yml, observatory.yml)
- [ ] Skills o MCP tools
- [ ] Documentazione
- [ ] Altro

## Checklist

### Se tocchi sources_registry.yaml

- [ ] `radar_check.py` gestisce la nuova fonte senza errori
- [ ] `observation_mode` impostato correttamente (radar-only / catalog-watch)
- [ ] Eventuali nuovi protocolli testati manualmente

### Se modifichi script o MCP

- [ ] `pytest tests/` passa
- [ ] `ruff check .` passa
- [ ] `mypy scripts/ mcp/` passa
- [ ] Comando manuale verificato (es. `python scripts/radar_check.py --source <id>`)

### Se modifichi il funnel

- [ ] `docs/architecture.md` aggiornato o verificato
- [ ] Impatto su artifact esistenti (radar_summary, catalog_signals) valutato

## Verifica

Spiega come hai verificato il cambiamento.

- [ ] Perimetro stretto: una PR = un tema o un fix
- [ ] Issue collegata o motivazione dell'assenza

## Note per chi revisiona

Rischi, limiti, punti da controllare con attenzione.
