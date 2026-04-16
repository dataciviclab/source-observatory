from __future__ import annotations

import time
import requests
from typing import Any

from .base import CollectorResult, strip_query, inventory_cfg


CKAN_ACTION_NAMES = {
    "package_list",
    "package_search",
    "package_show",
    "current_package_list_with_resources",
}


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


def collect(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    search_fn=collect_ckan_inventory_via_search,
    current_list_fn=collect_ckan_inventory_via_current_list,
    package_list_fn=collect_ckan_inventory_via_package_list,
    package_show_sample_fn=collect_ckan_inventory_via_package_show_sample,
) -> CollectorResult:
    inv = inventory_cfg(source_cfg)
    search_exc: Exception | None = None
    if not inv.get("skip_package_search"):
        try:
            rows = search_fn(source_id, source_cfg, captured_at)
            return CollectorResult(rows=rows)
        except Exception as exc:
            search_exc = exc
    else:
        search_exc = ValueError(
            f"CKAN package_search disabled for {source_id} ({inv.get('skip_package_search_reason', 'disabled by registry config')})."
        )

    package_list_rows = package_list_fn(source_id, source_cfg, captured_at)
    if inv.get("skip_current_list"):
        if inv.get("package_show_sample"):
            enriched_rows, sample_warning = package_show_sample_fn(
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
            return CollectorResult(rows=merged_rows, warning=warning)
        return CollectorResult(
            rows=package_list_rows,
            warning={
                "type": "skip_current_package_list",
                "message": f"Enrichment current_package_list_with_resources disabilitato per {source_id} (instabilita SSL/GIL in ambiente locale).",
            },
        )

    time.sleep(1.0)
    try:
        current_rows, current_warning = current_list_fn(source_id, source_cfg, captured_at)
        enriched_by_id = {row["item_id"]: row for row in current_rows}
        fallback_merged_rows: list[dict[str, Any]] = []
        missing_metadata = 0
        for row in package_list_rows:
            enriched = enriched_by_id.get(row["item_id"])
            if enriched is None:
                missing_metadata += 1
                fallback_merged_rows.append(row)
            else:
                fallback_merged_rows.append(
                    {**row, **enriched, "ordinal": row["ordinal"]}
                )

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
        return CollectorResult(rows=fallback_merged_rows, warning=fallback_warning)
    except Exception as current_list_exc:
        return CollectorResult(
            rows=package_list_rows,
            warning={
                "type": "fallback_package_list",
                "message": "Fallback finale a package_list dopo fallimento di package_search e current_package_list_with_resources.",
                "package_search_error": str(search_exc)
                if search_exc is not None
                else "package_search skipped",
                "current_list_error": str(current_list_exc),
            },
        )

