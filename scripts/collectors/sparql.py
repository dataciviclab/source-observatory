from __future__ import annotations

from typing import Any

from .base import (
    CollectorResult,
    sparql_binding_value,
    compact_uri_name,
    append_unique,
    parse_int,
    observatory_get,
)


SPARQL_QUERY_TEMPLATES = {
    "dcat_datasets": """
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>

SELECT DISTINCT ?dataset ?title ?description ?publisherName ?issued ?modified ?landingPage ?theme
WHERE {
  ?dataset a dcat:Dataset .
  OPTIONAL { ?dataset dct:title ?title . }
  OPTIONAL { ?dataset dct:description ?description . }
  OPTIONAL {
    ?dataset dct:publisher ?publisher .
    OPTIONAL { ?publisher foaf:name ?publisherName . }
  }
  OPTIONAL { ?dataset dct:issued ?issued . }
  OPTIONAL { ?dataset dct:modified ?modified . }
  OPTIONAL { ?dataset dcat:landingPage ?landingPage . }
  OPTIONAL { ?dataset dcat:theme ?theme . }
}
ORDER BY ?dataset
LIMIT {limit}
""".strip()
}


def build_sparql_query(source_cfg: dict[str, Any]) -> tuple[str, str]:
    sparql_cfg = source_cfg.get("sparql") or {}
    query_name = sparql_cfg.get("query_name") or source_cfg.get(
        "catalog_baseline", {}
    ).get("query_name")
    query_text = sparql_cfg.get("query")
    if not query_text:
        query_name = query_name or "dcat_datasets"
        query_text = SPARQL_QUERY_TEMPLATES.get(query_name)
    if not query_text:
        raise ValueError(f"SPARQL query template not found: {query_name}")
    limit = int(sparql_cfg.get("limit", 5000))
    if "{limit}" in query_text:
        query_text = query_text.replace("{limit}", str(limit))
    return query_text, query_name or "custom"


def _group_sparql_bindings(bindings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_dataset: dict[str, dict[str, Any]] = {}

    for binding in bindings:
        dataset_uri = sparql_binding_value(binding, "dataset")
        if not dataset_uri:
            continue
        row_state = by_dataset.setdefault(
            dataset_uri,
            {
                "title": None,
                "description": None,
                "publisher": None,
                "issued": None,
                "modified": None,
                "landing_page": None,
                "distribution_count": None,
                "distribution_urls": [],
                "formats": [],
                "themes": [],
            },
        )
        row_state["title"] = row_state["title"] or sparql_binding_value(
            binding, "title"
        )
        row_state["description"] = row_state["description"] or sparql_binding_value(
            binding, "description"
        )
        row_state["publisher"] = row_state["publisher"] or sparql_binding_value(
            binding, "publisherName"
        )
        row_state["issued"] = row_state["issued"] or sparql_binding_value(
            binding, "issued"
        )
        row_state["modified"] = row_state["modified"] or sparql_binding_value(
            binding, "modified"
        )
        row_state["landing_page"] = row_state["landing_page"] or sparql_binding_value(
            binding, "landingPage"
        )
        row_state["distribution_count"] = row_state["distribution_count"] or parse_int(
            sparql_binding_value(binding, "distributionCount")
        )
        append_unique(
            row_state["distribution_urls"],
            sparql_binding_value(binding, "distributionURL")
            or sparql_binding_value(binding, "distributionUrl")
            or sparql_binding_value(binding, "distribution_url")
            or sparql_binding_value(binding, "downloadURL")
            or sparql_binding_value(binding, "accessURL")
            or sparql_binding_value(binding, "distribution"),
        )
        append_unique(row_state["formats"], sparql_binding_value(binding, "format"))
        append_unique(row_state["themes"], sparql_binding_value(binding, "theme"))

    return by_dataset


def _build_sparql_rows(
    by_dataset: dict[str, dict[str, Any]],
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    endpoint: str,
    query_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    inventory_method = source_cfg.get("catalog_baseline", {}).get(
        "method", "sparql_query"
    )

    for idx, (dataset_uri, row_state) in enumerate(by_dataset.items(), start=1):
        description = row_state["description"]
        distribution_urls = row_state["distribution_urls"]
        distribution_count = row_state["distribution_count"]
        formats = row_state["formats"]
        themes = row_state["themes"]
        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": inventory_method,
                "item_kind": "dataset",
                "item_id": dataset_uri,
                "item_name": compact_uri_name(dataset_uri),
                "title": row_state["title"],
                "organization": row_state["publisher"],
                "tags": None,
                "notes_excerpt": description[:300] if description else None,
                "source_url": endpoint,
                "ordinal": idx,
                "issued": row_state["issued"],
                "modified": row_state["modified"],
                "landing_page": row_state["landing_page"],
                "distribution_url": distribution_urls[0] if distribution_urls else None,
                "distribution_count": distribution_count
                if distribution_count is not None
                else (len(distribution_urls) if distribution_urls else None),
                "format": ", ".join(formats) if formats else None,
                "theme": ", ".join(themes) if themes else None,
            }
        )

    return rows, {
        "type": "sparql_query_template",
        "message": "Inventory raccolto via query SPARQL dichiarata.",
        "query_name": query_name,
        "datasets": len(rows),
    }


def collect(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint = sparql_cfg.get("endpoint_url") or source_cfg["base_url"]
    query_text, query_name = build_sparql_query(source_cfg)
    response = observatory_get(
        endpoint,
        params={"query": query_text, "format": "application/sparql-results+json"},
        headers={
            "Accept": "application/sparql-results+json",
        },
        timeout=int(sparql_cfg.get("timeout_seconds", 60)),
    )
    response.raise_for_status()
    payload = response.json()
    bindings = ((payload.get("results") or {}).get("bindings")) or []
    if not isinstance(bindings, list):
        raise ValueError(
            f"Unexpected SPARQL payload for {source_id}: bindings is not a list"
        )

    by_dataset = _group_sparql_bindings(bindings)
    rows, summary = _build_sparql_rows(
        by_dataset,
        source_id,
        source_cfg,
        captured_at,
        endpoint,
        query_name,
    )

    if not rows:
        raise ValueError(f"SPARQL query returned no inventory rows for {source_id}")

    summary["bindings"] = len(bindings)
    return CollectorResult(rows=rows, summary=summary)
