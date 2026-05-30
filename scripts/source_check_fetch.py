"""
Fetch fase per bulk source-check.

Strati:
  toolkit.scout.http  → funzioni HTTP/fetch condivise (probe, format, CKAN, SDMX, HTML)
  Questo modulo        → circuit breaker bulk + orchestrazione specifica SO
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
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


# ── Download phase ──────────────────────────────────────────────────────────


def _download_preview_content(url: str, fmt: str) -> tuple[bytes, int] | None:
    """Download a preview chunk of a data file.

    Returns ``(content: bytes, file_size: int)`` or ``None`` on any failure
    (HTTP error, connection error, oversized non-CSV file).  Caller should
    check ``enrich_method`` in the final result dict.
    """

    range_limit = 1 * 1024 * 1024 if fmt in ("csv", "tsv", "json") else 5 * 1024 * 1024
    sample_size = 100 * 1024 if fmt in ("csv", "tsv", "json") else None

    fetch_result = _tracked_http_get(url, headers={"Range": f"bytes=0-{range_limit - 1}"})
    if fetch_result is None:
        return None
    if not fetch_result.is_ok or fetch_result.response is None:
        return None

    resp = fetch_result.response
    if resp.status_code >= 400:
        return None
    content = resp.content
    if sample_size is not None:
        content = content[:sample_size]
    elif len(content) > range_limit:
        return None  # csv_preview_skipped_too_large

    try:
        file_size = int(resp.headers.get("Content-Length", "0"))
    except (ValueError, TypeError):
        file_size = 0
    if file_size <= 0:
        file_size = len(resp.content)
    return content, file_size


# ── Profiling phase ─────────────────────────────────────────────────────────


def _extract_year_values_from_sample(
    sample: list[dict],
    columns: list[str],
) -> list[int]:
    """Extract year values from sample rows.

    First tries numeric columns where at least 2 values are in 1900-2100
    (likely years), then falls back to columns whose name is a known
    year hint (``_YEAR_COLUMN_HINTS``).  Filters out NaN values that would
    crash ``int()``.
    """
    def _safe_ints(vals: list) -> list[int]:
        return [int(v) for v in vals if not (isinstance(v, float) and math.isnan(v))]

    year_values: list[int] = []
    if not sample:
        return year_values
    for col in columns:
        vals = [
            r.get(col) for r in sample
            if isinstance(r.get(col), (int, float))
        ]
        if vals:
            y_vals = [v for v in _safe_ints(vals) if 1900 <= v <= 2100]
            if len(y_vals) >= 2:
                return y_vals  # best signal: multiple years found
    if not year_values:
        for col in columns:
            if col.lower() in _YEAR_COLUMN_HINTS:
                vals = [
                    r.get(col) for r in sample
                    if isinstance(r.get(col), (int, float))
                ]
                if vals:
                    return _safe_ints(vals)
    return []


def _infer_granularity_from_columns(columns: list[str]) -> str:
    """Infer territorial granularity from column names."""
    if not columns:
        return "non_determinato"
    cols_lower = [c.lower() for c in columns]
    combined = " ".join(cols_lower)
    if any(c in combined for c in COMUNE_COLUMNS):
        return "comune"
    if any(c in combined for c in REGION_COLUMNS):
        return "regione"
    return "non_determinato"


def _profile_downloaded_csv(
    tmp_path: Path,
    sniff: dict[str, Any],
    fmt: str,
    encoding_suggested: str | None,
    delim_suggested: str | None,
    decimal_suggested: str | None,
    skip_suggested: int,
) -> dict:
    """Profile a CSV/TSV file via toolkit profiler.

    Returns a dict with keys: ``columns``, ``col_types``, ``preview_row_count``,
    ``mapping_suggestions``, ``robust_read_suggested``, ``year_values``.
    """
    from toolkit.profile.raw import profile_with_read_cfg

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
    col_types: dict[str, str] = {}
    if columns and types_map and len(columns) == len(types_map):
        col_types = dict(zip(columns, types_map))
    sample = profile.get("sample_rows", [])
    year_values = _extract_year_values_from_sample(sample, columns) if sample else []
    return {
        "columns": columns,
        "col_types": col_types,
        "preview_row_count": len(sample) if sample else None,
        "mapping_suggestions": profile.get("mapping_suggestions"),
        "robust_read_suggested": profile.get("robust_read_suggested", False),
        "year_values": year_values,
    }


def _profile_downloaded_excel(
    tmp_path: Path,
    sniff: dict[str, Any],
    encoding_suggested: str | None,
    delim_suggested: str | None,
    decimal_suggested: str | None,
    skip_suggested: int,
) -> dict:
    """Profile an XLSX/XLS file (or fallback to CSV for mislabeled files).

    Returns the same dict shape as ``_profile_downloaded_csv``.
    """
    from toolkit.profile.raw import profile_excel

    read_cfg_excel = {"header": True, "skip": skip_suggested}
    excel_result = profile_excel(tmp_path, read_cfg_excel)
    excel_cols = excel_result.get("columns_raw", [])
    if excel_cols:
        sample = excel_result.get("sample_rows", [])
        year_values = _extract_year_values_from_sample(sample, excel_cols) if sample else []
        return {
            "columns": excel_cols,
            "col_types": {},
            "preview_row_count": len(sample) if sample else None,
            "mapping_suggestions": None,
            "robust_read_suggested": excel_result.get("robust_read_suggested", False),
            "year_values": year_values,
        }

    # Fallback: XLS falso (es. TSV mascherato da .xls) → prova come CSV
    from toolkit.profile.raw import profile_with_read_cfg

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
        col_types: dict[str, str] = {}
        if columns and types_map and len(columns) == len(types_map):
            col_types = dict(zip(columns, types_map))
        sample = profile.get("sample_rows", [])
        year_values = _extract_year_values_from_sample(sample, columns) if sample else []
        return {
            "columns": columns,
            "col_types": col_types,
            "preview_row_count": len(sample) if sample else None,
            "mapping_suggestions": None,
            "robust_read_suggested": profile.get("robust_read_suggested", False),
            "year_values": year_values,
        }
    except Exception:
        return {
            "columns": [], "col_types": {},
            "preview_row_count": None,
            "mapping_suggestions": None,
            "robust_read_suggested": False,
            "year_values": [],
        }


def _profile_downloaded_json(content: bytes) -> dict:
    """Parse JSON content and extract structural metadata."""
    import json as _json

    text = content.decode("utf-8", errors="replace")
    columns: list[str] = []
    col_types: dict[str, str] = {}
    preview_row_count: int | None = None
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
    return {
        "columns": columns,
        "col_types": col_types,
        "preview_row_count": preview_row_count,
        "mapping_suggestions": None,
        "robust_read_suggested": False,
        "year_values": [],
    }


# ── Orchestrator ────────────────────────────────────────────────────────────


def _fetch_data_preview(
    url: str,
    *,
    known_encoding: str | None = None,
    known_delim: str | None = None,
    known_decimal: str | None = None,
    known_skip: int | None = None,
) -> dict:
    """Fetch e parse content preview usando toolkit profiler + SO enrichment.

    Orchestrator: delegates to ``_download_preview_content`` and then to the
    appropriate ``_profile_downloaded_*`` function based on format type.
    """
    import json as _json
    import tempfile

    from toolkit.profile.raw import sniff_source_file

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

    # ── Download ──────────────────────────────────────────────────────────
    downloaded = _download_preview_content(url, fmt)
    if downloaded is None:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_fetch_failed"
        return result

    content, file_size = downloaded

    # ── Temp file + sniff ────────────────────────────────────────────────
    tmp_suffix = ".csv" if fmt == "tsv" else f".{fmt}"
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
            if sniff.get("encoding_suggested") is not None:
                encoding_suggested = str(sniff.get("encoding_suggested"))
            delim_suggested = sniff.get("delim_suggested")
            decimal_suggested = sniff.get("decimal_suggested")
            skip_suggested = sniff.get("skip_suggested", 0)

        # ── Profile ─────────────────────────────────────────────────────
        if fmt in ("csv", "tsv"):
            p = _profile_downloaded_csv(
                tmp_path, sniff, fmt,
                encoding_suggested, delim_suggested, decimal_suggested, skip_suggested,
            )
        elif fmt in ("xlsx", "xls"):
            p = _profile_downloaded_excel(
                tmp_path, sniff,
                encoding_suggested, delim_suggested, decimal_suggested, skip_suggested,
            )
        elif fmt == "json":
            p = _profile_downloaded_json(content)
        else:
            p = {"columns": [], "col_types": {}, "preview_row_count": None,
                 "mapping_suggestions": None, "robust_read_suggested": False, "year_values": []}

        columns = p["columns"]
        col_types = p["col_types"]
        preview_row_count = p["preview_row_count"]
        mapping_suggestions = p["mapping_suggestions"]
        robust_read_suggested = p["robust_read_suggested"]
        year_values = p["year_values"]

        # ── Infer metadata ─────────────────────────────────────────────│
        granularity = _infer_granularity_from_columns(columns)
        year_min = min(year_values) if year_values else None
        year_max = max(year_values) if year_values else None

    finally:
        tmp_path.unlink(missing_ok=True)

    # ── Build result ────────────────────────────────────────────────────
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


# ── Helpers interni ──────────────────────────────────────────────────────────
