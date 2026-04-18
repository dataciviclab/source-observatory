from __future__ import annotations

import time
import requests
import xml.etree.ElementTree as ET
from typing import Any

from .base import CollectorResult, observatory_get
from _constants import SDMX_RETRYABLE_STATUS_CODES, SDMX_RETRY_DELAYS_SECONDS


def parse_sdmx_name(name_elem: ET.Element | None) -> str | None:
    if name_elem is None:
        return None
    text = (name_elem.text or "").strip()
    return text or None


def _sdmx_api_base(url: str) -> str | None:
    if not url:
        return None
    base = url.split("?")[0].rstrip("/")
    if "/dataflow/" in base:
        return base[: base.index("/dataflow/")]
    return base


def collect(source_id: str, source_cfg: dict[str, Any], captured_at: str) -> CollectorResult:
    attempts = len(SDMX_RETRY_DELAYS_SECONDS) + 1
    endpoint = source_cfg["base_url"]
    response: requests.Response | None = None
    last_error: Exception | None = None
    retry_events: list[str] = []

    for attempt in range(1, attempts + 1):
        try:
            response = observatory_get(endpoint, timeout=120)
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

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        preview = response.text[:200].replace("\n", " ").strip()
        raise ValueError(
            f"SDMX endpoint returned invalid XML for {source_id} "
            f"(status={response.status_code}, preview={preview!r})"
        ) from exc

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
                "api_base_url": _sdmx_api_base(source_cfg.get("base_url") or endpoint),
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
    return CollectorResult(rows=rows, warning=warning)
