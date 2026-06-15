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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _constants import (
    CHECK_PARQUET_PATH,
    INVENTORY_PARQUET_PATH,
    RADAR_SUMMARY_PATH,
    get_red_source_ids,
)
from _constants import (
    safe_str as _safe_str,
)
from lab_connectors.http import HttpClient
from source_check_analyze import (
    _fallback_infer,
    _finalize_scores,
    _infer_granularity,
    _infer_years,
    _normalize_format,
    _parse_ckan_package,
    add_dataset_group_columns,
)
from source_check_fetch import (
    _EMPTY_ENRICH,
    SDMX_NS,
    _fetch_data_preview,
    _fetch_html_metadata,
    _fetch_sdmx_dataflow,
    _fetch_sdmx_years,
    _fetch_sparql_count,
    _http_head_with_retry,
    configure_source_check_http,
)
from toolkit.scout.http import (
    fetch_ckan_package as _toolkit_ckan_package,
)
from toolkit.scout.http import (
    probe_url_headers as _toolkit_probe_headers,
)
from toolkit.scout.http import (
    resolve_preview_kind as _toolkit_preview_kind,
)

logger = logging.getLogger(__name__)

DEFAULT_IN = INVENTORY_PARQUET_PATH
DEFAULT_OUT = CHECK_PARQUET_PATH

MAX_WORKERS = 16
_NO_SDMX_YEARS = False  # set via --no-sdmx-years flag


# ── registry ─────────────────────────────────────────────────────────────────


def _load_registry() -> dict[str, Any]:
    from _constants import load_registry

    try:
        return load_registry()
    except Exception:
        return {}


# ── SDMX enrichment ───────────────────────────────────────────────────────────


def _parse_sdmx_annotations(
    xml_root: ET.Element, base_url: str, flow_id: str, client: HttpClient | None = None
) -> dict:
    annotations: dict[str, str] = {}
    for ann in xml_root.findall(".//common:Annotation", SDMX_NS):
        atype_el = ann.find("common:AnnotationType", SDMX_NS)
        atext_el = ann.find("common:AnnotationText", SDMX_NS)
        if atype_el is not None and atext_el is not None:
            annotations[atype_el.text or ""] = atext_el.text or ""

    keywords_raw = annotations.get("LAYOUT_DATAFLOW_KEYWORDS", "")
    # formato: "keyword1+keyword2+...+keyword3+..."
    keywords = [
        k.strip().lower() for part in keywords_raw.split("+") for k in part.split(",") if k.strip()
    ]

    combined = " ".join(keywords)
    granularity = _infer_granularity(combined)
    year_min, year_max = _infer_years(combined)

    # se le annotations non contengono anni, prova a ricavarli dall'endpoint dati
    if year_min is None:
        year_min, year_max = _fetch_sdmx_years(
            base_url, flow_id, client=client, allow_fetch=not _NO_SDMX_YEARS
        )

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


# ── dispatch enrich per protocollo ────────────────────────────────────────────


def _extract_base_enrich(row: pd.Series, registry: dict[str, Any]) -> dict:
    """Estrae i campi comuni dell'inventory + registry per tutti gli handler."""
    source_id = str(row.get("source_id", ""))
    source_cfg = registry.get(source_id, {})
    protocol = source_cfg.get("protocol") or row.get("protocol") or ""
    base_url = source_cfg.get("base_url") or row.get("source_url") or ""

    inv_title = row.get("title")
    inv_format = row.get("format")
    inv_tags = row.get("tags")
    inv_notes = row.get("notes_excerpt")
    inv_granularity = row.get("granularity")

    # Organizzazione: inventory > registry
    inv_org = row.get("organization")
    if not inv_org or pd.isna(inv_org):
        inv_org = source_id.upper() if source_id else None
    if pd.isna(inv_tags) or pd.isna(inv_notes):
        hp = source_cfg.get("html_portal") or {}
        topic_hint = hp.get("topic_hint") if isinstance(hp, dict) else None
        src_note = source_cfg.get("note", "") or ""
        if pd.isna(inv_tags) and topic_hint:
            inv_tags = topic_hint
        if pd.isna(inv_notes) and src_note:
            inv_notes = src_note[:300]

    _raw_name = row.get("item_name") or row.get("item_id")
    item_name = "" if pd.isna(_raw_name) else str(_raw_name)
    _slug = row.get("item_slug")
    if isinstance(_slug, str) and _slug.strip():
        item_name = _slug.strip()

    _VALID_FORMATS_FOR_SKIP = {"CSV", "JSON", "XLSX", "XLS", "XML", "PDF", "SDMX", "ZIP", "PARQUET"}
    inv_format_has_valid = isinstance(inv_format, str) and any(
        t.strip().upper() in _VALID_FORMATS_FOR_SKIP for t in inv_format.split(",")
    )
    has_valid_slug = bool(isinstance(_slug, str) and _slug.strip() and _slug.strip() != "dataset")

    return {
        "source_id": source_id,
        "source_cfg": source_cfg,
        "protocol": protocol,
        "base_url": base_url,
        "item_name": item_name,
        "inv_title": inv_title,
        "inv_format": inv_format,
        "inv_format_has_valid": inv_format_has_valid,
        "inv_tags": inv_tags,
        "inv_notes": inv_notes,
        "inv_granularity": inv_granularity,
        "inv_org": inv_org,
        "has_valid_slug": has_valid_slug,
    }


def _apply_encoding_to_enrich(r: dict, row: pd.Series, base: dict) -> dict:
    """Aggiunge encoding + org/tags/notes dal registry a un result dict."""
    r["encoding_suggested"] = _safe_str(row.get("encoding_suggested"))
    r["delim_suggested"] = _safe_str(row.get("delim_suggested"))
    r["decimal_suggested"] = _safe_str(row.get("decimal_suggested"))
    _skip = row.get("skip_suggested")
    r["skip_suggested"] = 0 if pd.isna(_skip) else int(_skip)
    r["enriched_org"] = base["inv_org"]
    r["enriched_tags"] = base["inv_tags"]
    r["enriched_notes"] = base["inv_notes"]
    return r


# ── Handler CKAN ──────────────────────────────────────────────────────────────


def _enrich_ckan(row: pd.Series, base: dict, client: HttpClient | None = None) -> dict | None:
    """Re-fetch package_show se inventory non ha format E title."""
    if base["protocol"] != "ckan" or not base["base_url"] or not base["item_name"]:
        return None
    if not base["has_valid_slug"]:
        return None
    if base["inv_format_has_valid"] and base["inv_title"]:
        return None  # inventory già ricco — skip re-fetch

    api_base_url = row.get("api_base_url")
    base_api = (
        api_base_url
        if isinstance(api_base_url, str) and api_base_url.startswith("http")
        else base["base_url"]
    )
    parsed = urllib.parse.urlparse(base_api)
    portal_url = f"{parsed.scheme}://{parsed.netloc}"
    pkg = _toolkit_ckan_package(portal_url, base["item_name"], client=client)
    if pkg:
        return _parse_ckan_package(pkg)
    return None


# ── Handler SDMX ──────────────────────────────────────────────────────────────


def _enrich_sdmx(row: pd.Series, base: dict, client: HttpClient | None = None) -> dict | None:
    """Legge annotations SDMX dal dataflow XML."""
    if base["protocol"] != "sdmx" or not base["base_url"] or not base["item_name"]:
        return None
    xml_root = _fetch_sdmx_dataflow(base["base_url"], base["item_name"], client=client)
    if xml_root is not None:
        return _parse_sdmx_annotations(xml_root, base["base_url"], base["item_name"], client=client)
    return None


# ── Handler HTML ──────────────────────────────────────────────────────────────


def _enrich_html(row: pd.Series, base: dict, client: HttpClient | None = None) -> dict | None:
    """Arricchimento HTML: content-type → preview download → landing page."""
    if base["protocol"] != "html":
        return None

    def _e(r: dict) -> dict:
        return _apply_encoding_to_enrich(r, row, base)

    # 1. content-type su data_url via toolkit (probe HEAD → format)
    data_url = row.get("url")
    if isinstance(data_url, str):
        try:
            probe = _toolkit_probe_headers(data_url, client=client)
        except RuntimeError:
            probe = {}
        fmt = _toolkit_preview_kind(
            data_url, probe.get("content_type"), probe.get("content_disposition")
        )
        if fmt:
            return _e(
                {
                    "enriched_title": base["inv_title"],
                    "enriched_tags": base["inv_tags"],
                    "enriched_notes": base["inv_notes"],
                    "resource_url": data_url,
                    "resource_format": fmt,
                    "granularity": base["inv_granularity"],
                    "year_min": row.get("year_signal"),
                    "year_max": row.get("year_signal"),
                    "enrich_method": "content_type",
                }
            )

    # 2. download preview per CSV/JSON/XLS
    if isinstance(data_url, str):
        parsed = urllib.parse.urlparse(data_url)
        path = parsed.path or ""
        fmt_ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if fmt_ext in ("csv", "json", "xlsx", "xls"):
            preview = _fetch_data_preview(data_url, client=client)
            if preview:
                _e(preview)
            return preview

    # 3. landing page
    landing = row.get("landing_page")
    if isinstance(landing, str) and landing.startswith("http"):
        # scraping_blocked: ritorna sentinel
        if base["source_cfg"].get("scraping_blocked"):
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "scraping_blocked"
            return result
        return _fetch_html_metadata(landing, client=client)

    return None


# ── Handler SPARQL ────────────────────────────────────────────────────────────


def _enrich_sparql(row: pd.Series, base: dict, client: HttpClient | None = None) -> dict | None:
    """Arricchimento SPARQL: probe semantico con COUNT + HEAD format.

    Usa query SPARQL COUNT per verificare che l'endpoint risponda e abbia
    dati. Se l'item ha un graph URI (item_id), conta triple in quel grafo.
    Fallback: HEAD probe sulla landing_page (backward compat).
    """
    if base["protocol"] != "sparql":
        return None

    # 1. Endpoint SPARQL: da config registry, non dall'item
    source_cfg = base.get("source_cfg", {})
    sparql_cfg = source_cfg.get("sparql") or {}
    endpoint = sparql_cfg.get("endpoint_url") or source_cfg.get("base_url", "")

    sparql_responding: bool | None = None
    sparql_triple_count: int | None = None

    if endpoint and isinstance(endpoint, str) and endpoint.startswith("http"):
        # 2a. Prova COUNT sul named graph (item_id = graph URI)
        item_id = row.get("item_id")
        if item_id and isinstance(item_id, str) and item_id.startswith("http"):
            count = _fetch_sparql_count(endpoint, graph_uri=item_id)
            if count is not None:
                sparql_responding = True
                sparql_triple_count = count
            else:
                sparql_responding = False
        else:
            # 2b. COUNT globale sull'endpoint
            count = _fetch_sparql_count(endpoint)
            if count is not None:
                sparql_responding = True
                sparql_triple_count = count
            else:
                sparql_responding = False

    # 3. Formato: HEAD probe su landing_page (backward compat)
    landing = (
        _safe_str(row.get("landing_page"))
        or _safe_str(row.get("url"))
        or _safe_str(row.get("source_url"))
    )
    fmt = "SPARQL"
    if landing and landing.startswith("http"):
        http_status_raw, reachable, note, content_type = _http_head_with_retry(
            landing, client=client
        )
        if content_type:
            fmt = _normalize_format(content_type)

    return _apply_encoding_to_enrich(
        {
            "enriched_title": base["inv_title"],
            "enriched_tags": base["inv_tags"],
            "enriched_notes": base["inv_notes"],
            "resource_url": endpoint or landing,
            "resource_format": fmt,
            "granularity": base.get("inv_granularity") or "non_determinato",
            "year_min": row.get("year_signal"),
            "year_max": row.get("year_signal"),
            "enrich_method": "sparql_probe",
            "sparql_responding": sparql_responding,
            "sparql_triple_count": sparql_triple_count,
        },
        row,
        base,
    )


# ── Inventory-only fallback ───────────────────────────────────────────────────


def _enrich_fallback(row: pd.Series, base: dict) -> dict:
    """Usa i dati inventory così come sono."""
    return _apply_encoding_to_enrich(
        {
            "enriched_title": base["inv_title"],
            "enriched_tags": base["inv_tags"],
            "enriched_notes": base["inv_notes"],
            "resource_url": row.get("url") or row.get("landing_page"),
            "resource_format": base["inv_format"],
            "granularity": base["inv_granularity"],
            "year_min": row.get("year_signal"),
            "year_max": row.get("year_signal"),
            "enrich_method": "inventory_only",
        },
        row,
        base,
    )


# ── Dispatch registry ─────────────────────────────────────────────────────────

_ENRICH_HANDLERS: dict[str, Any] = {
    "ckan": _enrich_ckan,
    "sdmx": _enrich_sdmx,
    "html": _enrich_html,
    "sparql": _enrich_sparql,
}

# ── Orchestrator ──────────────────────────────────────────────────────────────


def _enrich_with_inventory(
    row: pd.Series,
    registry: dict[str, Any],
    client: HttpClient | None = None,
) -> dict:
    """Enrich item usando inventory + dispatch per protocollo.

    Ogni handler puo' ritornare un dict di arricchimento (successo) o None
    (fall through). Se nessun handler riesce, usa inventory cosi' com'e'.

    Args:
        row: Riga del catalogo.
        registry: Registry delle fonti.
        client: HttpClient condiviso (con circuit breaker). Passato
            agli handler HTTP (CKAN, SDMX, HTML) per condividere stato.
    """
    base = _extract_base_enrich(row, registry)

    handler = _ENRICH_HANDLERS.get(base["protocol"])
    if handler:
        result = handler(row, base, client=client)
        if result is not None:
            return result

    return _enrich_fallback(row, base)


# _safe_str importata da _constants — non ridefinire localmente


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
        # PAQA quality score (toolkit v1.36.0+)
        "paqa_score": enrich.get("paqa_score"),
        "paqa_verdict": enrich.get("paqa_verdict"),
        "paqa_flags": enrich.get("paqa_flags"),
        "paqa_ontologies": enrich.get("paqa_ontologies"),
        "paqa_sampled": enrich.get("paqa_sampled"),
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


def _check_row(
    row: pd.Series, check_ts: str, registry: dict[str, Any], client: HttpClient | None = None
) -> dict:
    if client is None:
        client = configure_source_check_http()
    enrich = _enrich_with_inventory(row, registry, client=client)

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
    # SDMX: distribution_url è il CSV costruito dal collector
    # ({api_base}/data/{flow_id}/ALL/?format=csv). Prevale su resource_url
    # che punta all'endpoint SDMX (non un CSV profilabile).
    # SPARQL: distribution_url arriva da DCAT distribution/accessURL. Prevale
    # su resource_url che punta all'endpoint SPARQL.
    # inventory_only / content_type_landing: distribution_url dal catalogo
    # è più probabile sia un URL diretto a file CSV/XLSX.
    # CKAN/HTML: resource_url è già il file dati corretto.
    protocol = str(row.get("protocol", "")).lower()
    is_sdmx = protocol == "sdmx"
    is_sparql = protocol == "sparql"
    if is_sdmx or is_sparql:
        preview_url = (
            _safe_str(row.get("distribution_url"))
            or enrich.get("resource_url")
            or _safe_str(row.get("url"))
        )
    elif enrich["enrich_method"] in ("inventory_only", "content_type_landing"):
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
                client,
                known_encoding=known_enc,
                known_delim=enrich.get("delim_suggested"),
                known_decimal=enrich.get("decimal_suggested"),
                known_skip=enrich.get("skip_suggested"),
            )
        else:
            preview = _fetch_data_preview(preview_url, client)
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
        http_status_raw, reachable, note, content_type = _http_head_with_retry(
            url_to_check or "", client=client
        )
        http_status = http_status_raw if http_status_raw is not None else 0

        # Content-type format as primary detection (now unified in _http_head_with_retry)
    fmt_from_content = content_type

    return {
        "check_timestamp": check_ts,
        "source_id": row.get("source_id"),
        "item_id": row.get("item_id"),
        "item_name": row.get("item_name"),
        "title": enrich["enriched_title"] or row.get("title"),
        "organization": row.get("organization")
        if pd.notna(row.get("organization"))
        else enrich.get("enriched_org") or str(row.get("source_id", "")).upper(),
        "tags": enrich["enriched_tags"] or row.get("tags"),
        "notes": enrich["enriched_notes"],
        "url_checked": url_to_check,
        "http_status": http_status,
        "reachable": reachable,
        "check_notes": note or None,
        "granularity": granularity,
        "year_min": year_min,
        "year_max": year_max,
        "resource_format": fmt_from_content
        or _normalize_format(enrich["resource_format"] or "")
        or _normalize_format(row.get("format") or ""),
        "enrich_method": enrich["enrich_method"],
        "file_size": preview_meta.get("file_size"),
        "preview_row_count": preview_meta.get("preview_row_count"),
        "col_types": preview_meta.get("col_types"),
        "columns": preview_meta.get("columns"),
        # Campi dal toolkit profiler: preview_meta se presente (da csv_preview),
        # altrimenti dall'enrich (da inventory sniff per content_type/landing/inventory_only)
        "encoding_suggested": preview_meta.get("encoding_suggested")
        or enrich.get("encoding_suggested"),
        "delim_suggested": preview_meta.get("delim_suggested") or enrich.get("delim_suggested"),
        "decimal_suggested": preview_meta.get("decimal_suggested")
        or enrich.get("decimal_suggested"),
        "skip_suggested": preview_meta.get("skip_suggested") or enrich.get("skip_suggested"),
        "robust_read_suggested": preview_meta.get("robust_read_suggested"),
        "mapping_suggestions": preview_meta.get("mapping_suggestions"),
        # PAQA quality score (toolkit v1.36.0+)
        "paqa_score": preview_meta.get("paqa_score") or enrich.get("paqa_score"),
        "paqa_verdict": preview_meta.get("paqa_verdict") or enrich.get("paqa_verdict"),
        "paqa_flags": preview_meta.get("paqa_flags") or enrich.get("paqa_flags"),
        "paqa_ontologies": preview_meta.get("paqa_ontologies") or enrich.get("paqa_ontologies"),
        "paqa_sampled": preview_meta["paqa_sampled"]
        if "paqa_sampled" in preview_meta
        else enrich.get("paqa_sampled"),
        "source_status": row.get("source_status", "unknown"),
        "needs_review": (granularity == "non_determinato") or pd.isna(year_min),
        "intake_score": None,  # placeholder, calcolato sotto
        "intake_candidate": None,
        # SDMX — pass-through dal Dataflow XML per scaffold toolkit
        "sdmx_flow": enrich.get("sdmx_flow"),
        "sdmx_version": enrich.get("sdmx_version"),
        "sdmx_agency": enrich.get("sdmx_agency"),
        # SPARQL — verifica semantica endpoint
        "sparql_responding": enrich.get("sparql_responding"),
        "sparql_triple_count": enrich.get("sparql_triple_count"),
        # Protocol — propagato dal catalogo per il grouping SDMX
        "protocol": row.get("protocol"),
        # Distribution URL — usata internamente per preview/HEAD, propagata per tracciabilità
        "distribution_url": row.get("distribution_url"),
    }


def run_bulk_check(
    df: pd.DataFrame,
    workers: int = MAX_WORKERS,
    client: HttpClient | None = None,
) -> pd.DataFrame:
    registry = _load_registry()
    check_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []

    # Client HTTP condiviso con circuit breaker
    _owns_client = client is None
    client = client or configure_source_check_http()

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
            f = pool.submit(_check_row, row, check_ts, registry, client)
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
                # altrimenti il merge upsert crasha su results["item_id"]
                # quando TUTTI i check falliscono (es. fonte temporaneamente down).
                # Usa _finalize_scores per avere TUTTE le colonne attese dal logging.
                fallback_row = dict(df.iloc[pos]) if pos < len(df) else {}
                base = {
                    "item_id": str(fallback_row.get("item_id", "")),
                    "source_id": str(fallback_row.get("source_id", "")),
                    "check_notes": f"check failed: {exc}",
                    "enrich_method": "error",
                    "granularity": None,
                    "year_min": None,
                    "year_max": None,
                    "reachable": False,
                    "needs_review": True,
                }
                results.append(_finalize_scores(base))
                source_error_count[sid] = source_error_count.get(sid, 0) + 1
            source_last_done[sid] = time.time()
            done += 1
            if done % 50 == 0 or done == total:
                logger.info("  %d/%d completed", done, total)
    except TimeoutError:
        logger.warning(
            "Source-check timeout after %ds (%d/%d items processed)",
            _BULK_CHECK_TIMEOUT,
            done,
            total,
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        if _owns_client:
            client.close()

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
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--in", dest="input", type=Path, default=DEFAULT_IN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--source-ids", nargs="+", metavar="ID")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--limit-per-source",
        type=int,
        default=None,
        metavar="N",
        help="Massimo N item per source_id (applicato prima del check)",
    )
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    p.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        help="Non ri-controllare item con check_timestamp più recente di N giorni. Default: None (nessun skip — tutti gli item vengono controllati)",
    )
    p.add_argument(
        "--max-items",
        type=int,
        default=500,
        help="Target massimo di item da processare per run. Prioritize: items CON formato (CSV/JSON prima). Default: 500",
    )
    p.add_argument(
        "--include-no-url",
        dest="only_with_url",
        action="store_false",
        default=True,
        help="Includi anche item senza URL nel catalogo (verranno comunque arricchiti via API)",
    )
    p.add_argument(
        "--only-with-title",
        action="store_true",
        default=False,
        help="Salta item senza title nel catalogo (tipicamente righe non-sample senza metadati)",
    )
    p.add_argument(
        "--skip-red-sources",
        action="store_true",
        default=False,
        help="Skip item da fonti con status RED in radar_summary.json (evita timeout su fonti down)",
    )
    p.add_argument(
        "--no-sdmx-years",
        action="store_true",
        default=False,
        help="Skip SDMX year fetch (riduce timeout risk su CI)",
    )
    p.add_argument(
        "--circuit-fail-threshold",
        type=int,
        default=3,
        metavar="N",
        help="Dopo N errori consecutivi (timeout/connessione/HTTP 5xx) sullo stesso host, "
        "salta ulteriori HEAD/GET per quel host nel run (0 = disabilitato).",
    )
    return p.parse_args()


def _run_source_check(http_client: HttpClient, args: argparse.Namespace) -> None:
    """Esegue il source-check vero e proprio.

    Estratta da main() per garantire chiusura del client via try/finally.
    """
    logger.info("Loading catalog: %s", args.input)
    df = pd.read_parquet(args.input)
    logger.info("  %d total items", len(df))

    if args.source_ids:
        df = df[df["source_id"].isin(args.source_ids)]
        logger.info("  source_ids filter %s: %d items", args.source_ids, len(df))

    if args.only_with_url:
        # SDMX items non hanno landing_page/distribution_url (accedono via API REST),
        # ma hanno api_base_url + item_name per l'enrichment.
        has_url = (
            df["landing_page"].notna() | df["distribution_url"].notna() | (df["protocol"] == "sdmx")
        )
        df = df[has_url]
        logger.info("  URL present in catalog filter: %d items", len(df))

    if args.only_with_title:
        df = df[df["title"].notna()]
        logger.info("  non-null title filter: %d items", len(df))

    # ── Skip RED sources from radar_summary ────────────────────────────────────
    # Evita di campionare item da fonti che timeoutmano su Actions (IP cloud blocked)
    # e allungano il source-check senza produrre valore.
    if args.skip_red_sources:
        red_ids = get_red_source_ids()
        if red_ids:
            n_skipped = df["source_id"].isin(red_ids).sum()
            df = df[~df["source_id"].isin(red_ids)]
            logger.info("  skip RED sources (radar): %s — %d items rimossi", red_ids, n_skipped)
        elif not RADAR_SUMMARY_PATH.exists():
            logger.warning(
                "  skip-red-sources: radar_summary.json not found at %s", RADAR_SUMMARY_PATH
            )

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
        stale_sources = df.groupby("source_id")["source_status"].apply(
            lambda s: all(v == "stale" for v in s)
        )
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
        http_client.close()
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
        df = df.drop_duplicates(subset=["source_id", "item_id"], keep="first").drop(
            columns=["_fmt_pref"]
        )
        logger.info("  dedup (source_id, item_id): %d items", len(df))

    if df.empty:
        logger.info("No items to check. Exiting.")
        http_client.close()
        return

    # ── Smart sampling per target size ───────────────────────────────────────────
    # Priority: items WITH format (CSV/JSON/XLSX) first — they yield column profiles
    # and join keys. Items without format are deprioritized.
    if len(df) > args.max_items:
        has_format = df[df["format"].notna() & (df["format"] != "")]
        no_format = df[df["format"].isna() | (df["format"] == "")]

        # 80% of target: items WITH format (column profiling → joinability)
        target_has_format = int(args.max_items * 0.8)
        # 20% of target: items without format (enrichment only)
        target_no_format = args.max_items - target_has_format

        # Within has-format, prioritize CSV/JSON over XLSX over the rest
        def _fmt_priority(f: str) -> int:
            up = str(f).strip().upper()
            if "CSV" in up:
                return 0
            if "JSON" in up:
                return 1
            if "XLSX" in up or "XLS" in up:
                return 2
            return 3

        has_format = has_format.copy()
        has_format["_fmt_prio"] = has_format["format"].map(_fmt_priority)
        has_format = has_format.sort_values("_fmt_prio").drop(columns=["_fmt_prio"])

        # Sample from each group (deterministic seed for reproducible runs)
        if len(has_format) > target_has_format:
            has_format_sample = has_format.head(target_has_format)
        else:
            has_format_sample = has_format

        if len(no_format) > target_no_format:
            no_format_sample = no_format.sample(n=target_no_format, random_state=42)
        else:
            no_format_sample = no_format

        df = pd.concat([no_format_sample, has_format_sample]).reset_index(drop=True)
        logger.info(
            "  smart sampling to %d items (has_format=%d, no_format=%d)",
            len(df),
            len(has_format_sample),
            len(no_format_sample),
        )

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
                merge_df = pd.merge(df_modified, existing_for_merge, on="item_id", how="inner")

                # Parsa modified come datetime
                merge_df["modified"] = pd.to_datetime(
                    merge_df["modified"], utc=True, errors="coerce"
                )

                # Filtra item dove modified > check_timestamp (e modified non è null)
                updated_mask = (merge_df["modified"].notna()) & (
                    merge_df["modified"] > merge_df["check_timestamp"]
                )
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
                logger.info(
                    "  Skipped %d items checked in last %d days", skipped, args.max_age_days
                )
            logger.info("  %d items to check", len(df_to_check))
            df = df_to_check
        elif "item_id" not in existing.columns:
            # skip dedup se no item_id
            logger.warning("  existing has no 'item_id' column, skipping dedup")
        # else: max_age_days=None → non skippare nessuno, check all (df unchanged)

    if df.empty:
        logger.info("No new items to check. Exiting.")
        http_client.close()
        return

    logger.info("Starting check on %d items (%d workers)...", len(df), args.workers)
    t0 = time.time()
    results = run_bulk_check(df, workers=args.workers, client=http_client)
    elapsed = time.time() - t0
    logger.info("Completed in %.1fs", elapsed)

    # ── Upsert ───────────────────────────────────────────────────────────────────
    if existing is not None and not existing.empty and "item_id" in existing.columns:
        # Tieni solo i risultati da existing che non sono stati ri-controllati
        existing_to_keep = existing[
            ~existing["item_id"].astype(str).isin(results["item_id"].astype(str))
        ]

        # Concatena nuovi risultati con quelli vecchi (non ri-controllati)
        results = pd.concat([results, existing_to_keep], ignore_index=True)

        # Deduplica su item_id tenendo la riga con check_timestamp più recente
        results["check_timestamp"] = pd.to_datetime(results["check_timestamp"], utc=True)
        results = (
            results.sort_values("check_timestamp", ascending=False)
            .drop_duplicates(subset=["source_id", "item_id"], keep="first")
            .reset_index(drop=True)
        )
        logger.info("  Unified %d results (new + previous not re-checked)", len(results))

    # ── Dataset group columns ───────────────────────────────────────────────────
    # Raggruppa item multi-anno / multi-versione dello stesso dataset concettuale.
    # Aggiunge dataset_group, dataset_group_size, dataset_group_year_min/max.
    results = add_dataset_group_columns(results)
    ngroups = results["dataset_group"].nunique()
    logger.info(
        "  Dataset groups: %d unique groups (%.1f items/group average)",
        ngroups,
        len(results) / max(ngroups, 1),
    )

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
        logger.info(
            "Intake candidates: %d/%d (avg score: %.0f)", candidates, len(results), avg_score
        )
        top = results[results["intake_candidate"].fillna(False)].nlargest(5, "intake_score")[
            ["title", "granularity", "year_min", "year_max", "intake_score"]
        ]
        if not top.empty:
            logger.info("Top candidates:\n%s", top.to_string(index=False))

    # ── Riepilogo joinabilità ────────────────────────────────────────────────
    if "joinability_score" in results.columns:
        with_keys = results["join_keys"].notna().sum()
        avg_jscore = results["joinability_score"].mean()
        logger.info(
            "Joinability: %d/%d items with keys (avg score: %.1f)",
            with_keys,
            len(results),
            avg_jscore,
        )
        top_j = results[results["join_keys"].notna()].nlargest(5, "joinability_score")[
            ["title", "join_keys", "joinability_score", "intake_score"]
        ]
        if not top_j.empty:
            logger.info("Top joinable:\n%s", top_j.to_string(index=False))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    results = _normalize_preview_columns_for_parquet(results)
    results.to_parquet(args.out, index=False)
    logger.info("Results: %s", args.out)


def main() -> None:
    """Entry point: crea il client HTTP e avvia il source-check."""
    logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
    args = parse_args()
    global _NO_SDMX_YEARS
    _NO_SDMX_YEARS = args.no_sdmx_years

    http_client = configure_source_check_http(
        circuit_fail_threshold=args.circuit_fail_threshold,
        http_timeout=(4, 9),
        http_max_retries=1,
    )
    try:
        _run_source_check(http_client, args)
    finally:
        http_client.close()


if __name__ == "__main__":
    main()
