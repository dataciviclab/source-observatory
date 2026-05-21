#!/usr/bin/env python3
"""
Bulk source-check su una selezione del catalogo.

Per ogni item del catalogo:
  - CKAN (inps, openbdap, ...): chiama package_show per recuperare title,
    notes, tags, risorse (url + format), copertura temporale dagli extras.
  - SDMX (istat_sdmx): chiama /dataflow per leggere le annotations
    LAYOUT_DATAFLOW_KEYWORDS (granularità + anni già strutturati).
  - Fallback: inferisce granularità e anni da titolo + tag con regex.
  Fa poi HEAD HTTP sull'URL più rilevante trovato.

Output: source_check_results.parquet

Uso:
    python scripts/bulk_source_check.py
    python scripts/bulk_source_check.py --source-ids inps istat_sdmx
    python scripts/bulk_source_check.py --source-ids openbdap --limit 50 --include-no-url
    python scripts/bulk_source_check.py --out data/mycheck.parquet
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_check_fetch import (
    SDMX_NS,
    _EMPTY_ENRICH,
    _content_type_format,
    _fetch_ckan_package,
    _fetch_data_preview,
    _fetch_html_metadata,
    _fetch_sdmx_dataflow,
    _fetch_sdmx_years,
    _http_head_with_retry,
    configure_source_check_http,
)
from source_check_analyze import (
    _infer_granularity,
    _infer_years,
    _parse_ckan_package,
    _fallback_infer,
    _normalize_format,
    _finalize_scores,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_latest.parquet"
DEFAULT_OUT = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"

MAX_WORKERS = 16
_NO_SDMX_YEARS = False  # set via --no-sdmx-years flag




# ── registry ─────────────────────────────────────────────────────────────────

def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ── SDMX enrichment ───────────────────────────────────────────────────────────

def _parse_sdmx_annotations(xml_root: ET.Element, base_url: str, flow_id: str) -> dict:
    annotations: dict[str, str] = {}
    for ann in xml_root.findall(".//common:Annotation", SDMX_NS):
        atype_el = ann.find("common:AnnotationType", SDMX_NS)
        atext_el = ann.find("common:AnnotationText", SDMX_NS)
        if atype_el is not None and atext_el is not None:
            annotations[atype_el.text or ""] = atext_el.text or ""

    keywords_raw = annotations.get("LAYOUT_DATAFLOW_KEYWORDS", "")
    # formato: "keyword1+keyword2+...+keyword3+..."
    keywords = [k.strip().lower() for part in keywords_raw.split("+") for k in part.split(",") if k.strip()]

    combined = " ".join(keywords)
    granularity = _infer_granularity(combined)
    year_min, year_max = _infer_years(combined)

    # se le annotations non contengono anni, prova a ricavarli dall'endpoint dati
    if year_min is None:
        year_min, year_max = _fetch_sdmx_years(base_url, flow_id, allow_fetch=not _NO_SDMX_YEARS)

    metadata_url = annotations.get("METADATA_URL")

    # Estrai version e agency dal Dataflow XML (per scaffold toolkit)
    df_elem = xml_root.find(".//structure:Dataflow", SDMX_NS)
    sdmx_version = df_elem.attrib.get("version") if df_elem is not None else None
    sdmx_agency = df_elem.attrib.get("agencyID") if df_elem is not None else None

    return {
        "enriched_title": None,
        "enriched_tags": ", ".join(keywords[:10]) if keywords else None,
        "enriched_notes": keywords_raw[:300] if keywords_raw else None,
        "resource_url": metadata_url,
        "resource_format": "SDMX",
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "enrich_method": "sdmx_dataflow_annotations",
        "sdmx_flow": flow_id,
        "sdmx_version": sdmx_version,
        "sdmx_agency": sdmx_agency,  # None se non presente nel XML
    }


# ── HTML enrichment (fallback per landing_page) ───────────────────────────────

# (importato da source_check_fetch)


# ── dispatcher per protocollo ─────────────────────────────────────────────────

def _enrich(row: pd.Series, registry: dict[str, Any]) -> dict:
    source_id = row.get("source_id") or ""
    source_cfg = registry.get(source_id, {})
    protocol = source_cfg.get("protocol") or row.get("protocol") or ""
    base_url = source_cfg.get("base_url") or row.get("source_url") or ""
    _raw_name = row.get("item_name") or row.get("item_id")
    item_name = "" if pd.isna(_raw_name) else str(_raw_name)
    # preferisci item_slug (nome testuale CKAN) per package_show
    _slug = row.get("item_slug")
    if isinstance(_slug, str) and _slug.strip():
        item_name = _slug.strip()

    has_valid_slug = False  # default; set True inside CKAN block if slug is usable
    if protocol == "ckan" and base_url and item_name:
        # _slug già letto sopra (linea 395) — non riletto
        has_valid_slug = bool(isinstance(_slug, str) and _slug.strip() and _slug.strip() != "dataset")
        if has_valid_slug:
            # usa api_base_url pre-calcolata dal layer 1 (gestisce endpoint non-standard come INPS /odapi/)
            api_base_url = row.get("api_base_url")
            base_api = api_base_url if isinstance(api_base_url, str) and api_base_url.startswith("http") else base_url
            pkg = _fetch_ckan_package(base_api, item_name)
            if pkg:
                return _parse_ckan_package(pkg)
        # CKAN senza slug valido → skip package_show, passa a HTML fallback sotto

    if protocol == "sdmx" and base_url and item_name:
        # base_url dal registry ha il path completo (es. .../dataflow/IT1).
        # Non usare api_base_url — più corto, _fetch_sdmx_dataflow() fallisce.
        xml_root = _fetch_sdmx_dataflow(base_url, item_name)
        if xml_root is not None:
            return _parse_sdmx_annotations(xml_root, base_url, item_name)

    # HTML protocol: direct data URL (CSV/JSON/XLS) — fetch content preview
    if protocol == "html":
        data_url = row.get("url")
        if isinstance(data_url, str):
            parsed = urllib.parse.urlparse(data_url)
            path = parsed.path or ""
            fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if fmt in ("csv", "json", "xlsx", "xls"):
                return _fetch_data_preview(data_url)

    # HTML fallback: per tutti i source con landing_page raggiungibile
    # dati_camera ha scraping_blocked=true → salta HTML se CKAN package_show già provato
    # CKAN senza slug valido = package_show già saltato → proviamo comunque l'HTML
    landing = row.get("landing_page")
    if isinstance(landing, str) and landing.startswith("http"):
        # skip scraping_blocked sources only if CKAN package_show already attempted
        ckan_skipped_package_show = protocol == "ckan" and not has_valid_slug
        if source_cfg.get("scraping_blocked") and not ckan_skipped_package_show:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "scraping_blocked"
            return result
        return _fetch_html_metadata(landing)

    return _EMPTY_ENRICH.copy()


# ── fallback euristica su campi catalogo ──────────────────────────────────────

# (importato da source_check_analyze)


# ── inventory-aware enrich ───────────────────────────────────────────────────

def _enrich_with_inventory(
    row: pd.Series,
    registry: dict[str, Any],
) -> dict:
    """
    Enrich item using inventory as primary source.

    Rules:
    - title/format/tags from inventory → use directly (no re-fetch)
    - Re-enrich via API only if: inventory.format is null AND item looks promising
    - For CKAN: re-fetch package_show only when inventory has no format AND no title
    - For SDMX: always use dataflow annotations (inventory has them)
    - For HTML: use inventory.url + content-type detection
    """
    source_id = row.get("source_id") or ""
    source_cfg = registry.get(source_id, {})
    protocol = source_cfg.get("protocol") or row.get("protocol") or ""
    base_url = source_cfg.get("base_url") or row.get("source_url") or ""

    # Inventory has these → use directly
    inv_title = row.get("title")
    inv_format = row.get("format")
    inv_tags = row.get("tags")
    inv_notes = row.get("notes_excerpt")
    inv_granularity = row.get("granularity")  # may be None

    # Fallback per fonti HTML: inventory non ha org/tags/notes perché il
    # csv_magnet scan cattura solo URL e titolo, non i metadati del portale.
    # Deriviamo dai campi noti del registry (source_id, topic_hint, note).
    inv_org = row.get("organization")
    if not inv_org:
        # source_id come organizzazione implicita (es. "aifa"→"AIFA")
        inv_org = source_id.upper() if source_id else None
    # NaN safeguard: pandas NaN è truthy in Python, ma `not x` su NaN è False.
    # Usiamo pd.isna() per rilevare valori NaN/non popolati.
    if pd.isna(inv_org) or pd.isna(inv_tags) or pd.isna(inv_notes):
        hp = source_cfg.get("html_portal") or {}
        topic_hint = hp.get("topic_hint") if isinstance(hp, dict) else None
        src_note = source_cfg.get("note", "") or ""
        if pd.isna(inv_org):
            inv_org = source_id.upper() if source_id else None
        if pd.isna(inv_tags) and topic_hint:
            inv_tags = topic_hint
        if pd.isna(inv_notes) and src_note:
            inv_notes = src_note[:300]

    _raw_name = row.get("item_name") or row.get("item_id")
    item_name = "" if pd.isna(_raw_name) else str(_raw_name)
    _slug = row.get("item_slug")
    if isinstance(_slug, str) and _slug.strip():
        item_name = _slug.strip()

    # CKAN: only re-fetch package_show if format AND title are missing in inventory
    # inv_format="csv,xml,json" is a dirty concatenated string from package_search → check if any token is valid
    _VALID_FORMATS_FOR_SKIP = {"CSV", "JSON", "XLSX", "XLS", "XML", "PDF", "SDMX", "ZIP", "PARQUET"}
    inv_format_has_valid = (
        isinstance(inv_format, str)
        and any(t.strip().upper() in _VALID_FORMATS_FOR_SKIP for t in inv_format.split(","))
    )
    has_valid_slug = bool(isinstance(_slug, str) and _slug.strip() and _slug.strip() != "dataset")
    needs_ckan_refetch = (
        protocol == "ckan"
        and base_url
        and item_name
        and has_valid_slug
        and not inv_format_has_valid
        and not inv_title
    )

    if needs_ckan_refetch:
        api_base_url = row.get("api_base_url")
        base_api = api_base_url if isinstance(api_base_url, str) and api_base_url.startswith("http") else base_url
        pkg = _fetch_ckan_package(base_api, item_name)
        if pkg:
            return _parse_ckan_package(pkg)

    # SDMX: always use dataflow annotations (structured, not in inventory format)
    if protocol == "sdmx" and base_url and item_name:
        # base_url dal registry ha il path completo (es. .../dataflow/IT1).
        # api_base_url dall'inventory è più corto (.../rest) — non usarlo
        # perché _fetch_sdmx_dataflow() si aspetta il path con /dataflow/IT1.
        xml_root = _fetch_sdmx_dataflow(base_url, item_name)
        if xml_root is not None:
            return _parse_sdmx_annotations(xml_root, base_url, item_name)

    def _enc(r: dict) -> dict:
        """Aggiunge encoding dall'inventory row a qualsiasi result dict,
        più organization derivata dal registry per fonti senza metadati."""
        r["encoding_suggested"] = _safe_str(row.get("encoding_suggested"))
        r["delim_suggested"] = _safe_str(row.get("delim_suggested"))
        r["decimal_suggested"] = _safe_str(row.get("decimal_suggested"))
        _skip = row.get("skip_suggested")
        r["skip_suggested"] = 0 if pd.isna(_skip) else int(_skip)
        # Fallback per fonti HTML: inventory non ha organization/tags/notes
        # (csv_magnet scan cattura solo URL e titolo).
        # Assegnamento diretto (non setdefault): _EMPTY_ENRICH ha già queste
        # chiavi a None, setdefault non sovrascriverebbe.
        r["enriched_org"] = inv_org
        r["enriched_tags"] = inv_tags
        r["enriched_notes"] = inv_notes
        return r

    # HTML: use inventory url + content-type format detection
    if protocol == "html":
        data_url = row.get("url")
        if isinstance(data_url, str):
            fmt = _content_type_format(data_url)
            if fmt:
                return _enc({
                    "enriched_title": inv_title,
                    "enriched_tags": inv_tags,
                    "enriched_notes": inv_notes,
                    "resource_url": data_url,
                    "resource_format": fmt,
                    "granularity": inv_granularity,
                    "year_min": row.get("year_signal"),
                    "year_max": row.get("year_signal"),
                    "enrich_method": "content_type",
                })

    # HTML fallback via direct fetch for CSV/JSON/XLS
    if protocol == "html":
        data_url = row.get("url")
        if isinstance(data_url, str):
            parsed = urllib.parse.urlparse(data_url)
            path = parsed.path or ""
            fmt_ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if fmt_ext in ("csv", "json", "xlsx", "xls"):
                preview = _fetch_data_preview(data_url)
                # Merge con _enc per arricchire org/tags/notes dal registry
                if preview:
                    # Unisce i campi del registry (enriched_org, encoding, etc.)
                    _enc(preview)
                return preview

    # HTML fallback: landing_page reachable
    landing = row.get("landing_page")
    if isinstance(landing, str) and landing.startswith("http"):
        if source_cfg.get("scraping_blocked") and not (protocol == "ckan" and not has_valid_slug):
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "scraping_blocked"
            return result
        # use content-type format from landing page
        fmt = _content_type_format(landing)
        if fmt:
            return _enc({
                "enriched_title": inv_title,
                "enriched_tags": inv_tags,
                "enriched_notes": inv_notes,
                "resource_url": landing,
                "resource_format": fmt,
                "granularity": inv_granularity,
                "year_min": row.get("year_signal"),
                "year_max": row.get("year_signal"),
                "enrich_method": "content_type_landing",
            })

    # No re-enrich possible — use inventory as-is
    return _enc({
        "enriched_title": inv_title,
        "enriched_tags": inv_tags,
        "enriched_notes": inv_notes,
        "resource_url": row.get("url") or row.get("landing_page"),
        "resource_format": inv_format,
        "granularity": inv_granularity,
        "year_min": row.get("year_signal"),
        "year_max": row.get("year_signal"),
        "enrich_method": "inventory_only",
    })


def _safe_str(v: Any) -> str | None:
    """Convert a value to string, handling pandas NaN."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v)


def _preview_meta_from_enrich(enrich: dict[str, Any]) -> dict[str, Any]:
    """Build preview_meta from enrich, ensuring col_types and columns are parquet-safe.

    Both col_types (dict) and columns (list) must be JSON-encoded as strings
    before writing the DataFrame to avoid ArrowTypeError on to_parquet.
    Nuovi campi toolkit (encoding_suggested, delim_suggested, ecc.) vengono
    propagati direttamente — sono già tipi semplici (str, int, bool, None).
    """
    import json as _json

    col_types_val = enrich.get("col_types")
    if isinstance(col_types_val, dict):
        col_types_val = _json.dumps(col_types_val)

    columns_val = enrich.get("columns")
    if isinstance(columns_val, list):
        columns_val = _json.dumps(columns_val)

    mapping_val = enrich.get("mapping_suggestions")
    if isinstance(mapping_val, dict):
        mapping_val = _json.dumps(mapping_val)
    elif not isinstance(mapping_val, str):
        # Forza "{}" invece di None per evitare che DuckDB inferisca
        # DOUBLE per la colonna (quando tutti i valori sono None).
        mapping_val = "{}"

    return {
        "file_size": enrich.get("file_size"),
        "preview_row_count": enrich.get("preview_row_count"),
        "col_types": col_types_val,
        "columns": columns_val,
        # Nuovi campi dal toolkit profiler
        "encoding_suggested": enrich.get("encoding_suggested"),
        "delim_suggested": enrich.get("delim_suggested"),
        "decimal_suggested": enrich.get("decimal_suggested"),
        "skip_suggested": enrich.get("skip_suggested"),
        "robust_read_suggested": enrich.get("robust_read_suggested"),
        "mapping_suggestions": mapping_val,
    }


def _normalize_preview_columns_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize preview metadata columns before parquet writes.

    Incremental runs concatenate new checks with previous parquet rows. Older
    rows may still contain Arrow struct/list values loaded back as dict/list or
    array-like values, so normalize the final DataFrame, not only newly-built
    row payloads.
    """
    import json as _json

    def _preview_cell_for_parquet(value: Any) -> Any:
        if isinstance(value, str) or value is None:
            return value
        if isinstance(value, dict):
            return _json.dumps(value, ensure_ascii=False)
        if isinstance(value, (list, tuple, set)):
            return _json.dumps(list(value), ensure_ascii=False)
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            converted = tolist()
            if isinstance(converted, dict):
                return _json.dumps(converted, ensure_ascii=False)
            if isinstance(converted, list):
                return _json.dumps(converted, ensure_ascii=False)
        return value

    normalized = df.copy()
    for column in ("col_types", "columns", "mapping_suggestions"):
        if column not in normalized.columns:
            continue
        normalized[column] = normalized[column].map(_preview_cell_for_parquet)
    return normalized


def _check_row(row: pd.Series, check_ts: str, registry: dict[str, Any]) -> dict:
    enrich = _enrich_with_inventory(row, registry)

    # granularità e anni: da enrichment, poi fallback su campi catalogo
    granularity = enrich["granularity"]
    year_min = enrich["year_min"]
    year_max = enrich["year_max"]
    # Bug 1 fix: pd.isna() handles NaN from pandas correctly (NaN is not None)
    if granularity == "non_determinato" or (granularity is None) or pd.isna(year_min):
        fb_gran, fb_ymin, fb_ymax = _fallback_infer(row)
        if granularity in (None, "non_determinato"):
            granularity = fb_gran
        if pd.isna(year_min):
            year_min = fb_ymin
        if pd.isna(year_max):
            year_max = fb_ymax

    # Preview dati reali: per ogni item con URL a file CSV/XLSX/XLS, scarica
    # un sample e profila con toolkit (encoding, delim, colonne, mapping).
    # Anni/granularità vengono aggiornati solo se i metadati non li hanno
    # già determinati — ma i campi di profiling (encoding_suggested, ecc.)
    # vengono SEMPRE popolati.
    preview_meta: dict[str, Any] = {}
    # Per inventory_only e content_type_landing, enrich["resource_url"] è
    # una landing page, non un file dati. In quei casi, distribution_url
    # dal catalogo è più probabile sia un URL diretto a file CSV/XLSX.
    # Per CKAN/SDMX/HTML, resource_url è già il file dati corretto.
    if enrich["enrich_method"] in ("inventory_only", "content_type_landing"):
        preview_url = (
            _safe_str(row.get("distribution_url"))
            or enrich.get("resource_url")
            or _safe_str(row.get("url"))
        )
    else:
        preview_url = (
            enrich.get("resource_url")
            or _safe_str(row.get("distribution_url"))
            or _safe_str(row.get("url"))
        )
    if isinstance(preview_url, str) and preview_url.startswith("http"):
        # Se l'inventory ha già sniffato encoding, passa i parametri noti
        # a _fetch_data_preview per saltare la fase di re-sniff.
        known_enc = enrich.get("encoding_suggested")
        if known_enc:
            preview = _fetch_data_preview(
                preview_url,
                known_encoding=known_enc,
                known_delim=enrich.get("delim_suggested"),
                known_decimal=enrich.get("decimal_suggested"),
                known_skip=enrich.get("skip_suggested"),
            )
        else:
            preview = _fetch_data_preview(preview_url)
        if preview.get("enrich_method") == "csv_preview":
            # Anni/granularità: solo se metadati non bastano
            if granularity in (None, "non_determinato") and preview.get("granularity"):
                granularity = preview["granularity"]
            if pd.isna(year_min) and preview.get("year_min") is not None:
                year_min = preview["year_min"]
            if pd.isna(year_max) and preview.get("year_max") is not None:
                year_max = preview["year_max"]
            # Campi profiling: SEMPRE popolati (encoding, delim, mapping, ecc.)
            preview_meta = _preview_meta_from_enrich(preview)

    # Se l'enrich ha gia' chiamato _fetch_data_preview ma non siamo rientrati
    # nel blocco sopra (perche' granularita' era gia' determinata),
    # propaga comunque i campi preview dall'enrich.
    if not preview_meta and enrich.get("enrich_method") == "csv_preview":
        preview_meta = _preview_meta_from_enrich(enrich)

    # URL da controllare: enrichment resource > catalogo landing_page > distribution_url
    url_to_check = (
        enrich.get("resource_url")
        or _safe_str(row.get("landing_page"))
        or _safe_str(row.get("distribution_url"))
    )
    # per SDMX la metadata_url non è un dato, usiamo la base_url per il check
    if enrich["enrich_method"] in ("sdmx_dataflow_annotations", "inventory_only"):
        url_to_check = row.get("landing_page") or row.get("distribution_url") or url_to_check

    # Se l'enrich ha già fatto un HEAD con successo (content_type/content_type_landing/html_scrape),
    # evitiamo un secondo HEAD ridondante sullo stesso URL.
    if enrich["enrich_method"] in ("content_type", "content_type_landing", "html_scrape"):
        http_status: int = 200
        reachable = True
        note = None
        content_type = None
    else:
        http_status_raw, reachable, note, content_type = _http_head_with_retry(url_to_check or "")
        http_status = http_status_raw if http_status_raw is not None else 0

        # Content-type format as primary detection (now unified in _http_head_with_retry)
    fmt_from_content = content_type

    return {
        "check_timestamp": check_ts,
        "source_id": row.get("source_id"),
        "item_id": row.get("item_id"),
        "item_name": row.get("item_name"),
        "title": enrich["enriched_title"] or row.get("title"),
        "organization": row.get("organization") if pd.notna(row.get("organization")) else enrich.get("enriched_org") or str(row.get("source_id", "")).upper(),
        "tags": enrich["enriched_tags"] or row.get("tags"),
        "notes": enrich["enriched_notes"],
        "url_checked": url_to_check,
        "http_status": http_status,
        "reachable": reachable,
        "check_notes": note or None,
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "resource_format": fmt_from_content or _normalize_format(enrich["resource_format"] or "") or _normalize_format(row.get("format") or ""),
        "enrich_method": enrich["enrich_method"],
        "file_size": preview_meta.get("file_size"),
        "preview_row_count": preview_meta.get("preview_row_count"),
        "col_types": preview_meta.get("col_types"),
        "columns": preview_meta.get("columns"),
        # Campi dal toolkit profiler: preview_meta se presente (da csv_preview),
        # altrimenti dall'enrich (da inventory sniff per content_type/landing/inventory_only)
        "encoding_suggested": preview_meta.get("encoding_suggested") or enrich.get("encoding_suggested"),
        "delim_suggested": preview_meta.get("delim_suggested") or enrich.get("delim_suggested"),
        "decimal_suggested": preview_meta.get("decimal_suggested") or enrich.get("decimal_suggested"),
        "skip_suggested": preview_meta.get("skip_suggested") or enrich.get("skip_suggested"),
        "robust_read_suggested": preview_meta.get("robust_read_suggested"),
        "mapping_suggestions": preview_meta.get("mapping_suggestions"),
        "source_status": row.get("source_status", "unknown"),
        "needs_review": (granularity == "non_determinato") or pd.isna(year_min),
        "intake_score": None,  # placeholder, calcolato sotto
        "intake_candidate": None,
        # SDMX — pass-through dal Dataflow XML per scaffold toolkit
        "sdmx_flow": enrich.get("sdmx_flow"),
        "sdmx_version": enrich.get("sdmx_version"),
        "sdmx_agency": enrich.get("sdmx_agency"),
    }


def run_bulk_check(df: pd.DataFrame, workers: int = MAX_WORKERS) -> pd.DataFrame:
    registry = _load_registry()
    check_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []

    # Per-source timing (stesso pattern di build_catalog_inventory)
    source_first_submit: dict[str, float] = {}
    source_last_done: dict[str, float] = {}
    source_item_count: dict[str, int] = {}
    source_error_count: dict[str, int] = {}

    _BULK_CHECK_TIMEOUT = 900  # 15 minuti per batch source-check (safety net)
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        # Usa enumerate per avere un indice posizionale garantito come int.
        # df.iterrows() restituisce un indice generico (Hashable) che mypy
        # non accetta per df.loc/df.iloc — con enumerate pos abbiamo int certo.
        future_to_idx = {}
        for pos, (_idx, row) in enumerate(df.iterrows()):
            f = pool.submit(_check_row, row, check_ts, registry)
            future_to_idx[f] = pos
            sid = str(row.get("source_id", ""))
            source_first_submit.setdefault(sid, time.time())
            source_item_count[sid] = source_item_count.get(sid, 0) + 1

        done = 0
        total = len(future_to_idx)
        for future in as_completed(future_to_idx, timeout=_BULK_CHECK_TIMEOUT):
            pos = future_to_idx[future]
            sid = str(df.iloc[pos].get("source_id", "")) if pos < len(df) else ""
            try:
                results.append(_finalize_scores(future.result()))
            except Exception as exc:
                logger.warning("Row check failed for index %d: %s", pos, exc)
                # Mantieni item_id e source_id anche in caso di fallimento,
                # altrimenti il merge upsert (riga 743) crasha su results["item_id"]
                # quando TUTTI i check falliscono (es. fonte temporaneamente down).
                fallback_row = dict(df.iloc[pos]) if pos < len(df) else {}
                results.append({
                    "item_id": str(fallback_row.get("item_id", "")),
                    "source_id": str(fallback_row.get("source_id", "")),
                    "check_notes": f"check failed: {exc}",
                    "enrich_method": "error",
                })
                source_error_count[sid] = source_error_count.get(sid, 0) + 1
            source_last_done[sid] = time.time()
            done += 1
            if done % 50 == 0 or done == total:
                logger.info("  %d/%d completed", done, total)
    except TimeoutError:
        logger.warning("Source-check timeout after %ds (%d/%d items processed)",
                       _BULK_CHECK_TIMEOUT, done, total)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # ── Per-source timing table ───────────────────────────────────────────────────
    if source_item_count:
        print()
        print(f"{'Source':<24} {'Items':<8} {'Errors':<8} {'Time':<8}  {'Note'}")
        print("-" * 64)
        now = time.time()
        for sid in sorted(source_item_count):
            first = source_first_submit.get(sid, now)
            last = source_last_done.get(sid)
            if last is None:
                # fonte non completata (timeout batch): stima con timeout globale
                elapsed = float(_BULK_CHECK_TIMEOUT)
                note = "timeout"
            else:
                elapsed = last - first
                note = "ok"
            errs = source_error_count.get(sid, 0)
            if errs:
                note = f"{errs} error(s)"
            print(f"{sid:<24} {source_item_count[sid]:<8} {errs:<8} {elapsed:>6.1f}s  {note}")
        print()

    return pd.DataFrame(results)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="input", type=Path, default=DEFAULT_IN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--source-ids", nargs="+", metavar="ID")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--limit-per-source", type=int, default=None, metavar="N",
                   help="Massimo N item per source_id (applicato prima del check)")
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    p.add_argument("--max-age-days", type=int, default=None,
                   help="Non ri-controllare item con check_timestamp più recente di N giorni. Default: None (nessun skip — tutti gli item vengono controllati)")
    p.add_argument("--max-items", type=int, default=500,
                   help="Target massimo di item da processare per run. Prioritize: items senza format + sample random. Default: 500")
    p.add_argument("--include-no-url", dest="only_with_url", action="store_false", default=True,
                   help="Includi anche item senza URL nel catalogo (verranno comunque arricchiti via API)")
    p.add_argument("--only-with-title", action="store_true", default=False,
                   help="Salta item senza title nel catalogo (tipicamente righe non-sample senza metadati)")
    p.add_argument("--skip-red-sources", action="store_true", default=False,
                   help="Skip item da fonti con status RED in radar_summary.json (evita timeout su fonti down)")
    p.add_argument("--no-sdmx-years", action="store_true", default=False,
                   help="Skip SDMX year fetch (riduce timeout risk su CI)")
    p.add_argument(
        "--circuit-fail-threshold",
        type=int,
        default=0,
        metavar="N",
        help="Dopo N errori consecutivi (timeout/connessione/HTTP 5xx) sullo stesso host, "
        "salta ulteriori HEAD/GET per quel host nel run (0 = disabilitato).",
    )
    return p.parse_args()


def main() -> None:
    logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
    args = parse_args()
    global _NO_SDMX_YEARS
    _NO_SDMX_YEARS = args.no_sdmx_years

    configure_source_check_http(
        circuit_fail_threshold=args.circuit_fail_threshold,
        http_timeout=(4.0, 9.0),
        http_max_retries=1,
    )

    logger.info("Loading catalog: %s", args.input)
    df = pd.read_parquet(args.input)
    logger.info("  %d total items", len(df))

    if args.source_ids:
        df = df[df["source_id"].isin(args.source_ids)]
        logger.info("  source_ids filter %s: %d items", args.source_ids, len(df))

    if args.only_with_url:
        # SDMX items non hanno landing_page/distribution_url (accedono via API REST),
        # ma hanno api_base_url + item_name per l'enrichment.
        has_url = df["landing_page"].notna() | df["distribution_url"].notna() | (df["protocol"] == "sdmx")
        df = df[has_url]
        logger.info("  URL present in catalog filter: %d items", len(df))

    if args.only_with_title:
        df = df[df["title"].notna()]
        logger.info("  non-null title filter: %d items", len(df))

    # ── Skip RED sources from radar_summary ────────────────────────────────────
    # Evita di campionare item da fonti che timeoutmano su Actions (IP cloud blocked)
    # e allungano il source-check senza produrre valore.
    if args.skip_red_sources:
        radar_summary_path = REPO_ROOT / "data" / "radar" / "radar_summary.json"
        if radar_summary_path.exists():
            import json
            try:
                with radar_summary_path.open() as f:
                    radar = json.load(f)
                red_source_ids = [s["id"] for s in radar.get("sources", []) if s.get("status") == "RED"]
                if red_source_ids:
                    skipped = df["source_id"].isin(red_source_ids).sum()
                    df = df[~df["source_id"].isin(red_source_ids)]
                    logger.info("  skip RED sources (radar): %s — %d items rimossi", red_source_ids, skipped)
            except Exception as exc:
                logger.warning("  skip-red-sources: could not read radar_summary: %s", exc)
        else:
            logger.warning("  skip-red-sources: radar_summary.json not found at %s", radar_summary_path)

    if args.limit:
        df = df.head(args.limit)
        logger.info("  limit %d: %d items", args.limit, len(df))

    if args.limit_per_source:
        df = df.groupby("source_id", group_keys=False).head(args.limit_per_source)
        logger.info("  limit-per-source %d: %d items", args.limit_per_source, len(df))

    # ── Fix B: skip fonti interamente stale (calcolato PRIMA di Fix A) ─────────────
    # motivazione: se una fonte ha tutti i suoi item nello stato stale, skippiamo
    # l'intera fonte senza processarla. Meglio un warning che un skip silenzioso
    # per fonti che potrebbero essere temporaneamente down ma ancora utili.
    if "source_status" in df.columns and not df.empty:
        stale_sources = df.groupby("source_id")["source_status"].apply(lambda s: all(v == "stale" for v in s))
        stale_source_ids = stale_sources[stale_sources].index.tolist()
        if stale_source_ids:
            # logga ma non saltare — skip completo è troppo aggressivo per fonti
            # che potrebbero essere temporary down ma hanno dati ancora validi
            for sid in stale_source_ids:
                logger.warning("  %s: tutte le righe sono stale — verificare manualmente", sid)
            df = df[~df["source_id"].isin(stale_source_ids)]
            logger.info("  skip stale sources %s: %d items", stale_source_ids, len(df))

    if df.empty:
        logger.info("No items to check. Exiting.")
        return

    # ── Fix A: dedup per (source_id, item_id) — stesso dataset, formati multipli ───
    # tiene una riga per item_id per source, con preferenza CSV > JSON > XLSX > altro.
    # Nota: dedup su (source_id, item_id) e non solo item_id per evitare collisioni
    # cross-source se due fonti usano lo stesso item_id (allineato con Fix C in
    # build_catalog_inventory.py che deduplica su (source_id, item_id)).
    FORMAT_PREF = {"CSV": 0, "JSON": 1, "XLSX": 2, "XLS": 3}
    if not df.empty:
        df = df.copy()
        df["_fmt_pref"] = df["format"].map(lambda f: FORMAT_PREF.get(str(f).strip().upper(), 99))
        df = df.sort_values(["source_id", "_fmt_pref"])
        df = df.drop_duplicates(subset=["source_id", "item_id"], keep="first").drop(columns=["_fmt_pref"])
        logger.info("  dedup (source_id, item_id): %d items", len(df))

    if df.empty:
        logger.info("No items to check. Exiting.")
        return

    # ── Smart sampling per target size ───────────────────────────────────────────
    # Prioritize: items senza format (arricchimento needed) + random sample
    # per validation coverage
    if len(df) > args.max_items:
        # 70% of target: items without format (enrichment value)
        no_format = df[df["format"].isna() | (df["format"] == "")]
        target_no_format = int(args.max_items * 0.7)

        # 30% of target: random sample from items WITH format (validation)
        has_format = df[df["format"].notna() & (df["format"] != "")]
        target_has_format = args.max_items - target_no_format

        # Sample from each group (deterministic seed for reproducible runs)
        if len(no_format) > target_no_format:
            no_format_sample = no_format.sample(n=target_no_format, random_state=42)
        else:
            no_format_sample = no_format

        if len(has_format) > target_has_format:
            has_format_sample = has_format.sample(n=target_has_format, random_state=42)
        else:
            has_format_sample = has_format

        df = pd.concat([no_format_sample, has_format_sample]).reset_index(drop=True)
        logger.info("  smart sampling to %d items (no_format=%d, has_format=%d)",
                    len(df), len(no_format_sample), len(has_format_sample))

    # ── Logica incrementale ──────────────────────────────────────────────────────
    existing = None
    skipped = 0
    if args.out.exists():
        logger.info("Loading previous results: %s", args.out)
        existing = pd.read_parquet(args.out)
        logger.info("  %d previous results", len(existing))

        # Parsare check_timestamp come datetime se presente
        if "check_timestamp" in existing.columns:
            existing["check_timestamp"] = pd.to_datetime(existing["check_timestamp"], utc=True)

        # Filtra item da non ri-controllare (solo se max_age_days è specificato)
        if args.max_age_days is not None and "item_id" in existing.columns:
            now = pd.Timestamp.now(tz="UTC")
            cutoff = now - pd.Timedelta(days=args.max_age_days)

            # Trova gli item con check recente (più recente di cutoff)
            existing_recent = existing[existing["check_timestamp"] >= cutoff]
            recent_ids = set(str(x) for x in existing_recent["item_id"].astype(str).unique())

            # ── Secondo criterio: re-aggiungi item se la fonte ha aggiornato modified ──
            if "modified" in df.columns and not df.empty:
                # Prepara df per il merge
                df_modified = df[["item_id", "modified"]].copy()
                df_modified["item_id"] = df_modified["item_id"].astype(str)

                # Prepara existing_recent per il merge
                existing_for_merge = existing_recent[["item_id", "check_timestamp"]].copy()
                existing_for_merge["item_id"] = existing_for_merge["item_id"].astype(str)

                # Merge su item_id
                merge_df = pd.merge(
                    df_modified,
                    existing_for_merge,
                    on="item_id",
                    how="inner"
                )

                # Parsa modified come datetime
                merge_df["modified"] = pd.to_datetime(merge_df["modified"], utc=True, errors="coerce")

                # Filtra item dove modified > check_timestamp (e modified non è null)
                updated_mask = (merge_df["modified"].notna()) & (merge_df["modified"] > merge_df["check_timestamp"])
                updated_ids = set(merge_df[updated_mask]["item_id"].unique())

                # Rimuovi questi item da recent_ids (vanno ri-controllati)
                reinspected = len(recent_ids & updated_ids)
                if reinspected > 0:
                    recent_ids = recent_ids - updated_ids
                    logger.info("  %d items re-added because source updated modified", reinspected)

            # Filtra catalogo escludendo item recenti
            df_to_check = df[~df["item_id"].astype(str).isin(recent_ids)].copy()
            skipped = len(df) - len(df_to_check)

            if skipped > 0:
                logger.info("  Skipped %d items checked in last %d days", skipped, args.max_age_days)
            logger.info("  %d items to check", len(df_to_check))
            df = df_to_check
        elif "item_id" not in existing.columns:
            # skip dedup se no item_id
            logger.warning("  existing has no 'item_id' column, skipping dedup")
        # else: max_age_days=None → non skippare nessuno, check all (df unchanged)

    if df.empty:
        logger.info("No new items to check. Exiting.")
        return

    logger.info("Starting check on %d items (%d workers)...", len(df), args.workers)
    t0 = time.time()
    results = run_bulk_check(df, workers=args.workers)
    elapsed = time.time() - t0
    logger.info("Completed in %.1fs", elapsed)

    # ── Upsert ───────────────────────────────────────────────────────────────────
    if existing is not None and not existing.empty and "item_id" in existing.columns:
        # Tieni solo i risultati da existing che non sono stati ri-controllati
        existing_to_keep = existing[~existing["item_id"].astype(str).isin(results["item_id"].astype(str))]

        # Concatena nuovi risultati con quelli vecchi (non ri-controllati)
        results = pd.concat([results, existing_to_keep], ignore_index=True)

        # Deduplica su item_id tenendo la riga con check_timestamp più recente
        results["check_timestamp"] = pd.to_datetime(results["check_timestamp"], utc=True)
        results = results.sort_values("check_timestamp", ascending=False).drop_duplicates(subset=["source_id", "item_id"], keep="first").reset_index(drop=True)
        logger.info("  Unified %d results (new + previous not re-checked)", len(results))

    enrich_counts = results["enrich_method"].value_counts()
    reachable_n = results["reachable"].sum() if "reachable" in results.columns else 0
    reachable_pct = results["reachable"].mean() * 100 if "reachable" in results.columns else 0
    logger.info("Enrichment:\n%s", enrich_counts.to_string())
    logger.info("Reachable: %.0f%% (%d/%d)", reachable_pct, reachable_n, len(results))
    logger.info("Granularity:\n%s", results["granularity"].value_counts().to_string())
    logger.info("Needs review: %d", results["needs_review"].sum())
    if "intake_score" in results.columns:
        candidates = results["intake_candidate"].sum()
        avg_score = results["intake_score"].mean()
        logger.info("Intake candidates: %d/%d (avg score: %.0f)", candidates, len(results), avg_score)
        top = results[results["intake_candidate"].fillna(False)].nlargest(5, "intake_score")[["title","granularity","year_min","year_max","intake_score"]]
        if not top.empty:
            logger.info("Top candidates:\n%s", top.to_string(index=False))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    results = _normalize_preview_columns_for_parquet(results)
    results.to_parquet(args.out, index=False)
    logger.info("Results: %s", args.out)


if __name__ == "__main__":
    main()
