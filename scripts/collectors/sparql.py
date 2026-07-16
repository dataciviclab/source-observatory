from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from lab_connectors.http.sparql import (
    discover_graphs as discover_named_graphs,
)
from lab_connectors.http.sparql import (
    execute_sparql,
)
from lab_connectors.http.sparql import (
    infer_schema as infer_graph_schema,
)

from .base import (
    CollectorResult,
    append_unique,
    compact_uri_name,
    parse_int,
    sparql_binding_value,
)

# Estensioni tabulari/scaricabili in ordine di preferenza
_TABULAR_EXT_RANK: dict[str, int] = {
    ".csv": 0,
    ".tsv": 1,
    ".xlsx": 2,
    ".xls": 3,
    ".json": 4,
    ".xml": 5,
    ".zip": 6,
}


def _normalize_format_uri(fmt: str) -> str:
    """Normalizza URI formato in nome breve.

    Es: ``http://purl.org/dc/terms/IMT`` → ``IMT``
        ``http://publications.europa.eu/resource/authority/file-type/CSV`` → ``CSV``
    """
    return fmt.rsplit("/", 1)[-1].rsplit("#", 1)[-1] if "/" in fmt or "#" in fmt else fmt


def _best_distribution_url(urls: list[str]) -> str | None:
    """Sceglie la distribuzione più probabilmente tabulare/scaricabile.

    Ordina per estensione file (CSV > TSV > XLSX > ...).
    Se nessuna estensione riconosciuta, restituisce la prima URL.
    """
    if not urls:
        return None
    scored = sorted(
        urls,
        key=lambda u: _TABULAR_EXT_RANK.get(Path(u.split("?")[0]).suffix.lower(), 99),
    )
    return scored[0]


SPARQL_QUERY_TEMPLATES = {
    "dcat_datasets": """
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>

SELECT DISTINCT ?dataset ?title ?description ?publisherName ?issued ?modified ?landingPage ?theme ?distributionURL ?format
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
  OPTIONAL { ?dataset dcat:distribution ?dist . }
  OPTIONAL { ?dist dcat:downloadURL ?distributionURL . }
  OPTIONAL {
    ?dist dcat:accessURL ?distributionURL .
    FILTER NOT EXISTS { ?dist dcat:downloadURL [] . }
  }
  OPTIONAL { ?dist dct:format ?format . }
  OPTIONAL { ?dist dcat:mediaType ?format . }
}
ORDER BY ?dataset
LIMIT {limit}
OFFSET {offset}
""".strip()
}


def build_sparql_query(source_cfg: dict[str, Any], offset: int = 0) -> tuple[str, str]:
    sparql_cfg = source_cfg.get("sparql") or {}
    query_name = sparql_cfg.get("query_name") or source_cfg.get("catalog_baseline", {}).get(
        "query_name"
    )
    query_text = sparql_cfg.get("query")
    if not query_text:
        query_name = query_name or "dcat_datasets"
        query_text = SPARQL_QUERY_TEMPLATES.get(query_name)
    if not query_text:
        raise ValueError(f"SPARQL query template not found: {query_name}")
    limit = int(sparql_cfg.get("limit", 5000))
    if "{limit}" in query_text:
        query_text = query_text.replace("{limit}", str(limit))
    if "{offset}" in query_text:
        query_text = query_text.replace("{offset}", str(offset))
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
        row_state["title"] = row_state["title"] or sparql_binding_value(binding, "title")
        row_state["description"] = row_state["description"] or sparql_binding_value(
            binding, "description"
        )
        row_state["publisher"] = row_state["publisher"] or sparql_binding_value(
            binding, "publisherName"
        )
        row_state["issued"] = row_state["issued"] or sparql_binding_value(binding, "issued")
        row_state["modified"] = row_state["modified"] or sparql_binding_value(binding, "modified")
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
    inventory_method = source_cfg.get("catalog_baseline", {}).get("method", "sparql_query")

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
                "distribution_url": _best_distribution_url(distribution_urls),
                "distribution_count": distribution_count
                if distribution_count is not None
                else (len(distribution_urls) if distribution_urls else None),
                "format": (
                    ", ".join(_normalize_format_uri(f) for f in formats) if formats else "SPARQL"
                ),
                "theme": ", ".join(themes) if themes else None,
            }
        )

    return rows, {
        "type": "sparql_query_template",
        "message": "Inventory raccolto via query SPARQL dichiarata.",
        "query_name": query_name,
        "datasets": len(rows),
    }


def _query_supports_offset(source_cfg: dict[str, Any], query_name: str) -> bool:
    """Check if the SPARQL query template or custom query supports {offset} placeholder."""
    if query_name in SPARQL_QUERY_TEMPLATES:
        return "{offset}" in SPARQL_QUERY_TEMPLATES[query_name]
    custom_query = (source_cfg.get("sparql") or {}).get("query") or ""
    return "{offset}" in custom_query


def _execute_sparql_query(
    endpoint: str,
    query_text: str,
    timeout: int,
) -> list[dict[str, Any]]:
    """Execute a single SPARQL query and return bindings.

    Delega a lab_connectors.http.sparql.execute_sparql
    (POST + GET fallback).
    """
    try:
        return execute_sparql(endpoint, query_text, timeout=timeout)
    except RuntimeError as e:
        raise ValueError(str(e)) from e


def _collect_named_graphs(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
) -> CollectorResult:
    """Enumerate all named graphs as proxy inventory items.

    Use when the endpoint has no DCAT catalog but organizes data in named graphs
    (e.g., Senato: composizione/13, ddl/19, votazioni/17, ...).
    Activated via sparql.inventory_mode: named_graphs in sources_registry.yaml.
    """
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint = sparql_cfg.get("endpoint_url") or source_cfg["base_url"]
    timeout = int(sparql_cfg.get("timeout_seconds", 60))
    graph_uri_prefix = sparql_cfg.get("graph_uri_prefix", "")
    graph_uri_blacklist = [
        str(b)
        for b in sparql_cfg.get(
            "graph_uri_blacklist",
            [
                "localhost",
                "virtrdf",
                "owl#",
                "rules.skos",
                "virtrdf-label",
            ],
        )
    ]
    enrich_schema = sparql_cfg.get("enrich_schema", False)
    schema_predicate_limit = int(sparql_cfg.get("schema_predicate_limit", 20))
    enrich_workers = int(sparql_cfg.get("enrich_workers", 4))
    max_workers = 0

    t0 = time.monotonic()

    # Discover named graphs via lab-connectors
    graph_uris = discover_named_graphs(
        endpoint=endpoint,
        timeout=timeout,
        prefix=graph_uri_prefix,
        blacklist=graph_uri_blacklist,
    )
    t1 = time.monotonic()

    rows: list[dict[str, Any]] = []
    # Costruisci righe base (senza schema) subito
    for idx, graph_uri in enumerate(graph_uris, start=1):
        uri_path = graph_uri.replace(graph_uri_prefix, "").rstrip("/")
        title = uri_path.replace("_", " ").replace("/", " \u2014 Legislatura ")
        if title:
            title = title[0].upper() + title[1:]
        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": "sparql",
                "inventory_method": "named_graphs",
                "item_kind": "dataset",
                "item_id": graph_uri,
                "item_name": compact_uri_name(graph_uri),
                "title": title,
                "organization": None,
                "tags": None,
                "notes_excerpt": f"Named graph: {uri_path}",
                "source_url": endpoint,
                "ordinal": idx,
                "issued": None,
                "modified": None,
                "landing_page": None,
                "distribution_url": None,
                "distribution_count": None,
                "format": "SPARQL_NAMED_GRAPH",
                "theme": None,
            }
        )

    # Schema enrichment parallelo
    enrich_count = 0
    enrich_errors = 0
    t_enrich_start = time.monotonic()
    if enrich_schema and rows:
        max_workers = min(enrich_workers, len(rows))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut_to_row = {}
            for row in rows:
                g = row["item_id"]
                fut = pool.submit(
                    infer_graph_schema,
                    endpoint,
                    g,
                    timeout=timeout,
                    limit=schema_predicate_limit,
                )
                fut_to_row[fut] = row

            for fut in as_completed(fut_to_row):
                row = fut_to_row[fut]
                try:
                    schema = fut.result()
                    if schema:
                        pred_strings = [f"{p['compact_name']}({p['count']})" for p in schema]
                        row["tags"] = ", ".join(pred_strings)
                        row["notes_excerpt"] = (
                            f"{row['notes_excerpt']} | Predicati ({len(schema)}): {row['tags']}"
                        )
                        enrich_count += 1
                except Exception:
                    enrich_errors += 1
    t_enrich_end = time.monotonic()

    if not rows:
        raise ValueError(f"Named graph enumeration returned no rows for {source_id}")

    return CollectorResult(
        rows=rows,
        summary={
            "type": "named_graphs",
            "message": "Inventory via enumerazione named graphs SPARQL.",
            "graphs": len(rows),
            "timing": {
                "discover_s": round(t1 - t0, 1),
                "enrich_s": round(t_enrich_end - t_enrich_start, 1),
                "total_s": round(t_enrich_end - t0, 1),
                "enrich_ok": enrich_count,
                "enrich_errors": enrich_errors,
                "enrich_workers": max_workers,
            },
        },
    )


def collect(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint = sparql_cfg.get("endpoint_url") or source_cfg["base_url"]
    inventory_mode = sparql_cfg.get("inventory_mode", "dcat")

    if inventory_mode == "named_graphs":
        return _collect_named_graphs(source_id, source_cfg, captured_at)
    limit = int(sparql_cfg.get("limit", 5000))
    max_pages = int(sparql_cfg.get("max_pages", 50))
    timeout = int(sparql_cfg.get("timeout_seconds", 60))

    _, query_name = build_sparql_query(source_cfg, offset=0)
    supports_pagination = _query_supports_offset(source_cfg, query_name)

    if supports_pagination:
        # Paginazione OFFSET-based
        all_bindings: list[dict[str, Any]] = []
        offset = 0
        page = 0

        while page < max_pages:
            query_text = build_sparql_query(source_cfg, offset=offset)[0]
            bindings = _execute_sparql_query(endpoint, query_text, timeout)
            if not bindings:
                break
            all_bindings.extend(bindings)
            page += 1
            if len(bindings) < limit:
                break
            offset += limit

        by_dataset = _group_sparql_bindings(all_bindings)
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
        summary["bindings"] = len(all_bindings)
        summary["pages"] = page
        if page >= max_pages:
            summary["warning"] = (
                f"Pagination stopped at max_pages={max_pages}; catalog may be truncated"
            )
    else:
        # Run singolo (backward compat per query custom senza {offset})
        query_text = build_sparql_query(source_cfg, offset=0)[0]
        bindings = _execute_sparql_query(endpoint, query_text, timeout)
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
        summary["pages"] = 1

    return CollectorResult(rows=rows, summary=summary)
