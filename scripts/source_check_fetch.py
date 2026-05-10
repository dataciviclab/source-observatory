"""
Fetch fase per bulk source-check.

Estratto da bulk_source_check.py per separare il "come scarico" dal "cosa ci faccio".
Usa lab_connectors.http (HttpClient) per le richieste HTTP, con SSL fallback built-in.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Optional

from lab_connectors.http import HttpClient

logger = logging.getLogger(__name__)

HTTP_TIMEOUT: tuple[float, float] = (5, 10)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20[012]\d)(?!\d)")

SDMX_NS = {
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
}

_SUPPORTED_FORMATS = ("JSON", "CSV", "XLSX", "XML", "PDF", "SDMX", "PARQUET")
_EXCEL_LEGACY = "excel"
_EXCEL_OOXML = "spreadsheetml"

_EMPTY_ENRICH: dict[str, Any] = {
    "enriched_title": None,
    "enriched_tags": None,
    "enriched_notes": None,
    "resource_url": None,
    "resource_format": None,
    "granularity": None,
    "year_min": None,
    "year_max": None,
    "enrich_method": None,
}


# ── helpers ────────────────────────────────────────────────────────────────


def _format_from_content_type(content_type: str) -> Optional[str]:
    ct = content_type or ""
    for fmt in _SUPPORTED_FORMATS:
        if fmt.lower() in ct.lower():
            return fmt
    if _EXCEL_LEGACY in ct.lower() and _EXCEL_OOXML not in ct.lower():
        return "XLS"
    if _EXCEL_OOXML in ct.lower():
        return "XLSX"
    return None


# ── HTTP HEAD with retry ───────────────────────────────────────────────────


def _http_head_with_retry(url: str, max_retries: int = 1) -> tuple[Optional[int], bool, str, Optional[str]]:
    """HTTP HEAD with retry su errori transienti, SSL fallback via HttpClient."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid", None

    client = HttpClient(timeout=HTTP_TIMEOUT)
    last_error = ""

    for attempt in range(max_retries + 1):
        result = client.head(url)

        if result.is_ok and result.response is not None:
            resp = result.response
            if resp.status_code >= 500 and attempt < max_retries:
                last_error = f"server_error_{resp.status_code}"
                time.sleep(0.5 * (attempt + 1))
                continue
            ct = resp.headers.get("Content-Type", "") or ""
            content_type = _format_from_content_type(ct)
            reachable = resp.status_code < 400
            return resp.status_code, reachable, "", content_type

        if result.err is not None:
            err_name = type(result.err).__name__
            if "Timeout" in err_name and attempt < max_retries:
                last_error = "timeout"
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, False, err_name.lower(), None

        return None, False, last_error or "transient_error", None

    return None, False, last_error or "transient_error", None


def _content_type_format(url: str) -> Optional[str]:
    """Extract format from Content-Type via HEAD."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    try:
        client = HttpClient(timeout=HTTP_TIMEOUT)
        result = client.head(url)
        if result.is_ok and result.response is not None:
            ct = result.response.headers.get("Content-Type", "") or ""
            return _format_from_content_type(ct)
    except Exception:
        pass
    return None


# ── CKAN fetch ─────────────────────────────────────────────────────────────


def _fetch_ckan_package(base_api: str, item_name: str) -> Optional[dict]:
    """Fetch CKAN package_show."""
    url = f"{base_api}/package_show?id={item_name}"
    try:
        client = HttpClient(timeout=HTTP_TIMEOUT)
        result = client.get(url)
        if result.is_ok and result.response is not None:
            r = result.response
            if r.status_code != 200:
                return None
            data = r.json()
            if not data.get("success"):
                return None
            return data.get("result")
    except Exception:
        pass
    return None


# ── SDMX fetch ─────────────────────────────────────────────────────────────


def _fetch_sdmx_years(
    base_url: str,
    flow_id: str,
    *,
    allow_fetch: bool = True,
) -> tuple[Optional[int], Optional[int]]:
    """Chiama l'endpoint dati SDMX per ricavare year_min/year_max dalla dimensione TIME_PERIOD.

    Args:
        base_url: URL base del servizio SDMX.
        flow_id: Identificativo del flusso SDMX.
        allow_fetch: Se False, salta la chiamata HTTP (rispetta --no-sdmx-years).
    """
    if not allow_fetch:
        return None, None
    try:
        base = base_url.split("?")[0].rstrip("/")
        if "/dataflow/" in base:
            sdmx_root = base[: base.index("/dataflow/")]
        elif base.endswith("/dataflow"):
            sdmx_root = base[: -len("/dataflow")]
        else:
            sdmx_root = base
        url = f"{sdmx_root}/data/{flow_id}?lastNObservations=1"
        client = HttpClient(timeout=HTTP_TIMEOUT)
        result = client.get(url, headers={"Accept": "application/xml"})
        if not result.is_ok or result.response is None:
            return None, None
        r = result.response
        if r.status_code != 200:
            return None, None
        root = ET.fromstring(r.text)
        time_values: list[str] = []
        for val_el in root.findall(".//generic:ObsKey/generic:Value", SDMX_NS):
            if val_el.get("id") == "TIME_PERIOD":
                v = val_el.get("value")
                if v:
                    time_values.append(v)
        for obs_el in root.findall(".//generic:Obs", SDMX_NS):
            v = obs_el.get("TIME_PERIOD")
            if v:
                time_values.append(v)
        for obs_el in root.findall(".//generic:ObsValue", SDMX_NS):
            v = obs_el.get("TIME_PERIOD")
            if v:
                time_values.append(v)
        years: list[int] = []
        for tv in time_values:
            found = _YEAR_RE.findall(tv)
            years.extend(int(y) for y in found)
        if not years:
            return None, None
        return min(years), max(years)
    except Exception:
        return None, None


def _fetch_sdmx_dataflow(base_url: str, flow_id: str) -> Optional[ET.Element]:
    """
    Fetch SDMX dataflow definition XML (contiene annotations con keywords).
    Mantiene la stessa logica URL dell'originale.
    """
    base = base_url.split("?")[0].rstrip("/")
    if base.endswith("/IT1"):
        root_url = base
    else:
        root_url = base.rsplit("/", 1)[0]
    url = f"{root_url}/{flow_id}"
    try:
        client = HttpClient(timeout=HTTP_TIMEOUT)
        result = client.get(url, headers={"Accept": "application/xml"})
        if result.is_ok and result.response is not None:
            r = result.response
            if r.status_code != 200:
                return None
            return ET.fromstring(r.text)
    except Exception:
        pass
    return None


# ── HTML fetch ─────────────────────────────────────────────────────────────


def _fetch_html_metadata(url: str) -> dict:
    """Scarica pagina HTML e cerca metadati (formato, link risorse)."""
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_invalid_url"
        return result

    try:
        client = HttpClient(timeout=HTTP_TIMEOUT)
        result = client.get(url)
        if not result.is_ok or result.response is None:
            err = _EMPTY_ENRICH.copy()
            err["enrich_method"] = "html_scrape_fetch_failed"
            return err

        r = result.response
        html = r.text

        resource_format: Optional[str] = None
        patterns = [
            (r'\.(csv|xlsx?|json|xml|zip|parquet)\b', 1),
            (r'["\']([^"\']+\.(csv|xlsx?|json|xml|zip|parquet))["\']', 1),
        ]
        for pattern, group_idx in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                filename = matches[0]
                if isinstance(matches[0], tuple):
                    filename = matches[0][0]
                ext = filename.rsplit(".", 1)[-1].upper() if "." in filename else None
                if ext:
                    resource_format = ext
                    break

        return {
            "enriched_title": None,
            "enriched_tags": None,
            "enriched_notes": None,
            "resource_url": None,
            "resource_format": resource_format,
            "granularity": None,
            "year_min": None,
            "year_max": None,
            "enrich_method": "html_scrape",
        }
    except Exception:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_failed"
        return result


# ── Data preview (toolkit profiler) ────────────────────────────────────────


REGION_COLUMNS = ["regione", "region", "provincia", "province", "area", "territorio"]
COMUNE_COLUMNS = ["comune", "municip", "localita", "citta", "city"]

# Colonne il cui nome suggerisce valori anno — fallback se la detection
# automatica da dati numerici non trova nulla
_YEAR_COLUMN_HINTS = ["anno", "year", "data", "date", "periodo", "period", "mese", "month"]


def _fetch_data_preview(url: str) -> dict:
    """Fetch e parse content preview usando il profiler del toolkit.

    Usa sniff_source_file + profile_with_read_cfg (DuckDB) invece di pandas
    diretto. Gestisce encoding, delimitatore, decimale e skip in modo robusto,
    anche per CSV italiani (latin-1, ; come delim, , come decimale).

    Returns dict in formato _EMPTY_ENRICH con campi aggiuntivi:
    - columns: list[str] (JSON-encoded)
    - col_types: dict[str, str] (JSON-encoded)
    - year_min, year_max
    - granularity
    - file_size: int (bytes)
    - preview_row_count: int | None
    - encoding_suggested, delim_suggested, decimal_suggested, skip_suggested
    - mapping_suggestions: dict (JSON-encoded, pronto per intake)
    - robust_read_suggested: bool
    - enrich_method: "csv_preview"
    """
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result

    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    fmt = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if fmt not in ("csv", "json", "xlsx", "xls"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_skipped"
        return result

    try:
        client = HttpClient(timeout=HTTP_TIMEOUT)
        fetch_result = client.get(url)
        if not fetch_result.is_ok or fetch_result.response is None:
            err = _EMPTY_ENRICH.copy()
            err["enrich_method"] = "csv_preview_fetch_failed"
            return err

        resp = fetch_result.response
        if resp.status_code >= 400:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "csv_preview_http_error"
            return result

        # Usa solo primi ~100KB per preview.
        content = resp.content[:100 * 1024]
        try:
            file_size = int(resp.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            file_size = 0
        if file_size <= 0:
            file_size = len(resp.content)

        import json as _json
        import tempfile
        from pathlib import Path
        from toolkit.profile.raw import sniff_source_file, profile_with_read_cfg

        columns: list[str] = []
        col_types: dict[str, str] = {}
        preview_row_count: int | None = None
        year_min: Optional[int] = None
        year_max: Optional[int] = None
        granularity = "non_determinato"
        year_values: list[int] = []
        encoding_suggested: str | None = None
        delim_suggested: str | None = None
        decimal_suggested: str | None = None
        skip_suggested: int = 0
        mapping_suggestions: dict | None = None
        robust_read_suggested: bool = False

        # Salva il contenuto in un file temporaneo per usare il profiler toolkit
        ext = f".{fmt}"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            # Phase 1: sniff — encoding, delim, decimal, skip, binary detection
            sniff = sniff_source_file(tmp_path)
            encoding_suggested = sniff.get("encoding_suggested")
            delim_suggested = sniff.get("delim_suggested")
            decimal_suggested = sniff.get("decimal_suggested")
            skip_suggested = sniff.get("skip_suggested", 0)

            is_binary = sniff.get("is_binary_file")

            if fmt == "csv" and not is_binary:
                # CSV: profiling DuckDB con sniff
                effective_read_cfg: dict[str, Any] = {
                    "encoding": encoding_suggested,
                    "delim": delim_suggested,
                    "decimal": decimal_suggested,
                    "skip": skip_suggested,
                    "header": True,
                }

                profile = profile_with_read_cfg(tmp_path, sniff, effective_read_cfg)
                columns = profile.get("columns_raw", [])
                types_map = profile.get("duckdb_types", [])
                if columns and types_map and len(columns) == len(types_map):
                    col_types = dict(zip(columns, types_map))
                else:
                    col_types = {}

                sample = profile.get("sample_rows", [])
                preview_row_count = len(sample) if sample else None
                mapping_suggestions = profile.get("mapping_suggestions")
                robust_read_suggested = profile.get("robust_read_suggested", False)

                # Year detection: scorri TUTTE le colonne numeriche dai sample rows
                # (non solo quelle con nome in YEAR_COLUMNS)
                if sample:
                    for col in columns:
                        vals = []
                        for row in sample:
                            v = row.get(col)
                            if isinstance(v, (int, float)):
                                vals.append(v)
                        if vals:
                            # Filtra valori che sembrano anni (1900-2100)
                            y_vals = [int(v) for v in vals if v and 1900 <= int(v) <= 2100]
                            if len(y_vals) >= 2:
                                year_values = y_vals
                                break

                    # Fallback: se nessuna colonna numerica ha valori anno,
                    # prova colonne con nome in YEAR_COLUMN_HINTS
                    if not year_values:
                        for col in columns:
                            if col.lower() in _YEAR_COLUMN_HINTS:
                                vals = [r.get(col) for r in sample]
                                numeric_vals = [int(v) for v in vals if isinstance(v, (int, float))]
                                if numeric_vals:
                                    year_values = numeric_vals
                                    break

            elif fmt in ("xlsx", "xls") and is_binary in ("xlsx", "xls"):
                # Excel: usa _profile_excel dal toolkit (stesso reader del runtime clean)
                from toolkit.profile.raw import _profile_excel

                read_cfg_excel = {"header": True, "skip": skip_suggested}
                excel_result = _profile_excel(tmp_path, read_cfg_excel)
                columns = excel_result.get("columns_raw", [])
                preview_row_count = len(excel_result.get("sample_rows", []))
                col_types = {}
                robust_read_suggested = excel_result.get("robust_read_suggested", False)

                # Year detection su Excel: stessi criteri del CSV
                sample = excel_result.get("sample_rows", [])
                if sample:
                    for col in columns:
                        vals = []
                        for row in sample:
                            v = row.get(col)
                            if isinstance(v, (int, float)):
                                vals.append(v)
                        if vals:
                            y_vals = [int(v) for v in vals if v and 1900 <= int(v) <= 2100]
                            if len(y_vals) >= 2:
                                year_values = y_vals
                                break

            elif fmt in ("xlsx", "xls") and not is_binary:
                # XLS/XLSX falso: magic bytes non corrispondono a Excel.
                # Prova a trattarlo come CSV con sniff (es. file TSV mascherato
                # da estensione .xls con encoding Latin-1).
                effective_read_cfg = {
                    "encoding": encoding_suggested,
                    "delim": delim_suggested,
                    "decimal": decimal_suggested,
                    "skip": skip_suggested,
                    "header": True,
                }
                try:
                    profile = profile_with_read_cfg(tmp_path, sniff, effective_read_cfg)
                    columns = profile.get("columns_raw", [])
                    types_map = profile.get("duckdb_types", [])
                    if columns and types_map and len(columns) == len(types_map):
                        col_types = dict(zip(columns, types_map))
                    else:
                        col_types = {}
                    sample = profile.get("sample_rows", [])
                    preview_row_count = len(sample) if sample else None
                    robust_read_suggested = profile.get("robust_read_suggested", False)
                    # Year detection (same as CSV branch)
                    if sample:
                        for col in columns:
                            vals = [r.get(col) for r in sample if isinstance(r.get(col), (int, float))]
                            if vals:
                                y_vals = [int(v) for v in vals if v and 1900 <= int(v) <= 2100]
                                if len(y_vals) >= 2:
                                    year_values = y_vals
                                    break
                except Exception:
                    pass

            elif fmt == "json":
                # JSON: keep existing logic (toolkit doesn't profile JSON)
                text = content.decode("utf-8", errors="replace")
                try:
                    data = _json.loads(text)
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        columns = list(data[0].keys())
                        col_types = {str(k): type(v).__name__ for k, v in data[0].items()}
                        preview_row_count = len(data)
                    elif isinstance(data, dict):
                        columns = list(data.keys())
                except Exception:
                    pass

            # Granularità da nomi colonna
            if columns:
                cols_lower = [c.lower() for c in columns]
                if any(c in " ".join(cols_lower) for c in COMUNE_COLUMNS):
                    granularity = "comune"
                elif any(c in " ".join(cols_lower) for c in REGION_COLUMNS):
                    granularity = "regione"

            if year_values:
                year_min = min(year_values)
                year_max = max(year_values)

        finally:
            # Pulisce il file temporaneo
            tmp_path.unlink(missing_ok=True)

        result = _EMPTY_ENRICH.copy()
        result.update({
            "columns": _json.dumps(columns) if columns else None,
            "col_types": _json.dumps(col_types) if col_types else None,
            "file_size": file_size,
            "preview_row_count": preview_row_count,
            "year_min": year_min,
            "year_max": year_max,
            "granularity": granularity,
            "resource_format": fmt.upper(),
            "enrich_method": "csv_preview",
            # Nuovi campi dal toolkit
            "encoding_suggested": encoding_suggested,
            "delim_suggested": delim_suggested,
            "decimal_suggested": decimal_suggested,
            "skip_suggested": skip_suggested,
            "robust_read_suggested": robust_read_suggested,
            "mapping_suggestions": _json.dumps(mapping_suggestions) if isinstance(mapping_suggestions, dict) else "{}",
        })
        return result

    except Exception:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result


# ── internal helpers ───────────────────────────────────────────────────────


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
