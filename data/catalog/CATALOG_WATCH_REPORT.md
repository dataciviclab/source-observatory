# Catalog Watch Report

Ultimo run: 2026-04-03

## Sommario segnali

| Classificazione | Conteggio | Dettaglio |
| :--- | :--- | :--- |
| `no signal` | 3 | ISTAT (509), INPS (2323) e OpenBDAP (3772) allineati alle baseline correnti. |
| `inventory change` | 0 | - |
| `structural drift` | 0 | - |
| `health` | 1 | ANAC risponde ancora con pagina di reject HTML e non con JSON CKAN verificabile. |
| `follow-up candidate` | 0 | - |
| `[DATO MANCANTE]` | 0 | - |

---

## Dettaglio per fonte

### istat_sdmx
- **Stato**: `no signal`
- **Baseline**: 509 (2026-04-03)
- **Osservato**: 509 (2026-04-03)
- **Delta**: 0
- **Nota**: La baseline e' stata riallineata esplicitamente al conteggio riproducibile via endpoint pubblico `dataflow/IT1`. Il valore storico 4787 non risultava replicabile con il metodo attuale di osservazione.
- **Azione**: Nessuna azione richiesta; mantenere monitoraggio sul metodo corrente.

### anac
- **Stato**: `health`
- **Baseline**: 69 (2026-03-28)
- **Osservato**: [DATO MANCANTE] (2026-04-03)
- **Delta**: non verificabile
- **Nota**: L'endpoint risponde con HTTP 200 ma restituisce ancora una pagina HTML di `Request Rejected`, non un payload JSON CKAN verificabile.
- **Azione**: Trattare la fonte come problema di health/raggiungibilita' e non come inventario stabile finche' non torna una risposta JSON reale.

### inps
- **Stato**: `no signal`
- **Baseline**: 2323 (2026-04-02)
- **Osservato**: 2323 (2026-04-03)
- **Delta**: 0
- **Nota**: Catalogo CKAN consolidato sulla nuova baseline misurata nei giorni scorsi.
- **Azione**: Nessuna azione richiesta.

### openbdap
- **Stato**: `no signal`
- **Baseline**: 3772 (2026-04-02)
- **Osservato**: 3772 (2026-04-03)
- **Delta**: 0
- **Nota**: Le API di package_list confermano l'inventario dichiarato nella baseline recente.
- **Azione**: Nessuna azione richiesta.

---

## STOP POINT
Report pronto per revisione editoriale di Gabri.
Non sono state effettuate modifiche ai dataset o ai candidate.
