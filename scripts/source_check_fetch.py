"""
Fetch fase per bulk source-check.

Estratto da bulk_source_check.py per separare il "come scarico" dal "cosa ci faccio".
Usa lab_connectors.http (HttpClient) per le richieste HTTP, con SSL fallback built-in.
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

# HTTP/fetch condivise da toolkit.scout (sostituiscono versioni locali)
from toolkit.scout.http import (
    DEFAULT_TIMEOUT,
    fetch_ckan_package as _toolkit_ckan_package,
    fetch_html_body as _toolkit_html_body,
    fetch_sdmx_years as _toolkit_sdmx_years,
)

logger = logging.getLogger(__name__)

# Default HTTP (retro-compatibile se configure_source_check_http non è chiamato).
HTTP_TIMEOUT: tuple[float, float] = (5, 10)
_http_timeout: tuple[float, float] = (5.0, 10.0)
_http_max_retries = 2

# Circuit breaker per netloc: dopo N errori di trasporto/5xx consecutivi, salta HEAD/GET.
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

_SUPPORTED_FORMATS = ("JSON", "CSV", "XLSX", "XML", "PDF", "SDMX", "PARQUET")
_EXCEL_LEGACY = "excel"
_EXCEL_OOXML = "spreadsheetml"

# Estensioni path + formati inferibili da HEAD (source-check preview / toolkit profiler).
_PREVIEW_KINDS = frozenset({"csv", "json", "xlsx", "xls", "tsv"})
_CD_FILENAME_STAR_RE = re.compile(r"filename\*=(?:UTF-8''|utf-8'')([^;\s]+)", re.I)
_CD_FILENAME_DQ_RE = re.compile(r'filename="([^"]+)"', re.I)
_CD_FILENAME_TOKEN_RE = re.compile(r"filename=([^;\s]+)", re.I)

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
    # SDMX — popolati solo per item SDMX (flow, version, agency da Dataflow XML)
    "sdmx_flow": None,
    "sdmx_version": None,
    "sdmx_agency": None,
}


def configure_source_check_http(
    *,
    circuit_fail_threshold: int = 3,
    http_timeout: tuple[float, float] | None = None,
    http_max_retries: int = 1,
) -> None:
    """Reimposta stato HTTP/circuit per un run di bulk_source_check (o test).

    Args:
        circuit_fail_threshold: dopo N fallimenti consecutivi sullo stesso host
            (timeout/connessione/5xx), salta HEAD/GET per quel host (0 = disabilitato).
        http_timeout: override timeout (connect, read); default (4, 9) se None e main().
        http_max_retries: retry GET su errore transiente (default 1 in bulk).
    """
    global _circuit_threshold, _http_timeout, _http_max_retries
    with _cb_lock:
        _cb_consecutive.clear()
    _circuit_threshold = max(0, int(circuit_fail_threshold))
    if http_timeout is not None:
        _http_timeout = (float(http_timeout[0]), float(http_timeout[1]))
    _http_max_retries = max(1, int(http_max_retries))


def _mk_http_client() -> HttpClient:
    return HttpClient(timeout=_http_timeout, max_retries=_http_max_retries)


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
    failed = False
    if result.err is not None or result.response is None:
        failed = True
    elif getattr(result.response, "status_code", 200) >= 500:
        failed = True
    with _cb_lock:
        if failed:
            prev = _cb_consecutive.get(host, 0)
            n = prev + 1
            _cb_consecutive[host] = n
            if prev < _circuit_threshold <= n:
                logger.warning(
                    "Source-check circuit: host %s aperto dopo %d errori (soglia=%d)",
                    host,
                    n,
                    _circuit_threshold,
                )
        else:
            _cb_consecutive[host] = 0


def _tracked_http_head(url: str) -> HttpResult | None:
    """HEAD con circuit. None = circuit aperto (nessuna richiesta inviata)."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    if _circuit_should_block(url):
        return None
    client = _mk_http_client()
    result = client.head(url)
    _circuit_after_result(url, result)
    return result


def _tracked_http_get(url: str, **kwargs: Any) -> HttpResult | None:
    """GET con circuit. None = circuit aperto."""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    if _circuit_should_block(url):
        return None
    client = _mk_http_client()
    result = client.get(url, **kwargs)
    _circuit_after_result(url, result)
    return result


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


def _filename_from_content_disposition(value: str | None) -> str | None:
    """Estrae il nome file da Content-Disposition (RFC 5987 / quoted)."""
    if not value or not isinstance(value, str):
        return None
    m = _CD_FILENAME_STAR_RE.search(value)
    if m:
        raw = m.group(1).strip().strip('"')
        return urllib.parse.unquote(raw) if raw else None
    m = _CD_FILENAME_DQ_RE.search(value)
    if m:
        return m.group(1).strip() or None
    m = _CD_FILENAME_TOKEN_RE.search(value)
    if m:
        return m.group(1).strip().strip('"') or None
    return None


def _path_extension_kind(url: str) -> str | None:
    """Ultima estensione path (minuscolo), mappata su kind preview."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if "." not in path:
        return None
    ext = path.rsplit(".", 1)[-1].lower()
    if ext in _PREVIEW_KINDS:
        return ext
    return None


def _infer_preview_kind_from_headers(content_type: str, content_disposition: str | None) -> str | None:
    """Deduce kind (csv, json, …) da Content-Type / Content-Disposition (nessun GET body)."""
    fn = _filename_from_content_disposition(content_disposition)
    if fn and "." in fn:
        ext = fn.rsplit(".", 1)[-1].lower()
        if ext in _PREVIEW_KINDS:
            return ext

    ct = (content_type or "").split(";")[0].strip()
    ct_low = ct.lower()
    if "tab-separated" in ct_low or ct_low in ("text/tsv", "application/tsv"):
        return "tsv"

    token = _format_from_content_type(ct)
    if token == "CSV":
        return "csv"
    if token == "JSON":
        return "json"
    if token == "XLSX":
        return "xlsx"
    if token == "XLS":
        return "xls"
    return None


def _resolve_preview_kind(url: str) -> tuple[str | None, bool]:
    """Ritorna (kind, inferred_via_head). kind=None → preview non applicabile."""
    direct = _path_extension_kind(url)
    if direct is not None:
        return direct, False

    if not isinstance(url, str) or not url.startswith("http"):
        return None, False
    try:
        result = _tracked_http_head(url)
        if result is None:
            return None, False
        if not result.is_ok or result.response is None:
            return None, False
        resp = result.response
        if resp.status_code >= 400:
            return None, False
        ct = resp.headers.get("Content-Type", "") or ""
        cd = resp.headers.get("Content-Disposition")
        inferred = _infer_preview_kind_from_headers(ct, cd)
        if inferred is not None:
            return inferred, True
    except Exception:
        return None, False
    return None, False


# ── HTTP HEAD with retry ───────────────────────────────────────────────────


def _http_head_with_retry(url: str, max_retries: int = 1) -> tuple[Optional[int], bool, str, Optional[str]]:
    """HTTP HEAD with retry su errori transienti, SSL fallback via HttpClient."""
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
    """Extract format from Content-Type via HEAD.
    
    Versione semplificata: usa toolkit.scout per il probe HTTP.
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    try:
        from toolkit.scout.http import probe_url_headers
        probe = probe_url_headers(url)
        return probe.get("content_type")
    except Exception:
        return None


# ── CKAN fetch (wrapper: adatta base_api di SO a portal_url di toolkit) ─────


def _fetch_ckan_package(base_api: str, item_name: str) -> Optional[dict]:
    """Fetch CKAN package_show usando toolkit.scout.http."""
    # toolkit.scout prende (portal_url, dataset_id, *, timeout).
    # base_api e' come "https://example.com/api/3/action".
    # Estraiamo il portal_url e delegiamo a toolkit.
    parsed = urllib.parse.urlparse(base_api)
    portal_url = f"{parsed.scheme}://{parsed.netloc}"
    try:
        return _toolkit_ckan_package(portal_url, item_name, timeout=_http_timeout[0] if isinstance(_http_timeout, tuple) else DEFAULT_TIMEOUT)
    except Exception:
        return None


# ── SDMX fetch ─────────────────────────────────────────────────────────────


def _fetch_sdmx_years(
    base_url: str,
    flow_id: str,
    *,
    allow_fetch: bool = True,
) -> tuple[Optional[int], Optional[int]]:
    """Chiama endpoint SDMX per anni, usando toolkit.scout.http.

    Mantiene il parametro allow_fetch (specifico SO) e lo gestisce
    prima di delegare a toolkit.
    """
    if not allow_fetch:
        return None, None
    try:
        timeout = _http_timeout[0] if isinstance(_http_timeout, tuple) else DEFAULT_TIMEOUT
        return _toolkit_sdmx_years(base_url, flow_id, timeout=timeout)
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
        result = _tracked_http_get(url, headers={"Accept": "application/xml"})
        if result is None or not result.is_ok or result.response is None:
            return None
        r = result.response
        if r.status_code != 200:
            return None
        return ET.fromstring(r.text)
    except Exception:
        pass
    return None


# ── HTML fetch (usa toolkit.scout.http) ────────────────────────────────────


def _fetch_html_metadata(url: str) -> dict:
    """Scarica pagina HTML e cerca metadati (formato), via toolkit.scout.http."""
    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_invalid_url"
        return result

    try:
        body = _toolkit_html_body(url)
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


def _fetch_data_preview(
    url: str,
    *,
    known_encoding: str | None = None,
    known_delim: str | None = None,
    known_decimal: str | None = None,
    known_skip: int | None = None,
) -> dict:
    """Fetch e parse content preview usando il profiler del toolkit.

    Usa sniff_source_file + profile_with_read_cfg (DuckDB) invece di pandas
    diretto. Gestisce encoding, delimitatore, decimale e skip in modo robusto,
    anche per CSV italiani (latin-1, ; come delim, , come decimale).

    Estensioni path supportate: csv, tsv, json, xlsx, xls.
    Se il path non ha estensione utile, esegue HTTP HEAD e deduce il formato da
    Content-Type / Content-Disposition (filename), poi GET con Range come per CSV.

    Se known_encoding è fornito (es. dall'inventory sniff), salta la fase di
    sniff (Phase 1) e va direttamente a DuckDB profiling con parametri noti.
    Questo evita di re-downloadare e re-sniffare item giá processati in fase
    di inventory build.

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

    kind, _preview_inferred_via_head = _resolve_preview_kind(url)
    if kind is None:
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_skipped"
        return result

    fmt = kind
    resource_kind = kind

    try:
        # CSV/JSON: sample 100KB basta per sniffare encoding/colonne.
        # XLS/XLSX: serve il file intero (e' uno ZIP con XML dentro).
        # Il Range header limita il download a 1MB o 5MB rispettivamente.
        if fmt in ("csv", "tsv", "json"):
            range_limit = 1 * 1024 * 1024  # 1MB
            sample_size = 100 * 1024        # 100KB sample
        else:
            range_limit = 5 * 1024 * 1024   # 5MB per XLSX/XLS
            sample_size = None              # usa tutto

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
        # CSV/JSON: sample 100KB. XLSX/XLS: intero contenuto scaricato.
        if sample_size is not None:
            content = content[:sample_size]
        elif len(content) > range_limit:
            # XLSX troppo grande anche dopo Range — skippa
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

        # Salva il contenuto in un file temporaneo per usare il profiler toolkit
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
            # Phase 1: sniff — encoding, delim, decimal, skip, binary detection
            # Se known_encoding è fornito (dall'inventory), salta lo sniff
            # e usa i parametri noti. Il download del sample è già stato fatto.
            if known_encoding:
                encoding_suggested = known_encoding
                delim_suggested = known_delim
                decimal_suggested = known_decimal
                skip_suggested = known_skip or 0
                is_binary = None
                # sniff_hints minimale per profile_with_read_cfg (serve true_header_line + warnings)
                sniff: dict[str, Any] = {"true_header_line": None, "warnings": []}
            else:
                sniff = sniff_source_file(tmp_path)
                encoding_suggested = sniff.get("encoding_suggested")
                delim_suggested = sniff.get("delim_suggested")
                decimal_suggested = sniff.get("decimal_suggested")
                skip_suggested = sniff.get("skip_suggested", 0)
                is_binary = sniff.get("is_binary_file")

            if fmt in ("csv", "tsv") and not is_binary:
                # CSV/TSV: profiling DuckDB con sniff (TSV forza tab dopo sniff)
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
                # JSON: colonne da primo record (toolkit non profila JSON)
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
            "resource_format": resource_kind.upper(),
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
