# Deterministic Checks - catalog-watch

## Trigger checks

- [ ] Attiva la skill su richieste di controllo periodico dei portali `catalog-watch`
- [ ] Non attiva la skill su source-check o resource-monitor

## Process checks

- [ ] Legge il registry e filtra solo i portali con `observation_mode: catalog-watch`
- [ ] Usa tool reali coerenti col protocollo
- [ ] Confronta la baseline quando presente
- [ ] Aggiorna solo `last_probed`

## Output checks

- [ ] Produce `CATALOG_WATCH_REPORT.md` con sommario e dettaglio per portale
- [ ] Ogni segnale ha un'azione suggerita chiara

## Pitfall checks

- [ ] Non apre issue o source-check automatici
- [ ] Non modifica `catalog_baseline` senza istruzione esplicita
- [ ] Non classifica come `nessuna novita` un errore di endpoint
