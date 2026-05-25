"""CKAN package_show helper for SO MCP."""

from __future__ import annotations

from typing import Any

from lab_connectors.http import HttpClient


def _ckan_action_endpoint(base_url: str, action: str) -> str:
    """Build a CKAN API action URL from a base URL.

    If base_url already contains /api/3/action, appends the action directly.
    Otherwise appends /api/3/action/{action}.
    """
    base = base_url.rstrip("/")
    if "/api/3/action" in base:
        return f"{base}/{action}"
    return f"{base}/api/3/action/{action}"


def _ckan_get_json(url: str, timeout: int = 30, params: dict | None = None) -> dict[str, Any]:
    """Simple HTTP GET returning JSON — uses HttpClient with SSL fallback."""
    client = HttpClient(timeout=timeout)
    result = client.get(url, params=params or {})
    if not result.is_ok:
        raise result.err
    response = result.response
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            f"Non-JSON content-type (status={response.status_code}, "
            f"content_type={content_type or 'unknown'}, preview={preview!r})"
        )
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            f"Invalid JSON (status={response.status_code}, "
            f"content_type={content_type or 'unknown'}, preview={preview!r})"
        ) from exc


def _ckan_package_show(endpoint: str, package_id: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch a single CKAN package_show.

    Args:
        endpoint: CKAN portal base URL (e.g. https://dati.gov.it).
        package_id: CKAN dataset ID or name.
        timeout: request timeout in seconds (default 30, max 120).

    Returns dict with keys:
        success: True if dataset found
        item_id, name, title, notes (first 300 chars), organization,
        tags (comma-joined), format (resource formats), resource_count,
        datastore_active (bool), landing_page, distribution_url,
        source_url (API endpoint used)
    OR error + message on failure.
    """
    if not endpoint or not package_id:
        return {"error": "invalid_params", "message": "endpoint and package_id are required"}

    api_url = _ckan_action_endpoint(endpoint, "package_show")
    params = {"id": package_id}

    try:
        payload = _ckan_get_json(api_url, params=params, timeout=timeout)
    except Exception as exc:
        return {
            "error": type(exc).__name__,
            "message": str(exc)[:200],
            "tried_url": api_url,
            "package_id": package_id,
        }

    if not payload.get("success"):
        return {
            "error": "ckan_error",
            "message": f"success=false for {package_id}",
            "tried_url": api_url,
            "package_id": package_id,
            "ckan_response": payload.get("error") or payload,
        }

    item = payload.get("result")
    if not isinstance(item, dict):
        return {
            "error": "ckan_error",
            "message": f"result non-dict for {package_id}",
            "tried_url": api_url,
            "package_id": package_id,
        }

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

    resources = item.get("resources") or []
    formats: list[str] = []
    for r in resources:
        fmt = str(r.get("format") or "").strip().lower()
        if fmt:
            formats.append(fmt)
    format_str = ",".join(dict.fromkeys(formats)) if formats else None

    landing = item.get("url")
    if not landing:
        for r in resources:
            u = r.get("url")
            if u and isinstance(u, str) and u.strip():
                landing = u.strip()
                break

    datastore_active = any(
        str(r.get("datastore_active") or "").lower() == "true" for r in resources
    )

    notes = (item.get("notes") or "").strip()

    return {
        "success": True,
        "item_id": item.get("id") or item.get("name"),
        "name": item.get("name"),
        "title": item.get("title"),
        "notes_excerpt": notes[:300] if notes else None,
        "organization": organization,
        "tags": ", ".join(tags) if tags else None,
        "format": format_str,
        "resource_count": len(resources),
        "datastore_active": datastore_active,
        "landing_page": landing,
        "distribution_url": resources[0].get("url") if resources else None,
        "source_url": api_url,
    }
