"""SPARQL query execution for SO MCP."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import _artifact


def _sparql_query_raw(
    endpoint: str,
    query: str,
    timeout: int = 60,
    max_rows: int = 500,
) -> dict[str, Any]:
    """Execute a SPARQL SELECT query against any public endpoint.

    Returns dict with rows, columns, and bindings count.
    Uses observatory_get (from collectors.base) for POST-based SPARQL queries.
    """
    if not endpoint or not query:
        return {"error": "invalid_params", "message": "endpoint and query are required"}
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"error": "invalid_url", "message": f"Invalid SPARQL endpoint: {endpoint}"}
    safe_timeout = max(1, min(int(timeout or 60), 120))
    safe_max_rows = max(1, min(int(max_rows or 500), 5000))

    clean_query = query.strip()
    if "LIMIT" not in clean_query.upper():
        clean_query = f"{clean_query}\nLIMIT {safe_max_rows}"

    try:
        response = _artifact._get_observatory_get()(
            endpoint,
            params={"query": clean_query, "format": "application/sparql-results+json"},
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "DataCivicLab-SourceObservatory/1.0",
            },
            timeout=safe_timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc)[:200],
            "endpoint": endpoint,
        }

    bindings = ((payload.get("results") or {}).get("bindings")) or []
    if not isinstance(bindings, list):
        return {
            "error": "invalid_response",
            "message": "SPARQL endpoint did not return bindings list",
            "endpoint": endpoint,
        }

    rows: list[dict[str, Any]] = []
    for binding in bindings:
        row: dict[str, Any] = {}
        for var_name, var_value in binding.items():
            if isinstance(var_value, dict):
                row[var_name] = var_value.get("value")
            else:
                row[var_name] = var_value
        rows.append(row)

    return {
        "endpoint": endpoint,
        "query": clean_query,
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "bindings": len(bindings),
        "returned": len(rows),
    }
