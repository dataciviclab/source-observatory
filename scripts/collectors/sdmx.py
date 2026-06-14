from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lab_connectors.http import HttpClient

from .base import CollectorResult


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
    endpoint = source_cfg["base_url"]
    client = HttpClient(timeout=330, max_retries=1)
    result = client.get(endpoint)

    if result.is_error:
        raise RuntimeError(
            f"SDMX fetch failed for {source_id} on {endpoint}: {result.err}"
        ) from result.err

    response = result.response
    assert response is not None  # is_ok ensures response is set
    if response.status_code >= 400:
        raise RuntimeError(
            f"SDMX endpoint returned HTTP {response.status_code} for {source_id}: "
            f"{response.text[:200]}"
        )

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

    api_base = _sdmx_api_base(source_cfg.get("base_url") or endpoint)

    rows: list[dict[str, Any]] = []
    for idx, flow in enumerate(root.findall(".//structure:Dataflow", ns), start=1):
        flow_id = flow.attrib.get("id")
        name_elem = flow.find("common:Name", ns)
        agency = flow.attrib.get("agencyID")

        # Costruisce URL CSV dall'SDMX REST data endpoint
        dist_url = None
        if api_base and flow_id:
            dist_url = f"{api_base}/data/{flow_id}/ALL/?format=csv"

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
                "organization": agency,
                "tags": None,
                "notes_excerpt": None,
                "source_url": source_cfg["base_url"],
                "api_base_url": api_base,
                "distribution_url": dist_url,
                "format": "CSV",
                "ordinal": idx,
            }
        )
    return CollectorResult(rows=rows)
