"""Referenced-item drift: verifica che gli upstream referenziati esistano ancora.

Per ogni dataset con upstream refs, controlla che gli item referenziati
esistano nell'inventario della fonte. Se un upstream non ha match →
lo segnala come missing (drift).

Match per kind:
  - dataflow:      item_id == flow ID
  - ckan_dataset:  item_name == dataset name
  - ckan_resource: distribution_url contiene resource ID
  - url:           prefix match sul path (ignora {year} e query)
  - script_type:   item_name contiene il suffisso (es. "sentenze")
"""

from __future__ import annotations

import re
from typing import Any


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


def _match_url(ref_id: str, inventory_items: list[dict]) -> bool:
    # Rimuovi placeholder {year}/{prefix} e query per il prefix match.
    # Estrai solo la parte statica prima del primo placeholder.
    base = re.split(r"\{", ref_id)[0].split("?")[0].rstrip("/_,")
    if not base or len(base) < 10:
        return False
    for item in inventory_items:
        url = str(item.get("distribution_url") or item.get("url") or "")
        if url.startswith(base) or base in url:
            return True
    return False


def _match_script_type(ref_id: str, inventory_items: list[dict]) -> bool:
    # script_type e' un ID logico (es. "ricorsi-pervenuti-class") che nel
    # codice sorgente mappa a un suffisso package diverso (es.
    # "ricorsi-pervenuti-per-classificazione"). Il match e' best-effort:
    # cerca il tipo come substring, e anche le sue parole chiave principali.
    ref_low = ref_id.lower()
    # Parole chiave significative (ignora connector words)
    keywords = [
        w for w in ref_low.split("-") if len(w) > 3 and w not in ("per", "con", "della", "degli")
    ]
    for item in inventory_items:
        name = str(item.get("item_name") or "").lower()
        title = str(item.get("title") or "").lower()
        haystack = f"{name} {title}"
        # Match diretto
        if ref_low in haystack:
            return True
        # Match per keyword (almeno 2 keyword presenti)
        if keywords and sum(1 for kw in keywords if kw in haystack) >= min(2, len(keywords)):
            return True
    return False


_MATCHERS = {
    "dataflow": _match_dataflow,
    "ckan_dataset": _match_ckan_dataset,
    "ckan_resource": _match_ckan_resource,
    "url": _match_url,
    "script_type": _match_script_type,
}


def check_referenced_items(
    datasets_in_use: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verifica che gli upstream referenziati esistano nell'inventario.

    Returns:
        {"checked": N, "matched": N, "missing": [{slug, kind, id}, ...]}
        Se inventory e' vuoto, restituisce checked=0 (nessun cross-check possibile).
    """
    if not inventory_rows:
        return {"checked": 0, "matched": 0, "missing": []}

    checked = 0
    matched = 0
    missing: list[dict[str, str]] = []

    for ds in datasets_in_use:
        slug = ds.get("slug", "?")
        for ref in ds.get("upstream") or []:
            kind = ref.get("kind", "")
            ref_id = ref.get("id", "")
            if not kind or not ref_id or kind not in _MATCHERS:
                continue
            checked += 1
            if _MATCHERS[kind](ref_id, inventory_rows):
                matched += 1
            else:
                missing.append({"slug": slug, "kind": kind, "id": ref_id})

    return {"checked": checked, "matched": matched, "missing": missing}
