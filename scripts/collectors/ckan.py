from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from .base import USER_AGENT, CollectorResult, inventory_cfg, strip_query

CKAN_ACTION_NAMES = {
    "package_list",
    "package_search",
    "package_show",
    "current_package_list_with_resources",
}


def _ckan_api_base(url: str) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path
    if "/api/3/action/" in path:
        root = path[: path.index("/api/3/action/")]
        return f"{parsed.scheme}://{parsed.netloc}{root}/api/3/action"
    # endpoint non-standard (es. INPS /odapi): usa il path fino all'ultima action nota
    for action in (
        "package_list",
        "package_search",
        "package_show",
        "current_package_list_with_resources",
    ):
        if f"/{action}" in path:
            root = path[: path.index(f"/{action}")]
            return f"{parsed.scheme}://{parsed.netloc}{root}"
    # fallback: usa host + path senza query
    root = path.rstrip("/").rsplit("/", 1)[0] if "/" in path.rstrip("/") else path
    return f"{parsed.scheme}://{parsed.netloc}{root}"


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
    # Nessun path API rilevato — aggiunge il path standard CKAN
    return f"{endpoint}/api/3/action/{action}"


def ckan_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    """GET JSON da un'API CKAN.

    Args:
        url: Endpoint URL (es. ``/api/3/action/package_show``).
        client: Opzionale, ``HttpClient`` riusabile per connection pooling.
            Se non fornito, ne crea uno nuovo (comportamento legacy).
        **kwargs: Passati a ``HttpClient.get()``; ``timeout`` e ``headers``
            vengono estratti prima di passarli.
    """
    from lab_connectors.http import HttpClient

    client: HttpClient | None = kwargs.pop("client", None)
    timeout = kwargs.pop("timeout", 60)
    headers = kwargs.pop("headers", None)

    if client is None:
        client = HttpClient(timeout=timeout, user_agent=USER_AGENT)

    result = client.get(url, headers=headers or {}, **kwargs)
    if not result.is_ok or result.response is None:
        raise result.err if result.err else RuntimeError(f"GET failed for {url}")
    response = result.response
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            "CKAN API returned non-JSON content "
            f"(status={response.status_code}, content_type={content_type or 'unknown'}, "
            f"preview={preview!r})"
        )
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            "CKAN API returned invalid JSON "
            f"(status={response.status_code}, content_type={content_type or 'unknown'}, "
            f"preview={preview!r})"
        ) from exc


def _resource_format(item: dict) -> str | None:
    resources = item.get("resources") or []
    if not resources:
        return None
    formats: list[str] = []
    for r in resources:
        fmt = str(r.get("format") or "").strip().lower()
        if fmt:
            formats.append(fmt)
    if not formats:
        return None
    unique = list(dict.fromkeys(formats))
    return ",".join(unique)


def _resource_first_url(item: dict) -> str | None:
    """Return the URL of the first resource with a valid url field."""
    resources = item.get("resources") or []
    for r in resources:
        url = r.get("url")
        if url and isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _landing_page(item: dict) -> str | None:
    """Return the dataset landing page URL (CKAN 'url' field or first resource landing)."""
    # CKAN standard: 'url' is the dataset's own landing page (not a resource)
    url = item.get("url")
    if url and isinstance(url, str) and url.strip():
        return url.strip()
    # Fallback: use first resource with a valid url as de-facto landing
    return _resource_first_url(item)


def _distribution_url(item: dict) -> str | None:
    """Return the primary download/访问URL for this dataset.

    Priority: first resource with url > item url field.
    The distribution URL should be a direct link to download or access the data.
    """
    return _resource_first_url(item)


def _has_datastore_active(item: dict) -> bool:
    resources = item.get("resources") or []
    return any(str(r.get("datastore_active") or "").lower() == "true" for r in resources)


def _resource_count(item: dict) -> int:
    return len(item.get("resources") or [])


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

    # Estrae extras (hvd_category, ecc.)
    extras_raw = item.get("extras") or []
    extras: dict[str, str] = {}
    for e in extras_raw:
        if isinstance(e, dict) and "key" in e and "value" in e:
            extras[e["key"]] = str(e["value"])

    return {
        "captured_at": captured_at,
        "source_id": source_id,
        "source_kind": source_cfg.get("source_kind"),
        "protocol": source_cfg.get("protocol"),
        "inventory_method": inventory_method,
        "item_kind": "dataset",
        "item_id": item.get("id") or item.get("name"),
        "item_name": item.get("name") or item.get("id"),
        "item_slug": item.get("name") or None,
        "title": item.get("title"),
        "organization": organization,
        "tags": ", ".join(tags) if tags else None,
        "notes_excerpt": notes[:300] if notes else None,
        "source_url": endpoint,
        "api_base_url": _ckan_api_base(source_cfg.get("base_url") or endpoint),
        "ordinal": ordinal,
        "format": _resource_format(item),
        "landing_page": _landing_page(item),
        "distribution_url": _distribution_url(item),
        "datastore_active": _has_datastore_active(item),
        "resource_count": _resource_count(item),
        # Data di creazione/modifica lato fonte (CKAN metadata_created/modified)
        "issued": item.get("metadata_created") or None,
        "modified": item.get("metadata_modified") or None,
        # Licenza (es. cc-by-4.0, cc-zero, other-open)
        "license_id": item.get("license_id"),
        "license_title": item.get("license_title"),
        # HVD category (es. http://data.europa.eu/bna/c_ac64a52d)
        "hvd_category": extras.get("hvd_category", ""),
    }


def _ckan_search_params(
    source_cfg: dict[str, Any], *, page_size: int, start: int
) -> dict[str, Any]:
    """Build package_search params, optionally adding fq from inventory config."""
    inv = source_cfg.get("inventory") or {}
    params: dict[str, Any] = {"rows": page_size, "start": start}
    fq = inv.get("fq")
    if fq:
        params["fq"] = fq
    return params


def collect_ckan_inventory_via_search(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    """Inventory via paginated package_search.

    Args:
        client: Opzionale, ``HttpClient`` riusabile per connection pooling.
            Se non fornito, ne crea uno nuovo.
    """
    from lab_connectors.http import HttpClient

    if client is None:
        client = HttpClient(timeout=60, user_agent=USER_AGENT)

    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_search")
    page_size = 1000
    start = 0
    ordinal = 1
    rows: list[dict[str, Any]] = []

    while True:
        payload = ckan_get_json(
            endpoint,
            client=client,
            params=_ckan_search_params(source_cfg, page_size=page_size, start=start),
        )
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
    client: Any | None = None,
) -> tuple[dict[str, Any] | None, str | None, int]:
    current_limit = page_size

    while True:
        for attempt in range(max_retries + 1):
            try:
                payload = ckan_get_json(
                    endpoint,
                    client=client,
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
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    from lab_connectors.http import HttpClient

    if client is None:
        client = HttpClient(timeout=15, user_agent=USER_AGENT)
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "current_package_list_with_resources")
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
            client=client,
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
            raise ValueError(f"CKAN current_package_list_with_resources failed for {source_id}")

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
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    *,
    client: Any | None = None,
) -> list[dict[str, Any]]:
    from lab_connectors.http import HttpClient

    if client is None:
        client = HttpClient(timeout=60, user_agent=USER_AGENT)
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_list")
    payload = ckan_get_json(endpoint, client=client)
    if not payload.get("success"):
        raise ValueError(f"CKAN action failed for {source_id}")

    result = payload.get("result")
    if not isinstance(result, list):
        raise ValueError(f"Unexpected CKAN payload for {source_id}: result is not a list")

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
                # per fonti non-standard (es. INPS) package_list restituisce ID numerici,
                # non slug testuali — lo slug reale è disponibile solo dopo package_show_sample
                "item_slug": str(item_name),
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": endpoint,
                "api_base_url": _ckan_api_base(source_cfg.get("base_url") or endpoint),
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


def _fetch_package_show(
    package_id: str,
    endpoint: str,
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    ordinal: int,
    timeout: int = 10,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch and process a single package_show. Returns (row_dict, error_str).

    Timeout ereditato da ``source_cfg[inventory][package_show_timeout]``
    o default 10s.
    """
    try:
        payload = ckan_get_json(endpoint, params={"id": package_id}, timeout=timeout)
        if not payload.get("success"):
            return None, f"{package_id}: success=false"
        item = payload.get("result")
        if not isinstance(item, dict):
            return None, f"{package_id}: result non-dict"
        enriched = extract_ckan_inventory_row(
            source_id=source_id,
            source_cfg=source_cfg,
            captured_at=captured_at,
            item=item,
            endpoint=endpoint,
            ordinal=ordinal,
            inventory_method="package_show_sample",
        )
        enriched["item_id"] = package_id
        return enriched, None
    except Exception as exc:
        return None, f"{package_id}: {exc}"


def collect_ckan_inventory_via_package_show_sample(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    package_list_rows: list[dict[str, Any]],
    sample_size: int = 25,
    max_workers: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    endpoint = ckan_action_endpoint(source_cfg["base_url"], "package_show")
    sampled_idx = _sample_indexes(len(package_list_rows), sample_size)
    if not sampled_idx:
        return [], None

    enriched_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # Timeout ereditato dal registry (inventory.package_show_timeout)
    inv = inventory_cfg(source_cfg)
    pkg_timeout = int(inv.get("package_show_timeout", 10))

    # Parallel fetch — saturare la rete, non la CPU
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _fetch_package_show,
                str(package_list_rows[idx]["item_id"]),
                endpoint,
                source_id,
                source_cfg,
                captured_at,
                package_list_rows[idx]["ordinal"],
                pkg_timeout,
            ): idx
            for idx in sampled_idx
        }
        for future in as_completed(futures):
            row, err = future.result()
            if row is not None:
                enriched_rows.append(row)
            if err:
                errors.append(err)

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
    client: Any | None = None,
    search_fn=collect_ckan_inventory_via_search,
    current_list_fn=collect_ckan_inventory_via_current_list,
    package_list_fn=collect_ckan_inventory_via_package_list,
    package_show_sample_fn=collect_ckan_inventory_via_package_show_sample,
) -> CollectorResult:
    from lab_connectors.http import HttpClient

    if client is None:
        client = HttpClient(timeout=60, user_agent=USER_AGENT)
    inv = inventory_cfg(source_cfg)
    rows, warning = _ckan_standard_path(
        source_id=source_id,
        source_cfg=source_cfg,
        captured_at=captured_at,
        inv=inv,
        client=client,
        search_fn=search_fn,
        current_list_fn=current_list_fn,
        package_list_fn=package_list_fn,
        package_show_sample_fn=package_show_sample_fn,
    )
    return CollectorResult(rows=rows, warning=warning)


def _ckan_standard_path(
    source_id: str,
    source_cfg: dict[str, Any],
    captured_at: str,
    inv: dict[str, Any],
    *,
    client: Any | None = None,
    search_fn,
    current_list_fn,
    package_list_fn,
    package_show_sample_fn,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Ramo standard: package_search -> fallback package_list -> current_list.

    Tutte le funzioni di inventory ricevono il client condiviso per connection pooling.
    """
    search_exc: Exception | None = None

    if not inv.get("skip_package_search"):
        try:
            rows = search_fn(source_id, source_cfg, captured_at, client=client)
            return rows, None
        except Exception as exc:
            search_exc = exc  # per debug
    else:
        search_exc = ValueError(
            f"CKAN package_search disabled for {source_id} ({inv.get('skip_package_search_reason', 'disabled by registry config')})."
        )

    package_list_rows = package_list_fn(source_id, source_cfg, captured_at, client=client)
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
            warn: dict[str, Any] = {
                "type": "skip_current_package_list_with_package_show_sample",
                "message": f"current_package_list_with_resources disabilitato per {source_id}; applicato enrich sample via package_show.",
                "rows_enriched": len(enriched_by_id),
                "rows_missing_metadata": missing_metadata,
            }
            if sample_warning:
                warn["package_show_sample_warning"] = sample_warning
            return merged_rows, warn
        return package_list_rows, {
            "type": "skip_current_package_list",
            "message": f"Enrichment current_package_list_with_resources disabilitato per {source_id} (instabilita SSL/GIL in ambiente locale).",
        }

    time.sleep(1.0)
    try:
        # current_list ha timeout 15s proprio — non passare il client condiviso
        # (creato con timeout 60s) per non alterare il comportamento di retry
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
