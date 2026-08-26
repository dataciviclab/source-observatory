---
name: source-check
description: Workflow canonico per verificare se una fonte pubblica merita un intake issue in dataset-incubator.
license: MIT
metadata:
  version: "2.0"
  owner: "DataCivicLab"
---

# Workflow: source-check

**Stato: Operativo**
Verifica se una fonte regge davvero come pista del Lab, poi produce issue
intake in `dataset-incubator` + reply nella Discussion Domanda di riferimento.

## 1. Obiettivo e Boundary

- **SÌ**: Verificare accesso reale e forma minima (formato, granularità, copertura).
- **SÌ**: Distinguere tra fonte "viva" e fonte "utile" (domanda civica).
- **SÌ**: Fissare un perimetro v0 e un verdetto unico.
- **SÌ**: Aprire issue intake in `dataset-incubator` se la pista regge.
- **NO**: Fare run di pipeline o sostituire l'health check radar.
- **NO**: Sostituire `catalog-watch` o il monitoraggio ricorrente.

## 2. Pre-requisiti

Prima di iniziare, deve esistere una **Discussion categoria `Domanda`** in
`dataciviclab` che inquadri la domanda civica. Se non esiste (es. fonte emersa
da triage interno), apriline una — la Domanda è l'ancora pubblica del filone.

- [ ] Hai una Discussion Domanda di riferimento (# o URL)
- [ ] Hai una fonte concreta (URL, endpoint o file), non solo un tema.
- [ ] Esiste un possibile uso civico plausibile.
- **STOP**: Se il caso è già maturo per intake o se appartiene al monitoraggio.
- **STOP**: Se la fonte è totalmente opaca (niente metadati o preview).

## 2b. Soglie go intake (checklist binaria)

- [ ] Accesso reale confermato (non solo metadato).
- [ ] ≥1 dimensione analitica utile (geo, temporale, categoriale).
- [ ] Domanda civica formulabile senza join esterne obbligatorie.
- [ ] Qualificatore ≠ `too-thin-for-v0`.
- [ ] Non duplica un filone già aperto in Discussion o `dataset-incubator`.

> Serie storica corta o chiusa **non è blocco** se la domanda civica regge da sola.

## 3. Pre-check MCP (obbligatorio prima di iniziare)

Prima di toccare la fonte, consulta gli artifact SO via MCP per evitare
duplicati e orientarti:

```
1. so_find_by_url(<URL>)       → la fonte è già in source_check o inventory?
2. so_source_check(source_id=?, min_score=3) → score esistente per questa fonte
3. toolkit_source(action="probe", url=<URL>)     → reachability rapida (toolkit MCP)
```

**Se la fonte è già nota (source_id conosciuto)**: sostituisci i passaggi
1-2 con `so_source_report(<source_id>)` che dà identity + health + inventory +
source_check + signals + verdict in una chiamata.

**Se `so_find_by_url` trova risultati**: la fonte è già catalogata — consulta
i risultati prima di proseguire e possibilmente riutilizza evidenze esistenti.

**Se il report mostra health RED**: valuta se il source-check ha senso (fonte
temporaneamente down).

**Se la fonte non è ancora nel radar**: procedi normalmente, ma annota
`source_id` provvisorio nella nota.

## 4. Accesso Reale

Verifica raggiungibilità e leggibilità (redirect, login, WAF). Qualifica come
`verificato` o `inferito`.

1. **Shape minima**: Controlla formato, granularità (cosa rappresenta una riga)
   e copertura.
2. **Sufficienza Semantica**:
   - [ ] Il dato è leggibile subito?
   - [ ] Messaggi/Valori chiave sono autonomi?
   - [ ] Esiste un output minimo senza join esterne?
3. **Domanda Civica**: Formula in una riga *perché* non è solo un "elenco" ma
   serve a una domanda reale.
4. **Perimetro v0**: Fissa geografia e finestra temporale iniziale (preferisci
   perimetro stretto).
5. **Deduplica**: Controlla se il filone è già vivo in Discussion o
   `dataset-incubator`.

## 5. Verdict e Output

Scegli un solo verdetto:
- `go intake`: La fonte regge. Si apre issue intake in DI.
- `watchlist`: Promettente ma non pronta/accessibile ora.
- `support dataset`: Utile solo come supporto/join.
- `aggiorna esistente`: Il filone è già vivo, aggiorna l'artefatto esistente.
- `no-go`: Accesso, formato o valore non reggono.

**Output richiesto** — nota o commento sull'issue SO con:

Schema commento:
```
**Verdict**: [verdetto]

**Discussion Domanda**: [#N](URL)

**Accesso**: [verificato/inferito] — [URL]
**Shape**: [formato, granularità, copertura]
**Qualificatore**: [self-contained / usable-with-enrichment / too-thin-for-v0]
**Domanda civica**: [1 riga]
**Perimetro v0**: [geo + periodo + metrica]

**Next step**: [azione esplicita]
```

Se `verdict ≠ go intake`, il next step può essere `watchlist`, `no-go` o
`aggiornare issue #N` — in tutti i casi, lascia una reply nella Discussion
Domanda con l'esito.

## 6. Se verdict = go intake

Il verdetto `go intake` significa: la fonte regge, il perimetro è chiaro, e
serve un ticket tecnico eseguibile.

### 6a. Apri issue intake in dataset-incubator

Usa il template `new-candidate.yml`. Compila:

- **Title**: `{slug}: {dataset name}`
- **Discussion Domanda**: link alla Domanda di riferimento
- **Fonte**: URL esatto + tipo (HTTP, CKAN, SDMX, ...)
- **Perimetro v0**: geografia, periodo, metrica principale
- **Shape**: formato, granularità, colonne candidate (se già note)
- **Note tecniche**: encoding, delimiter, skip rows, autenticazione (se note)

L'issue intake non deve ri-nascondere la domanda civica — quella sta già nella
Discussion Domanda. L'issue è tecnica: cosa serve per far girare la pipeline.

### 6b. Reply nella Discussion Domanda

Lascia una reply pubblica nella Discussion Domanda:

```
## Scouting: fonte verificata ✅

Abbiamo trovato dati pertinenti:
- **Fonte**: [ente — URL diretto]
- **Copertura**: [periodo]
- **Granularità**: [comune/regionale/nazionale, ...]

✋ Aperta issue tecnica: [#ISSUE](link issue DI) — seguiamo il lavoro lì.

Ci risentiamo quando i dati sono pronti per l'analisi.
```

### 6c. Tracciabilità

- Assegna label `source-checked` all'issue SO
- L'issue SO resta aperta come audit trail finché il maintainer non decide

## 7. Qualificatori Semantici (da annotare)

- `self-contained`: Pronto all'uso.
- `usable-with-enrichment`: Serve join/mapping per valore reale.
- `too-thin-for-v0`: Troppo scarno per il funnel attuale.

---

**Done**: Fonte verificata, verdetto unico espresso, issue intake in DI +
reply pubblica nella Domanda.
