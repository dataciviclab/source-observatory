from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import duckdb
import pandas as pd
import requests
import yaml

from _constants import SDMX_RETRYABLE_STATUS_CODES, SDMX_RETRY_DELAYS_SECONDS


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "catalog_inventory" / "generated"
DEFAULT_OUT_PARQUET = "catalog_inventory_latest.parquet"
DEFAULT_OUT_REPORT = "catalog_inventory_report.json"
CKAN_ACTION_NAMES = {
    "package_list",
    "package_search",
    "package_show",
    "current_package_list_with_resources",
}
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


def _inventory_cfg(source_cfg: dict[str, Any]) -> dict[str, Any]:
    """Legge il blocco `inventory:` dalla config della fonte nel registry."""
    inv = source_cfg.get("inventory")
    if isinstance(inv, dict):
        return inv
    return {}


def supported_protocols() -> set[str]:
    return {"ckan", "sdmx", "sparql"}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def ckan_action_endpoint(base_url: str, action: str) -> str:
    endpoint = strip_query(base_url)
    if endpoint.endswith("/"):
        endpoint = endpoint[:-1]
    if endpoint.endswith(action):
        return endpoint
    if "/api/3/action/" in endpoint:
        root = endpoint.rsplit("/", 1)[0]
        return f"{root}/{action}"
    last_segment = endpoint.rsplit("/", 1)[-1]
    if last_segment in CKAN_ACTION_NAMES:
        root = endpoint.rsplit("/", 1)[0]
        return f"{root}/{action}"
    return endpoint


def ckan_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    timeout = kwargs.pop("timeout", 60)
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Connection", "close")
    response = requests.get(url, timeout=timeout, headers=headers, **kwargs)
    response.raise_for_status()
    return response.json()


def extract_ckan_inventory_row(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    item: dict[str, Any],
    endpoint: str,
    ordinal: int,
    inventory_method: str,
) -> dict[str, Any]:
    organization = (item.get("organization") or {}).get("title") or (
        item.get("organization") or {}
    ).get("name")
    if not organization:
        organization = item.get("author") or item.get("maintainer")
    tag_items = item.get("tags") or []
    tags: list[str] = []
    for tag_item in tag_items:
        if isinstance(tag_item, dict):
            tag_value = tag_item.get("display_name") or tag_item.get("name")
        elif isinstance(tag_item, str):
            tag_value = tag_item.strip()
        else:
            tag_value = None
        if tag_value:
            tags.append(tag_value)
    notes = (item.get("notes") or "").strip()
    return {
        "captured_at": captured_at,
        "source_id": source_id,
        "source_kind": source_cfg.get("source_kind"),
        "protocol": source_cfg.get("protocol"),
        "inventory_method": inventory_method,
        "item_kind": "dataset",
        "item_id": item.get("id") or item.get("name"),
        "item_name": item.get("name") or item.get("id"),
        "title": item.get("title"),
        "organization": organization,
        "tags": ", ".join(tags) if tags else None,
        "notes_excerpt": notes[:300] if notes else None,
        "source_url": endpoint,
        "ordinal": ordinal,
    }


def collect_ckan_inventory_via_search(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> list[dict[str, Any]]:
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_search")
    page_size = 1000
    start = 0
    ordinal = 1
    rows: list[dict[str, Any]] = []

    while True:
        payload = ckan_get_json(endpoint, params={"rows": page_size, "start": start})
        if not payload.get("success"):
            raise ValueError(f"CKAN package_search failed for {source_id}")

        result = payload.get("result", {})
        items = result.get("results") or []
        if not items:
            break

        for item in items:
            rows.append(
                extract_ckan_inventory_row(
                    source_id=source_id,
                    source_cfg=source_cfg,
                    captured_at=captured_at,
                    item=item,
                    endpoint=endpoint,
                    ordinal=ordinal,
                    inventory_method="package_search",
                )
            )
            ordinal += 1

        if len(items) < page_size:
            break
        start += page_size

    if not rows:
        raise ValueError(f"CKAN package_search returned no rows for {source_id}")
    return rows


def _fetch_ckan_chunk_with_fallback(
    endpoint: str,
    params: dict[str, Any],
    page_size: int,
    *,
    fallback_page_sizes: tuple[int, ...],
    request_timeout: int,
    max_retries: int,
    retry_delay: float,
) -> tuple[dict[str, Any] | None, str | None, int]:
    current_limit = page_size

    while True:
        for attempt in range(max_retries + 1):
            try:
                payload = ckan_get_json(
                    endpoint,
                    params={**params, "limit": current_limit},
                    timeout=request_timeout,
                )
                return payload, None, current_limit
            except requests.Timeout:
                if attempt < max_retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                break

        next_limit = next(
            (size for size in fallback_page_sizes if size < current_limit),
            None,
        )
        if next_limit is None:
            offset = params.get("offset")
            return (
                None,
                f"timeout after retry at offset {offset} with limit {current_limit}",
                current_limit,
            )
        current_limit = next_limit


def collect_ckan_inventory_via_current_list(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    endpoint = ckan_action_endpoint(
        source_cfg["base_url"], "current_package_list_with_resources"
    )
    page_size = 100
    fallback_page_sizes = (50, 10)
    request_timeout = 15
    max_retries = 2
    retry_delay = 1.0
    offset = 0
    ordinal = 1
    rows: list[dict[str, Any]] = []

    while True:
        payload, failure_reason, current_limit = _fetch_ckan_chunk_with_fallback(
            endpoint,
            {"offset": offset},
            page_size,
            fallback_page_sizes=fallback_page_sizes,
            request_timeout=request_timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        if payload is None:
            if rows:
                return rows, {
                    "type": "partial_current_package_list_with_resources",
                    "message": "Arricchimento parziale da current_package_list_with_resources; ultimi chunk in timeout dopo retry.",
                    "failed_offset": offset,
                    "failed_limit": current_limit,
                    "rows_collected": len(rows),
                    "failure": failure_reason,
                }
            raise requests.Timeout(
                f"CKAN current_package_list_with_resources timed out for {source_id}: {failure_reason}"
            )

        if not payload.get("success"):
            raise ValueError(
                f"CKAN current_package_list_with_resources failed for {source_id}"
            )

        result = payload.get("result")
        if not isinstance(result, list):
            raise ValueError(
                f"Unexpected CKAN payload for {source_id}: current_package_list_with_resources result is not a list"
            )
        if not result:
            break

        for item in result:
            rows.append(
                extract_ckan_inventory_row(
                    source_id=source_id,
                    source_cfg=source_cfg,
                    captured_at=captured_at,
                    item=item,
                    endpoint=endpoint,
                    ordinal=ordinal,
                    inventory_method="current_package_list_with_resources",
                )
            )
            ordinal += 1

        if len(result) < current_limit:
            break
        offset += len(result)
        time.sleep(1.0)

    if not rows:
        raise ValueError(
            f"CKAN current_package_list_with_resources returned no rows for {source_id}"
        )
    return rows, None


def collect_ckan_inventory_via_package_list(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> list[dict[str, Any]]:
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_list")
    payload = ckan_get_json(endpoint)
    if not payload.get("success"):
        raise ValueError(f"CKAN action failed for {source_id}")

    result = payload.get("result")
    if not isinstance(result, list):
        raise ValueError(
            f"Unexpected CKAN payload for {source_id}: result is not a list"
        )

    rows: list[dict[str, Any]] = []
    for idx, item_name in enumerate(result, start=1):
        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": source_cfg.get("catalog_baseline", {}).get(
                    "method", "package_list"
                ),
                "item_kind": "dataset",
                "item_id": str(item_name),
                "item_name": str(item_name),
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": endpoint,
                "ordinal": idx,
            }
        )
    return rows


def _sample_indexes(total: int, sample_size: int) -> list[int]:
    if total <= 0 or sample_size <= 0:
        return []
    if total <= sample_size:
        return list(range(total))

    indexes: set[int] = {0, total - 1}
    step = max(total // sample_size, 1)
    for idx in range(0, total, step):
        indexes.add(idx)
        if len(indexes) >= sample_size:
            break
    return sorted(indexes)


def collect_ckan_inventory_via_package_show_sample(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    package_list_rows: list[dict[str, Any]],
    sample_size: int = 25,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_show")
    sampled_idx = _sample_indexes(len(package_list_rows), sample_size)
    if not sampled_idx:
        return [], None

    enriched_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for idx in sampled_idx:
        base_row = package_list_rows[idx]
        package_id = str(base_row["item_id"])
        try:
            payload = ckan_get_json(endpoint, params={"id": package_id}, timeout=30)
            if not payload.get("success"):
                errors.append(f"{package_id}: package_show success=false")
                continue
            item = payload.get("result")
            if not isinstance(item, dict):
                errors.append(f"{package_id}: package_show result non-dict")
                continue
            enriched = extract_ckan_inventory_row(
                source_id=source_id,
                source_cfg=source_cfg,
                captured_at=captured_at,
                item=item,
                endpoint=endpoint,
                ordinal=base_row["ordinal"],
                inventory_method="package_show_sample",
            )
            # Keep package_list key for deterministic merge against base rows.
            enriched["item_id"] = package_id
            enriched_rows.append(enriched)
        except Exception as exc:
            errors.append(f"{package_id}: {exc}")

    warning: dict[str, Any] | None = None
    if errors:
        warning = {
            "type": "package_show_sample_partial",
            "message": "Arricchimento sample via package_show completato con errori parziali.",
            "sample_size": len(sampled_idx),
            "rows_enriched": len(enriched_rows),
            "errors_preview": errors[:10],
        }
    return enriched_rows, warning


def collect_ckan_inventory(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    inv = _inventory_cfg(source_cfg)
    search_exc: Exception | None = None
    if not inv.get("skip_package_search"):
        try:
            return collect_ckan_inventory_via_search(
                source_id, source_cfg, captured_at
            ), None
        except Exception as exc:
            search_exc = exc
    else:
        search_exc = ValueError(
            f"CKAN package_search disabled for {source_id} ({inv.get('skip_package_search_reason', 'disabled by registry config')})."
        )

    package_list_rows = collect_ckan_inventory_via_package_list(
        source_id, source_cfg, captured_at
    )
    if inv.get("skip_current_list"):
        if inv.get("package_show_sample"):
            enriched_rows, sample_warning = collect_ckan_inventory_via_package_show_sample(
                source_id=source_id,
                source_cfg=source_cfg,
                captured_at=captured_at,
                package_list_rows=package_list_rows,
                sample_size=inv.get("sample_size", 25),
            )
            enriched_by_id = {row["item_id"]: row for row in enriched_rows}
            merged_rows: list[dict[str, Any]] = []
            missing_metadata = 0
            for row in package_list_rows:
                enriched = enriched_by_id.get(row["item_id"])
                if enriched is None:
                    missing_metadata += 1
                    merged_rows.append(row)
                else:
                    merged_rows.append({**row, **enriched, "ordinal": row["ordinal"]})
            warning: dict[str, Any] = {
                "type": "skip_current_package_list_with_package_show_sample",
                "message": f"current_package_list_with_resources disabilitato per {source_id}; applicato enrich sample via package_show.",
                "rows_enriched": len(enriched_by_id),
                "rows_missing_metadata": missing_metadata,
            }
            if sample_warning:
                warning["package_show_sample_warning"] = sample_warning
            return merged_rows, warning
        return package_list_rows, {
            "type": "skip_current_package_list",
            "message": f"Enrichment current_package_list_with_resources disabilitato per {source_id} (instabilita SSL/GIL in ambiente locale).",
        }
    time.sleep(1.0)
    try:
        current_rows, current_warning = collect_ckan_inventory_via_current_list(
            source_id, source_cfg, captured_at
        )
        enriched_by_id = {row["item_id"]: row for row in current_rows}
        fallback_merged_rows: list[dict[str, Any]] = []
        missing_metadata = 0
        for row in package_list_rows:
            enriched = enriched_by_id.get(row["item_id"])
            if enriched is None:
                missing_metadata += 1
                fallback_merged_rows.append(row)
            else:
                fallback_merged_rows.append({**row, **enriched, "ordinal": row["ordinal"]})

        fallback_warning: dict[str, Any] = {
            "type": "fallback_current_package_list_with_resources",
            "message": "Fallback da package_search a current_package_list_with_resources.",
            "package_search_error": str(search_exc)
            if search_exc is not None
            else "package_search skipped",
            "rows_enriched": len(enriched_by_id),
            "rows_missing_metadata": missing_metadata,
        }
        if current_warning:
            fallback_warning["current_list_warning"] = current_warning
        return fallback_merged_rows, fallback_warning
    except Exception as current_list_exc:
        return package_list_rows, {
            "type": "fallback_package_list",
            "message": "Fallback finale a package_list dopo fallimento di package_search e current_package_list_with_resources.",
            "package_search_error": str(search_exc)
            if search_exc is not None
            else "package_search skipped",
            "current_list_error": str(current_list_exc),
        }


def parse_sdmx_name(name_elem: ET.Element | None) -> str | None:
    if name_elem is None:
        return None
    text = (name_elem.text or "").strip()
    return text or None


def sparql_binding_value(binding: dict[str, Any], name: str) -> str | None:
    value = (binding.get(name) or {}).get("value")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def compact_uri_name(uri: str | None) -> str | None:
    if not uri:
        return None
    value = uri.rstrip("/")
    if "#" in value:
        return value.rsplit("#", 1)[-1] or value
    return value.rsplit("/", 1)[-1] or value


def append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


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


def collect_sparql_inventory(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint = sparql_cfg.get("endpoint_url") or source_cfg["base_url"]
    query_text, query_name = build_sparql_query(source_cfg)
    response = requests.get(
        endpoint,
        params={"query": query_text, "format": "application/sparql-results+json"},
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "DataCivicLab Source Observatory",
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
    return rows, summary


def collect_sdmx_inventory(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    attempts = len(SDMX_RETRY_DELAYS_SECONDS) + 1
    endpoint = source_cfg["base_url"]
    response: requests.Response | None = None
    last_error: Exception | None = None
    retry_events: list[str] = []

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(endpoint, timeout=120)
            response.raise_for_status()
            break
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            retry_events.append(
                f"tentativo {attempt}: {type(exc).__name__} ({endpoint})"
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in SDMX_RETRYABLE_STATUS_CODES:
                raise
            last_error = exc
            retry_events.append(f"tentativo {attempt}: HTTP {status_code} ({endpoint})")

        if attempt < attempts:
            time.sleep(SDMX_RETRY_DELAYS_SECONDS[attempt - 1])
        else:
            details = ", ".join(retry_events) if retry_events else str(last_error)
            raise RuntimeError(
                f"SDMX fetch failed after {attempts} attempts for {source_id} on {endpoint}: {details}"
            ) from last_error

    if response is None:
        raise RuntimeError(f"SDMX fetch produced no response for {source_id}")

    root = ET.fromstring(response.content)

    ns = {
        "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
        "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
        "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    }

    rows: list[dict[str, Any]] = []
    for idx, flow in enumerate(root.findall(".//structure:Dataflow", ns), start=1):
        flow_id = flow.attrib.get("id")
        name_elem = flow.find("common:Name", ns)
        rows.append(
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": source_cfg.get("catalog_baseline", {}).get(
                    "method", "dataflow_count"
                ),
                "item_kind": "dataflow",
                "item_id": flow_id,
                "item_name": flow_id,
                "title": parse_sdmx_name(name_elem),
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": source_cfg["base_url"],
                "ordinal": idx,
            }
        )
    warning = None
    if retry_events:
        warning = {
            "type": "retry_backoff",
            "message": "Recupero SDMX riuscito dopo retry con backoff.",
            "events": retry_events,
        }
    return rows, warning


def load_registry() -> dict[str, Any]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def collect_inventory(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """Raccoglie l'inventory per una fonte. Ritorna (rows, warning, summary) senza side-effect."""
    protocol = source_cfg.get("protocol")
    if protocol == "ckan":
        rows, warning = collect_ckan_inventory(source_id, source_cfg, captured_at)
        return rows, warning, None
    if protocol == "sdmx":
        rows, warning = collect_sdmx_inventory(source_id, source_cfg, captured_at)
        return rows, warning, None
    if protocol == "sparql":
        rows, summary = collect_sparql_inventory(source_id, source_cfg, captured_at)
        return rows, None, summary
    raise ValueError(f"Unsupported protocol for catalog inventory: {protocol}")


def _collect_source(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
    """Worker per ThreadPoolExecutor: raccoglie una fonte e cattura eccezioni."""
    try:
        rows, warning, summary = collect_inventory(source_id, source_cfg, captured_at)
        return source_id, rows, warning, summary, None
    except Exception as exc:
        return source_id, [], None, None, exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Costruisce il catalog inventory derivato dal registry di source-observatory."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory di output per parquet e report JSON.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        choices=range(1, 9),
        metavar="N (1-8)",
        help="Thread per la raccolta parallela (default: 1 = seriale).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir
    out_parquet = out_dir / DEFAULT_OUT_PARQUET
    out_report = out_dir / DEFAULT_OUT_REPORT

    registry = load_registry()
    captured_at = now_utc_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "captured_at": captured_at,
        "registry_path": str(REGISTRY_PATH),
        "sources": {},
    }

    # Fase 1: filtra fonti inventariabili (in ordine del registry)
    inventoriable: list[tuple[str, dict[str, Any]]] = []
    for source_id, source_cfg in registry.items():
        if source_cfg.get("source_kind") != "catalog":
            continue
        if source_cfg.get("observation_mode") != "catalog-watch":
            continue

        inv = _inventory_cfg(source_cfg)
        if inv.get("non_inventoriable"):
            report["sources"][source_id] = {
                "status": "non_inventariabile",
                "protocol": source_cfg.get("protocol"),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": inv.get("reason", "Fonte non inventariabile."),
            }
            continue

        protocol = source_cfg.get("protocol")
        if protocol not in supported_protocols():
            report["sources"][source_id] = {
                "status": "protocol_not_supported",
                "protocol": protocol,
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": f"Protocollo {protocol} non ancora supportato dal builder inventory.",
            }
            continue

        inventoriable.append((source_id, source_cfg))

    # Fase 2: raccolta (seriale con workers=1, parallela con workers>1)
    collected: dict[str, tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_id = {
            executor.submit(_collect_source, source_id, source_cfg, captured_at): source_id
            for source_id, source_cfg in inventoriable
        }
        for future in as_completed(future_to_id):
            sid, rows, warning, summary, exc = future.result()
            collected[sid] = (rows, warning, summary, exc)

    # Fase 3: assembla report in ordine del registry
    for source_id, source_cfg in inventoriable:
        rows, warning, summary, exc = collected[source_id]
        if exc is not None:
            report["sources"][source_id] = {
                "status": "error",
                "protocol": source_cfg.get("protocol"),
                "error": str(exc),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }
            continue
        all_rows.extend(rows)
        source_report: dict[str, Any] = {
            "status": "ok",
            "protocol": source_cfg.get("protocol"),
            "rows": len(rows),
            "method": source_cfg.get("catalog_baseline", {}).get("method"),
        }
        if warning:
            source_report["warning"] = warning
        if summary:
            source_report["summary"] = summary
        report["sources"][source_id] = source_report

    if not all_rows:
        raise RuntimeError("No catalog inventory rows collected.")

    df = pd.DataFrame(all_rows)
    con = duckdb.connect()
    con.register("inventory_df", df)
    con.execute("CREATE TABLE inventory AS SELECT * FROM inventory_df")
    con.execute("COPY inventory TO ? (FORMAT PARQUET)", [str(out_parquet)])
    con.close()

    with out_report.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    print(f"Wrote {len(all_rows)} rows to {out_parquet}")
    print(f"Wrote report to {out_report}")


if __name__ == "__main__":
    main()
