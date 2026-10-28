"""Referenced-item drift: verifica che gli upstream referenziati esistano ancora.

Per ogni dataset con upstream refs, controlla che gli item referenziati
esistano ancora. Se un upstream non ha match → lo segnala come missing (drift).

Match per kind:
  - dataflow:      item_id == flow ID
  - ckan_dataset:  item_name == dataset name
  - ckan_resource: distribution_url contiene resource ID
  - url:           match sull'URL completo (i placeholder {year} sono wildcard),
                   con esito a tre stati (vedi ``_url_state``); se un
                   ``url_probe`` e' disponibile, l'inventario non conferma e
                   decide la verifica dell'URL consumato
  - script_type:   match per token su item_name/title, con esito a tre stati
                   (vedi ``_script_type_state``)
"""

from __future__ import annotations

import re
from typing import Any, Callable

# Verifica di un URL consumato: True (esiste) / False (non esiste) / None
# (non concludente, es. errore di rete → nessun drift dichiarato).
UrlProbe = Callable[[str], "bool | None"]

# Un ref di tipo ``url`` puo' finire in tre stati:
#   matched  → l'item referenziato c'e'
#   missing  → l'area della fonte e' nell'inventario ma l'item no (drift reale)
#   unknown  → l'inventario non copre quell'area: non si puo' concludere
MATCHED = "matched"
MISSING = "missing"
UNKNOWN = "unknown"

_URL_PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def _match_dataflow(ref_id: str, inventory_items: list[dict]) -> bool:
    return any(str(item.get("item_id")) == ref_id for item in inventory_items)


def _match_ckan_dataset(ref_id: str, inventory_items: list[dict]) -> bool:
    # ref_id puo' contenere placeholder tipo {year} — estrai il prefisso fisso
    base = re.sub(r"\{[^}]+\}", "", ref_id).strip("-_")
    for item in inventory_items:
        name = str(item.get("item_name") or item.get("item_id") or "")
        if name == ref_id or (base and name.startswith(base)):
            return True
    return False


def _match_ckan_resource(ref_id: str, inventory_items: list[dict]) -> bool:
    return any(ref_id in str(item.get("distribution_url") or "") for item in inventory_items)


def _url_pattern(ref_id: str) -> re.Pattern[str] | None:
    """Regex dell'URL template: ogni placeholder ``{...}`` diventa wildcard.

    ``.../index.php?tree={year}CIVATOT0201&export=3`` diventa un pattern che
    matcha solo quell'export, non tutto il portale: la query-string fa parte
    dell'identita' della risorsa, non e' rumore da scartare.
    """
    if not ref_id:
        return None
    parts = _URL_PLACEHOLDER_RE.split(ref_id)
    if all(len(p.strip("/_,")) < 3 for p in parts):
        return None  # ref fatto solo di placeholder: non discrimina nulla
    try:
        return re.compile(".*?".join(re.escape(p) for p in parts))
    except re.error:
        return None


def _url_static_prefix(ref_id: str) -> str:
    """Parte statica prima del primo placeholder o della query ('' se troppo corta)."""
    base = re.split(r"\{", ref_id)[0].split("?")[0].rstrip("/_,")
    return base if len(base) >= 10 else ""


def _common_prefix_len(a: str, b: str) -> int:
    """Lunghezza del prefisso comune tra due stringhe."""
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _path_start(url: str) -> int:
    """Indice del primo carattere del path (dopo schema://host/)."""
    match = re.match(r"^[a-z][a-z0-9+.-]*://[^/]+/", url, re.IGNORECASE)
    return match.end() if match else 0


def _url_state(ref_id: str, inventory_items: list[dict], url_probe: UrlProbe | None = None) -> str:
    """Esito del cross-check per un ref di tipo ``url``.

    L'inventario *non* e' autorevole per un URL che consumiamo: spesso descrive
    un altro endpoint dello stesso dato (AGID: ``catalogocloud.agid.gov.it`` vs
    ``indicepa.gov.it``) o solo una distribuzione per item (Consip: un resource
    per package, mentre il repo consuma piu' anni). Quindi:

      1. se l'inventario conferma l'URL → ``matched``, senza rete;
      2. altrimenti, se un ``url_probe`` e' configurato e l'URL e' concreto
         (nessun placeholder ``{year}``), decide la verifica dell'URL consumato:
         esiste → ``matched``, non esiste → ``missing``, non concludente
         (errore di rete) → ``unknown`` (niente falso drift);
      3. senza probe, o con URL templato, resta l'euristica sull'inventario
         (comportamento storico).

    I ref templati non si possono verificare via HTTP: l'URL concreto lo genera
    la pipeline a runtime (``{year}``), quindi l'unico oracolo resta l'inventario.
    """
    state = _url_state_from_inventory(ref_id, inventory_items)
    if state == MATCHED or url_probe is None:
        return state
    if _URL_PLACEHOLDER_RE.search(ref_id):
        return state

    verdict = url_probe(ref_id)
    if verdict is None:
        return UNKNOWN
    return MATCHED if verdict else MISSING


def _url_state_from_inventory(ref_id: str, inventory_items: list[dict]) -> str:
    """Esito del cross-check per un ref di tipo ``url`` (solo inventario).

    Due tentativi di match, in ordine:
      1. URL completo (query inclusa): la query a volte *e'* l'identita' della
         risorsa (``index.php?tree=2025CIVATOT0201``, ``?filterDataset=...``);
      2. solo path: la query a volte e' un parametro di serializzazione
         (``?format=csvdata`` su ECB) e l'identita' e' nel path.

    Un pattern che matcha *tutti* gli item non discrimina nulla: ``unknown``,
    non ``matched``.

    Se non c'e' match, l'esito dipende da quanto l'inventario copre l'area del
    ref (vedi i due segnali piu' sotto): area coperta → ``missing`` (drift
    reale), altrimenti → ``unknown`` (inventario che non copre quell'area).
    """
    urls = [str(item.get("distribution_url") or item.get("url") or "") for item in inventory_items]
    urls = [u for u in urls if u]
    if not urls:
        return UNKNOWN

    full = _url_pattern(ref_id)
    if full is not None:
        hits = sum(1 for u in urls if full.search(u))
        if hits:
            return MATCHED if (hits < len(urls) or len(urls) == 1) else UNKNOWN

    if "?" in ref_id:
        path_only = _url_pattern(ref_id.split("?")[0])
        if path_only is not None:
            hits = sum(1 for u in urls if path_only.search(u))
            if hits and (hits < len(urls) or len(urls) == 1):
                return MATCHED

    # Area coperta? Due segnali, entrambi conservativi:
    # (a) il prefisso statico del ref (path, senza query) esiste nell'inventario;
    # (b) il ref condivide con *alcuni* item un prefisso che entra nel path,
    #     ma non con tutti (altrimenti non distingue nulla).
    prefix = _url_static_prefix(ref_id)
    if prefix and any(prefix in u for u in urls):
        return MISSING

    area_ref = _URL_PLACEHOLDER_RE.sub("", ref_id)
    shared = [_common_prefix_len(area_ref, u) for u in urls]
    best = max(shared)
    if best >= _path_start(ref_id) and shared.count(best) < len(urls):
        return MISSING

    return UNKNOWN


def _script_type_tokens(ref_id: str) -> list[str]:
    """Token significativi di un ID logico ``script_type`` (senza connector words)."""
    return [
        w
        for w in ref_id.lower().split("-")
        if len(w) > 3 and w not in ("per", "con", "della", "degli")
    ]


def _script_type_state(ref_id: str, inventory_items: list[dict]) -> str:
    """Esito del cross-check per un ref di tipo ``script_type``.

    ``script_type`` e' un ID logico (es. ``ricorsi-pervenuti-class``) che mappa
    a nomi package diversi (``...-ricorsi-pervenuti-per-classificazione``): il
    match e' per token, non esatto.

    Un match *parziale* non e' un match: il portale puo' rimuovere l'intera
    famiglia referenziata e il ref resterebbe ``matched`` per via di un token
    generico (``ricorsi`` compare in 248 package su 436). Quindi:

      - ``matched``: un item contiene **tutti** i token del ref;
      - ``missing``: nessun item li contiene tutti, ma almeno un token compare
        ancora (la famiglia c'e', la variante no) — oppure il ref e' di un solo
        token e non compare: la famiglia stessa e' sparita;
      - ``unknown``: ref multi-token di cui **nessun** token compare
        nell'inventario (vocabolario non allineato, inventario che non copre).
    """
    tokens = _script_type_tokens(ref_id)
    if not tokens:
        return UNKNOWN

    haystacks = [
        f"{item.get('item_name') or ''} {item.get('title') or ''}".lower()
        for item in inventory_items
    ]
    if any(all(t in h for t in tokens) for h in haystacks):
        return MATCHED
    if any(any(t in h for t in tokens) for h in haystacks) or len(tokens) == 1:
        return MISSING
    return UNKNOWN


_MATCHERS = {
    "dataflow": _match_dataflow,
    "ckan_dataset": _match_ckan_dataset,
    "ckan_resource": _match_ckan_resource,
}

# Kind gestiti da uno state matcher a tre esiti (non da un matcher booleano).
_STATE_MATCHERS = frozenset({"url", "script_type"})


def _state_for(
    kind: str,
    ref_id: str,
    inventory_items: list[dict],
    url_probe: UrlProbe | None = None,
) -> str:
    """Esito del cross-check per un singolo ref upstream."""
    if kind == "url":
        return _url_state(ref_id, inventory_items, url_probe)
    if kind == "script_type":
        return _script_type_state(ref_id, inventory_items)
    matcher = _MATCHERS.get(kind)
    if matcher is None:
        return UNKNOWN
    return MATCHED if matcher(ref_id, inventory_items) else MISSING


def check_referenced_items(
    datasets_in_use: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
    url_probe: UrlProbe | None = None,
) -> dict[str, Any]:
    """Verifica che gli upstream referenziati esistano ancora.

    Returns:
        {"checked": N, "matched": N, "missing": [{slug, kind, id}, ...],
         "unknown": [{slug, kind, id}, ...]}
        ``missing`` = drift (l'area e' nell'inventario, l'item no);
        ``unknown`` = inventario che non copre l'area del ref.
        Se inventory e' vuoto e non c'e' ``url_probe``, restituisce checked=0
        (nessun cross-check possibile).

    Args:
        url_probe: verifica opzionale di un URL consumato. Riceve l'URL e
            ritorna ``True`` (esiste), ``False`` (non esiste) o ``None``
            (non concludente). Serve perche' l'inventario non e' autorevole
            per gli URL di ``http_file``: puo' descrivere un altro endpoint o
            una sola distribuzione per item. Senza probe resta l'euristica
            sull'inventario.
    """
    if not inventory_rows and url_probe is None:
        return {"checked": 0, "matched": 0, "missing": [], "unknown": []}

    checked = 0
    matched = 0
    missing: list[dict[str, str]] = []
    unknown: list[dict[str, str]] = []

    for ds in datasets_in_use:
        slug = ds.get("slug", "?")
        for ref in ds.get("upstream") or []:
            kind = ref.get("kind", "")
            ref_id = ref.get("id", "")
            if not kind or not ref_id or (kind not in _MATCHERS and kind not in _STATE_MATCHERS):
                continue
            checked += 1
            state = _state_for(kind, ref_id, inventory_rows, url_probe)
            if state == MATCHED:
                matched += 1
            elif state == MISSING:
                missing.append({"slug": slug, "kind": kind, "id": ref_id})
            else:
                unknown.append({"slug": slug, "kind": kind, "id": ref_id})

    return {"checked": checked, "matched": matched, "missing": missing, "unknown": unknown}
