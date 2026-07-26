"""SPARQL collector and validator."""

from __future__ import annotations

import logging
from typing import Any

from lab_connectors.http.sparql import execute_sparql

from .base import CollectorResult

logger = logging.getLogger(__name__)

# Cache endpoint→reachable per run. Evita COUNT query per ogni gruppo
# della stessa fonte SPARQL (dati_camera: 103 gruppi → 1 query invece di 103).
_endpoint_cache: dict[str, bool] = {}


def _group_sparql_bindings(bindings: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for b in bindings:
        key = b.get("graph", "")
        if key not in grouped:
            grouped[key] = {"graph": key, "subjects": 0, "predicates": set()}
        grouped[key]["subjects"] += 1
        pred = b.get("pred", "")
        if pred:
            grouped[key]["predicates"].add(pred)
    return grouped


def collect(source_id: str, source_cfg: dict, captured_at: str) -> CollectorResult:
    """Enumerate SPARQL datasets (named graphs) from an endpoint."""
    ctx = source_cfg.get("sparql", {})
    endpoint = ctx.get("endpoint_url") or source_cfg.get("base_url", "")
    query = (ctx.get("query") or "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }").strip()
    # Remove trailing semicolon if present
    query = query.rstrip(";")
    limit = int(ctx.get("limit", 100))
    timeout = int(ctx.get("timeout_seconds", 60))
    # Add limit if not present (required by test mock)
    if "limit" not in query.lower():
        query += f" LIMIT {limit}"

    try:
        bindings = execute_sparql(endpoint, query, timeout=timeout)
    except Exception as exc:
        logger.warning("SPARQL query failed for %s: %s", source_id, exc)
        return CollectorResult(rows=[], warning={"type": "sparql_error", "message": str(exc)})

    rows: list[dict] = []
    for idx, b in enumerate(bindings, start=1):
        graph_uri = b.get("g", "")
        if not graph_uri:
            continue

        # Extract a readable name from the URI
        name = graph_uri.rstrip("/").split("/")[-1].replace("_", " ").replace("-", " ").strip()
        title = name[:120] if name else graph_uri[:120]

        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "sparql_named_graphs",
                "item_kind": "named_graph",
                "item_id": graph_uri,
                "item_name": graph_uri,
                "title": title,
                "organization": source_cfg.get("organization"),
                "tags": None,
                "notes_excerpt": None,
                "source_url": endpoint,
                "api_base_url": endpoint,
                "distribution_url": None,
                "format": "SPARQL_NAMED_GRAPH",
                "ordinal": idx,
            }
        )
    return CollectorResult(rows=rows)


def validate_items(items: list[dict]) -> dict[str, Any]:
    """Validate a group of SPARQL items.

    Checks endpoint reachability and runs a simple COUNT query.
    """
    if not items:
        return {
            "dataset_group": "unknown",
            "source_id": "?",
            "protocol": "sparql",
            "reachable": False,
            "error": "No items",
        }

    first = items[0]
    endpoint = first.get("source_url") or first.get("api_base_url", "")
    graph_uri = first.get("item_id", "")
    source_id = first.get("source_id", "?")
    group = first.get("dataset_group", f"{source_id}/unknown")

    result: dict[str, Any] = {
        "dataset_group": group,
        "source_id": source_id,
        "protocol": "sparql",
        "item_count": len(items),
        "reachable": False,
        "format": "SPARQL_NAMED_GRAPH",
        "error": None,
        "endpoint": endpoint,
        "graph_uri": graph_uri,
    }

    if not endpoint:
        result["error"] = "No SPARQL endpoint"
        return result

    # Cache endpoint: se gia' verificato, usa risultato senza COUNT query
    if endpoint not in _endpoint_cache:
        try:
            count_query = f"""
            SELECT (COUNT(*) AS ?cnt) WHERE {{
                GRAPH <{graph_uri}> {{ ?s ?p ?o }}
            }}
            """.strip()
            bindings = execute_sparql(endpoint, count_query, timeout=10)
            if bindings:
                cnt = bindings[0].get("cnt", "0")
                _endpoint_cache[endpoint] = True
                result["triple_count"] = int(cnt) if cnt and str(cnt).isdigit() else 0
            else:
                _endpoint_cache[endpoint] = False
        except Exception as exc:
            _endpoint_cache[endpoint] = False
            result["error"] = str(exc)

    result["reachable"] = _endpoint_cache.get(endpoint, False)
    result["readiness_score"] = 3 if result["reachable"] else 0

    return result
