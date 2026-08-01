from __future__ import annotations

import re
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
                "format": "SDMX",
                "ordinal": idx,
            }
        )
    return CollectorResult(rows=rows)


def validate_items(
    items: list[dict[str, Any]],
    client: Any | None = None,  # noqa: ARG001 — SDMX non fa probe HTTP
) -> dict[str, Any]:
    """Valida un gruppo di item SDMX.

    SDMX non supporta HEAD/HTTP probe. La validazione si basa
    sui metadati gia' raccolti dal collector durante l'inventory:
    se ha api_base_url e distribution_url → raggiungibile.
    ``client`` accettato per firma uniforme col validatore tabulare,
    ma ignorato (SDMX non fa HTTP qui).
    """
    if not items:
        return {
            "group_id": "unknown",
            "source_id": "?",
            "protocol": "sdmx",
            "item_count": 0,
            "reachable": False,
            "error": "No items",
        }

    first = items[0]
    api_base = first.get("api_base_url") or ""
    dist_url = first.get("distribution_url") or ""
    source_id = first.get("source_id", "?")
    group = first.get("dataset_group", f"{source_id}/unknown")

    has_api = bool(api_base)
    has_url = bool(dist_url)
    has_title = bool(first.get("title"))

    issues: list[str] = []
    if not has_title:
        issues.append("missing title")
    if not has_url:
        issues.append("missing distribution_url")
    if not has_api:
        issues.append("missing api_base_url")

    # Dimensioni dal titolo (per arricchimento metadati)
    dimensions: list[str] = []
    title_text = str(first.get("title") or "") + " " + str(first.get("notes_excerpt") or "")
    tl = title_text.lower()
    for pattern, dim_name in [
        (r"\bsesso\b|\bsex\b|\bgender\b", "sesso"),
        (r"\bet[àa]\b|\bage\b", "eta"),
        (r"\bcittadinanza\b|\bpaese\b", "cittadinanza"),
        (r"\bregion\b|\bprovincia\b|\bnuts\b", "territorio"),
        (r"\bmese\b|\bmonth\b|\btrimestre\b|\bquarter\b", "tempo"),
    ]:
        if re.search(pattern, tl):
            dimensions.append(dim_name)

    reachable = has_api and has_url
    return {
        "dataset_group": group,
        "source_id": source_id,
        "protocol": "sdmx",
        "item_count": len(items),
        "reachable": reachable,
        "readiness_score": 5 if reachable else 0,
        "format": "SDMX",
        "error": "; ".join(issues) if issues else None,
        "validated_at": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()
        ),
        "endpoint": api_base,
        "dataflow_id": first.get("item_id"),
        "dimensions": dimensions or None,
        "title": first.get("title"),
    }
