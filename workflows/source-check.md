---
name: source-check
description: Workflow canonico per verificare se una fonte pubblica merita il funnel del Lab.
license: MIT
metadata:
  version: "1.2"
  owner: "DataCivicLab"
---

# Workflow: source-check

**Stato: Operativo (Compact Mode)**
Verifica se una fonte regge davvero come pista del Lab prima di aprire Discussion o pipeline.

## 1. Obiettivo e Boundary

- **SÌ**: Verificare accesso reale e forma minima (formato, granularità, copertura).
- **SÌ**: Distinguere tra fonte "viva" e fonte "utile" (domanda civica).
- **SÌ**: Fissare un perimetro v0 e un verdetto unico.
- **NO**: Fare intake in `dataset-incubator` o monitoraggio ricorrente.
- **NO**: Sostituire l'health check radar o `catalog-watch`.

## 2. Preconditions e Stop Rules

- [ ] Hai una fonte concreta (URL, endpoint o file), non solo un tema.
- [ ] Esiste un possibile uso civico plausibile.
- [ ] **STOP**: Se il caso è già maturo per Discussion/PI o se appartiene al monitoraggio.
- [ ] **STOP**: Se la fonte è totalmente opaca (niente metadata o preview).

## 2b. Soglie go Discussion (checklist binaria)

- [ ] Accesso reale confermato (non solo metadato).
- [ ] ≥1 dimensione analitica utile (geo, temporale, categoriale).
- [ ] Domanda civica formulabile senza join esterne obbligatorie.
- [ ] Qualificatore ≠ `too-thin-for-v0`.
- [ ] Non duplica un filone già aperto in Discussion o `dataset-incubator`.

> Serie storica corta o chiusa **non è blocco** se la domanda civica regge da sola.

## 3. Passi Canonici (Checklist)

1. **Accesso Reale**: Verifica raggiungibilità e leggibilità (redirect, login, WAF). Qualifica come `verificato` o `inferito`.
2. **Shape minima**: Controlla formato, granularità (cosa rappresenta una riga) e copertura.
3. **Sufficienza Semantica**:
   - [ ] Il dato è leggibile subito?
   - [ ] Messaggi/Valori chiave sono autonomi?
   - [ ] Esite un output minimo senza join esterne?
4. **Domanda Civica**: Formula in una riga *perché* non è solo un "elenco" ma serve a una domanda reale.
5. **Perimetro v0**: Fissa geografia e finestra temporale iniziale (preferisci perimetro stretto).
6. **Deduplica**: Controlla se il filone è già vivo in `Discussion` o `dataset-incubator`.

## 4. Verdict e Output

Scegli un solo verdetto:
- `go Discussion`: La fonte regge come pista autonoma.
- `watchlist`: Promettente ma non pronta/accessibile ora.
- `support dataset`: Utile solo come supporto/join.
- `aggiorna esistente`: Il filone è già vivo, aggiorna l'artefatto esistente.
- `no-go`: Accesso, formato o valore non reggono.

**Output richiesto**: nota o commento sull'issue SO con verdetto, accesso reale (stato + URL), shape, domanda civica, qualificatore e next step esplicito.

Schema commento:
```
**Verdict**: [verdetto]

**Accesso**: [verificato/inferito] — [URL]
**Shape**: [formato, granularità, copertura]
**Qualificatore**: [self-contained / usable-with-enrichment / too-thin-for-v0]
**Domanda civica**: [1 riga]
**Perimetro v0**: [geo + periodo + metrica]

**Next step**: [azione esplicita]
```

## 5. Se verdict = go Discussion

Il verdetto `go Discussion` significa: la fonte merita una Discussion. Il workflow deve almeno preparare il testo; pubblicarlo è un passo separato, consentito solo se il maintainer conferma o se il task lo richiede esplicitamente.

Prepara una discussion in `dataciviclab` categoria **Datasets** con questo schema compatto:

**Titolo**: `[fonte breve] — [domanda civica in max 8 parole]`

**Body** (max 15 righe):
```
## Fonte ufficiale
[ente + link/endpoint principale — 1-2 righe]

## Domanda civica
[1 domanda, max 2 righe]

## Perimetro v0
- [geografia]
- [periodo]
- [metrica principale]

→ Source-check completo: [link issue SO]
```

Poi:
- Se pubblicata, aggiungi label `go-discussion` e commento con link alla discussion.
- Se non pubblicata, lascia come next step `preparare/pubblicare Discussion Datasets`.
- **Non chiudere** l'issue SO solo per il source-check: resta audit trail finché il maintainer non decide.

## 6. Qualificatori Semantici (da annotare)

- `self-contained`: Pronto all'uso.
- `usable-with-enrichment`: Serve join/mapping per valore reale.
- `too-thin-for-v0`: Troppo scarno per il funnel attuale.

---
**Done**: Fonte verificata, verdetto unico espresso, next step scritto in nota o issue.
