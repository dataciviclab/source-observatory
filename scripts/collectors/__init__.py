from __future__ import annotations

from typing import Any

from . import ckan, html, sdmx, sparql
from .base import CollectorResult

COLLECTORS = {
    "ckan": ckan.collect,
    "sdmx": sdmx.collect,
    "sparql": sparql.collect,
    "html": html.collect,
}

VALIDATORS: dict[str, Any] = {
    "ckan": ckan.validate_items,
    "html": ckan.validate_items,  # HTML usa la stessa logica (HEAD + sniff CSV)
    "sdmx": sdmx.validate_items,
    "sparql": sparql.validate_items,
}


def supported_protocols() -> set[str]:
    return set(COLLECTORS.keys())


def dispatch(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    protocol: str = source_cfg.get("protocol") or ""
    collector = COLLECTORS.get(protocol)
    if not collector:
        raise ValueError(f"Unsupported protocol for catalog inventory: {protocol}")
    return collector(source_id, source_cfg, captured_at)


def dispatch_validate(protocol: str) -> Any:
    """Restituisce la funzione validate_items per un protocollo.

    Se il protocollo non ha un validatore dedicato, restituisce
    il validatore tabulare standard (HEAD + sniff CSV).
    """
    validator = VALIDATORS.get(protocol)
    if validator is not None:
        return validator
    # Fallback: validatore tabulare per protocolli non ancora mappati
    from ._validate_base import validate_tabular_group

    return validate_tabular_group
