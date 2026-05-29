"""
Fetch fase per bulk source-check.

Strati:
  toolkit.scout.http  → funzioni HTTP/fetch condivise (probe, format, CKAN, SDMX, HTML)
  Questo modulo        → circuit breaker bulk + orchestrazione specifica SO
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Optional

from lab_connectors.http import HttpClient, HttpResult
from toolkit.scout.http import (
    fetch_ckan_package as _toolkit_ckan_package,
)
from toolkit.scout.http import (
    fetch_html_body as _toolkit_html_body,
)
from toolkit.scout.http import (
    fetch_sdmx_years as _toolkit_sdmx_years,
)
from toolkit.scout.http import (
    probe_url_headers as _toolkit_probe_headers,
)
from toolkit.scout.http import (
    resolve_preview_kind as _toolkit_preview_kind,
)

logger = logging.getLogger(__name__)

# ── Config HTTP (sovrascrivibile da configure_source_check_http) ──────────────

HTTP_TIMEOUT: tuple[float, float] = (5, 10)
_http_timeout: tuple[float, float] = (5.0, 10.0)
_http_max_retries = 2

# ── Circuit breaker per host (bulk-specific) ─────────────────────────────────

_circuit_threshold = 0
_cb_lock = threading.Lock()
_cb_consecutive: dict[str, int] = {}
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20[012]\d)(?!\d)")

SDMX_NS = {
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
}

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
    "sdmx_flow": None,
    "sdmx_version": None,
    "sdmx_agency": None,
}


# ── Config ───────────────────────────────────────────────────────────────────


def configure_source_check_http(
    *,
    circuit_fail_threshold: int = 3,
    http_timeout: tuple[float, float] | None = None,
    http_max_retries: int = 1,
) -> None:
    """Reimposta stato HTTP/circuit per un run di bulk_source_check."""
    global _circuit_threshold, _http_timeout, _http_max_retries
    with _cb_lock:
        _cb_consecutive.clear()
    _circuit_threshold = max(0, int(circuit_fail_threshold))
    if http_timeout is not None:
        _http_timeout = (float(http_timeout[0]), float(http_timeout[1]))
    _http_max_retries = max(1, int(http_max_retries))


# ── Circuit breaker helpers ──────────────────────────────────────────────────


def _netloc(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
        return (parsed.netloc or "").lower() or None
    except Exception:
        return None


def _circuit_should_block(url: str) -> bool:
    if _circuit_threshold <= 0:
        return False
    host = _netloc(url)
    if not host:
        return False
    with _cb_lock:
        return _cb_consecutive.get(host, 0) >= _circuit_threshold


def _circuit_after_result(url: str, result: HttpResult) -> None:
    if _circuit_threshold <= 0:
        return
    host = _netloc(url)
    if not host:
        return
    failed = result.err is not None or result.response is None or getattr(result.response, "status_code", 200) >= 500
    with _cb_lock:
        if failed:
            n = _cb_consecutive.get(host, 0) + 1
            _cb_consecutive[host] = n
            if n == _circuit_threshold:
                logger.warning("Circuit: host %s aperto dopo %d errori", host, n)
        else:
            _cb_consecutive[host] = 0


# ── Client HTTP con circuit breaker (usato da toolkit.scout) ──────────────────


def _get_circuit_client() -> HttpClient:
    """Crea HttpClient con timeout/retry configurati (senza circuit breaker built-in)."""
    return HttpClient(timeout=_http_timeout, max_retries=_http_max_retries)


def _tracked_http_head(url: str) -> HttpResult | None:
    """HEAD con circuit breaker. None = circuit aperto."""
    if not url.startswith("http") or _circuit_should_block(url):
        return None
    client = _get_circuit_client()
    result = client.head(url)
    _circuit_after_result(url, result)
    return result


def _tracked_http_get(url: str, **kwargs: Any) -> HttpResult | None:
    """GET con circuit breaker. None = circuit aperto."""
    if not url.startswith("http") or _circuit_should_block(url):
        return None
    client = _get_circuit_client()
    result = client.get(url, **kwargs)
    _circuit_after_result(url, result)
    return result


# ── Probe principale (usato da bulk_source_check) ────────────────────────────


def _http_head_with_retry(url: str, max_retries: int = 1) -> tuple[Optional[int], bool, str, Optional[str]]:
    """HTTP HEAD con retry e circuit breaker. Usa toolkit.scout per format detection.

    Mantiene _tracked_http_head per il circuit breaker (non usa direttamente toolkit
    per l'HTTP perché toolkit non ha circuit breaker). La format detection usa
    toolkit.scout.http.resolve_preview_kind invece che la vecchia _format_from_content_type.

    Returns: (status_code, reachable, error, content_type_format).
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid", None
    if _circuit_should_block(url):
        return None, False, "circuit_open", None

    last_error = ""

    for attempt in range(max_retries + 1):
        result = _tracked_http_head(url)
        if result is None:
            return None, False, "circuit_open", None

        if result.is_ok and result.response is not None:
            resp = result.response
            if resp.status_code >= 500 and attempt < max_retries:
                last_error = f"server_error_{resp.status_code}"
                time.sleep(0.5 * (attempt + 1))
                continue
            ct = resp.headers.get("Content-Type", "") or ""
            cd = resp.headers.get("Content-Disposition")
            # Format detection via toolkit (pure, no HTTP)
            fmt = _toolkit_preview_kind(url, ct, cd)
            reachable = resp.status_code < 400
            return resp.status_code, reachable, "", fmt

        if result.err is not None:
            err_name = type(result.err).__name__
            if "Timeout" in err_name and attempt < max_retries:
                last_error = "timeout"
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, False, err_name.lower(), None

        return None, False, last_error or "transient_error", None

    return None, False, last_error or "transient_error", None


# ── CKAN fetch (wrapper: adatta base_api SO a portal_url toolkit) ─────────────


def _fetch_ckan_package(base_api: str, item_name: str) -> Optional[dict]:
    """Fetch CKAN package_show. Usa toolkit.scout con client SO."""
    parsed = urllib.parse.urlparse(base_api)
    portal_url = f"{parsed.scheme}://{parsed.netloc}"
    client = _get_circuit_client()
    try:
        pkg = _toolkit_ckan_package(portal_url, item_name, client=client)
        if pkg is None:
            logger.warning("CKAN package_show returned None for %s (portal: %s)", item_name, portal_url)
        return pkg
    except Exception as exc:
        logger.error("CKAN package_show failed for %s (portal: %s): %s", item_name, portal_url, exc)
        return None


# ── SDMX years ───────────────────────────────────────────────────────────────


def _fetch_sdmx_years(
    base_url: str,
    flow_id: str,
    *,
    allow_fetch: bool = True,
) -> tuple[Optional[int], Optional[int]]:
    """SDMX years via toolkit.scout con allow_fetch SO."""
    if not allow_fetch:
        return None, None
    client = _get_circuit_client()
    try:
        return _toolkit_sdmx_years(base_url, flow_id, client=client)
    except Exception:
        return None, None


# ── SDMX dataflow annotations ────────────────────────────────────────────────


def _fetch_sdmx_dataflow(base_url: str, flow_id: str) -> Optional[ET.Element]:
    """Fetch SDMX dataflow definition XML (annotations con keywords). SO-specific URL construction."""
    base = base_url.split("?")[0].rstrip("/")
    if base.endswith("/IT1"):
        root_url = base
    else:
        root_url = base.rsplit("/", 1)[0]
    url = f"{root_url}/{flow_id}"
    client = _get_circuit_client()
    try:
        result = client.get(url, headers={"Accept": "application/xml"})
        if not result.is_ok or result.response is None:
            return None
        r = result.response
        if r.status_code != 200:
            return None
        return ET.fromstring(r.text)
    except Exception:
        return None


# ── HTML metadata (format detection) ─────────────────────────────────────────


def _fetch_html_metadata(url: str) -> dict:
    """Scarica HTML e cerca formato dati. Usa toolkit.scout.fetch_html_body."""
    if not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_invalid_url"
        return result
    client = _get_circuit_client()
    try:
        body = _toolkit_html_body(url, client=client)
        if not body or not body.get("html_text"):
            err = _EMPTY_ENRICH.copy()
            err["enrich_method"] = "html_scrape_fetch_failed"
            return err
        html = body["html_text"]
        resource_format: Optional[str] = None
        patterns = [
            (r'\.(csv|xlsx?|json|xml|zip|parquet)\b', 1),
            (r'["\']([^"\']+\.(csv|xlsx?|json|xml|zip|parquet))["\']', 1),
        ]
        for pattern, _gidx in patterns:
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


# ── Content-type format (probe HEAD → format) ────────────────────────────────


def _content_type_format(url: str) -> Optional[str]:
    """Formato da Content-Type via HEAD. Usa toolkit.scout con circuit breaker."""
    if not url.startswith("http"):
        return None
    client = _get_circuit_client()
    try:
        probe = _toolkit_probe_headers(url, client=client)
        return _toolkit_preview_kind(url, probe.get("content_type"), probe.get("content_disposition"))
    except Exception:
        return None


# ── Data preview (toolkit profiler + SO enrichment) ──────────────────────────


REGION_COLUMNS = ["regione", "region", "provincia", "province", "area", "territorio"]
COMUNE_COLUMNS = ["comune", "municip", "localita", "citta", "city"]
_YEAR_COLUMN_HINTS = ["anno", "year", "data", "date", "periodo", "period", "mese", "month"]


def _resolve_preview_kind(url: str) -> tuple[str | None, bool]:
    """Ritorna (kind, inferred_via_head). Usa toolkit per URL extension + HEAD probe."""
    kind = _toolkit_preview_kind(url)
    if kind is not None:
        return kind, False
    if not url.startswith("http"):
        return None, False
    try:
        probe = _toolkit_probe_headers(url, client=_get_circuit_client())
        kind = _toolkit_preview_kind(url, probe.get("content_type"), probe.get("content_disposition"))
        return kind, kind is not None
    except Exception:
        return None, False


def _fetch_data_preview(
    url: str,
    *,
    known_encoding: str | None = None,
    known_delim: str | None = None,
    known_decimal: str | None = None,
    known_skip: int | None = None,
) -> dict:
    """Fetch e parse content preview usando toolkit profiler + SO enrichment.

    Invariato rispetto a prima — la logica di profiling è già in toolkit.profile.raw.
    Le uniche differenze: usa _resolve_preview_kind piu' snello e _tracked_http_get
    per il download (con circuit breaker).
    """
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result

    kind, _preview_inferred_via_head = _resolve_preview_kind(url)
    if kind is None:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_skipped"
        return result

    fmt = kind.lower()
    resource_kind = kind

    try:
        if fmt in ("csv", "tsv", "json"):
            range_limit = 1 * 1024 * 1024
            sample_size = 100 * 1024
        else:
            range_limit = 5 * 1024 * 1024
            sample_size = None

        fetch_result = _tracked_http_get(url, headers={"Range": f"bytes=0-{range_limit - 1}"})
        if fetch_result is None:
            return _EMPTY_ENRICH.copy()
        if not fetch_result.is_ok or fetch_result.response is None:
            err = _EMPTY_ENRICH.copy()
            err["enrich_method"] = "csv_preview_fetch_failed"
            return err

        resp = fetch_result.response
        if resp.status_code >= 400:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "csv_preview_http_error"
            return result

        content = resp.content
        if sample_size is not None:
            content = content[:sample_size]
        elif len(content) > range_limit:
            result = _EMPTY_ENRICH.copy()
            result["enrich_method"] = "csv_preview_skipped_too_large"
            return result
        try:
            file_size = int(resp.headers.get("Content-Length", "0"))
        except (ValueError, TypeError):
            file_size = 0
        if file_size <= 0:
            file_size = len(resp.content)

        import json as _json
        import tempfile
        from pathlib import Path

        from toolkit.profile.raw import profile_with_read_cfg, sniff_source_file

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

        if fmt == "tsv":
            tmp_suffix = ".csv"
        elif fmt == "json":
            tmp_suffix = ".json"
        else:
            tmp_suffix = f".{fmt}"
        with tempfile.NamedTemporaryFile(suffix=tmp_suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            if known_encoding:
                encoding_suggested = known_encoding
                delim_suggested = known_delim
                decimal_suggested = known_decimal
                skip_suggested = known_skip or 0
                sniff: dict[str, Any] = {"true_header_line": None, "warnings": []}
            else:
                sniff = sniff_source_file(tmp_path)
                encoding_suggested = sniff.get("encoding_suggested")
                delim_suggested = sniff.get("delim_suggested")
                decimal_suggested = sniff.get("decimal_suggested")
                skip_suggested = sniff.get("skip_suggested", 0)

            if fmt in ("csv", "tsv"):
                effective_read_cfg: dict[str, Any] = {
                    "encoding": encoding_suggested,
                    "delim": delim_suggested,
                    "decimal": decimal_suggested,
                    "skip": skip_suggested,
                    "header": True,
                }
                if fmt == "tsv":
                    effective_read_cfg["delim"] = "\t"

                profile = profile_with_read_cfg(tmp_path, sniff, effective_read_cfg)
                columns = profile.get("columns_raw", [])
                types_map = profile.get("duckdb_types", [])
                if columns and types_map and len(columns) == len(types_map):
                    col_types = dict(zip(columns, types_map))
                sample = profile.get("sample_rows", [])
                preview_row_count = len(sample) if sample else None
                mapping_suggestions = profile.get("mapping_suggestions")
                robust_read_suggested = profile.get("robust_read_suggested", False)
                if sample:
                    for col in columns:
                        vals = [r.get(col) for r in sample if isinstance(r.get(col), (int, float))]
                        if vals:
                            y_vals = [int(v) for v in vals if 1900 <= int(v) <= 2100]
                            if len(y_vals) >= 2:
                                year_values = y_vals
                                break
                    if not year_values:
                        for col in columns:
                            if col.lower() in _YEAR_COLUMN_HINTS:
                                vals = [r.get(col) for r in sample if isinstance(r.get(col), (int, float))]
                                if vals:
                                    year_values = [int(v) for v in vals]
                                    break

            elif fmt in ("xlsx", "xls"):
                from toolkit.profile.raw import profile_excel

                read_cfg_excel = {"header": True, "skip": skip_suggested}
                excel_result = profile_excel(tmp_path, read_cfg_excel)
                excel_cols = excel_result.get("columns_raw", [])
                if excel_cols:
                    columns = excel_cols
                    preview_row_count = len(excel_result.get("sample_rows", []))
                    robust_read_suggested = excel_result.get("robust_read_suggested", False)
                    sample = excel_result.get("sample_rows", [])
                    if sample:
                        for col in columns:
                            vals = [r.get(col) for r in sample if isinstance(r.get(col), (int, float))]
                            if vals:
                                y_vals = [int(v) for v in vals if 1900 <= int(v) <= 2100]
                                if len(y_vals) >= 2:
                                    year_values = y_vals
                                    break
                else:
                    # Fallback: XLS falso (es. TSV mascherato da .xls) → prova come CSV
                    effective_read_cfg = {
                        "encoding": encoding_suggested or "utf-8",
                        "delim": delim_suggested or "\t",
                        "decimal": decimal_suggested or ".",
                        "skip": skip_suggested,
                        "header": True,
                    }
                    try:
                        profile = profile_with_read_cfg(tmp_path, sniff, effective_read_cfg)
                        columns = profile.get("columns_raw", [])
                        types_map = profile.get("duckdb_types", [])
                        if columns and types_map and len(columns) == len(types_map):
                            col_types = dict(zip(columns, types_map))
                        sample = profile.get("sample_rows", [])
                        preview_row_count = len(sample) if sample else None
                        robust_read_suggested = profile.get("robust_read_suggested", False)
                        if sample and columns:
                            for col in columns:
                                vals = [r.get(col) for r in sample if isinstance(r.get(col), (int, float))]
                                if vals:
                                    y_vals = [int(v) for v in vals if 1900 <= int(v) <= 2100]
                                    if len(y_vals) >= 2:
                                        year_values = y_vals
                                        break
                    except Exception:
                        pass

            elif fmt == "json":
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
            "resource_format": resource_kind.upper(),
            "enrich_method": "csv_preview",
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


# ── Helpers interni ──────────────────────────────────────────────────────────


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
