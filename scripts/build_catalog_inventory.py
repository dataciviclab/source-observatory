from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import duckdb
import pandas as pd
import requests
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "catalog_inventory" / "generated"
DEFAULT_OUT_PARQUET = "catalog_inventory_latest.parquet"
DEFAULT_OUT_REPORT = "catalog_inventory_report.json"
NON_INVENTORIABLE_SOURCES = {
    "anac": "Fonte osservata in source-observatory, ma non inventariabile con client HTTP standard per via di una risposta WAF 'Request Rejected'.",
}
SDMX_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
SDMX_RETRY_DELAYS_SECONDS = (2, 5)
SUPPORTED_PROTOCOLS = {"ckan", "sdmx"}


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
    return endpoint


def ckan_get_json(url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


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
            organization = (item.get("organization") or {}).get("title") or (
                item.get("organization") or {}
            ).get("name")
            tag_items = item.get("tags") or []
            tags = [
                t.get("display_name") or t.get("name")
                for t in tag_items
                if (t.get("display_name") or t.get("name"))
            ]
            notes = (item.get("notes") or "").strip()
            rows.append(
                {
                    "captured_at": captured_at,
                    "source_id": source_id,
                    "source_kind": source_cfg.get("source_kind"),
                    "protocol": source_cfg.get("protocol"),
                    "inventory_method": "package_search",
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
            )
            ordinal += 1

        if len(items) < page_size:
            break
        start += page_size

    if not rows:
        raise ValueError(f"CKAN package_search returned no rows for {source_id}")
    return rows


def collect_ckan_inventory(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        return collect_ckan_inventory_via_search(
            source_id, source_cfg, captured_at
        ), None
    except Exception as exc:
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
        return rows, {
            "type": "fallback_package_list",
            "message": "Fallback da package_search a package_list.",
            "package_search_error": str(exc),
        }


def parse_sdmx_name(name_elem: ET.Element | None) -> str | None:
    if name_elem is None:
        return None
    text = (name_elem.text or "").strip()
    return text or None


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
) -> list[dict[str, Any]]:
    protocol = source_cfg.get("protocol")
    if protocol == "ckan":
        rows, warning = collect_ckan_inventory(source_id, source_cfg, captured_at)
        if warning:
            source_cfg["_inventory_warning"] = warning
        return rows
    if protocol == "sdmx":
        rows, warning = collect_sdmx_inventory(source_id, source_cfg, captured_at)
        if warning:
            source_cfg["_inventory_warning"] = warning
        return rows
    raise ValueError(f"Unsupported protocol for catalog inventory: {protocol}")


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

    for source_id, source_cfg in registry.items():
        if source_cfg.get("source_kind") != "catalog":
            continue
        if source_cfg.get("observation_mode") != "catalog-watch":
            continue

        if source_id in NON_INVENTORIABLE_SOURCES:
            report["sources"][source_id] = {
                "status": "non_inventariabile",
                "protocol": source_cfg.get("protocol"),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": NON_INVENTORIABLE_SOURCES[source_id],
            }
            continue

        protocol = source_cfg.get("protocol")
        if protocol not in SUPPORTED_PROTOCOLS:
            report["sources"][source_id] = {
                "status": "protocol_not_supported",
                "protocol": protocol,
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": f"Protocollo {protocol} non ancora supportato dal builder inventory.",
            }
            continue

        try:
            rows = collect_inventory(source_id, source_cfg, captured_at)
            all_rows.extend(rows)
            source_report = {
                "status": "ok",
                "protocol": source_cfg.get("protocol"),
                "rows": len(rows),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }
            warning = source_cfg.pop("_inventory_warning", None)
            if warning:
                source_report["warning"] = warning
            report["sources"][source_id] = source_report
        except Exception as exc:
            report["sources"][source_id] = {
                "status": "error",
                "protocol": source_cfg.get("protocol"),
                "error": str(exc),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }

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
