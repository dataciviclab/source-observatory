"""
Fetch fase per bulk source-check.

Strati:
  lab_connectors.http  → HttpClient con circuit breaker opzionale
  toolkit.scout.http   → funzioni HTTP/fetch condivise (probe, format, CKAN, SDMX, HTML)
  Questo modulo         → orchestrazione specifica SO
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

from lab_connectors.http import CircuitOpenError, HttpClient
from toolkit.profile.preview import (  # noqa: F401 — backward compat per test SO
    _extract_year_values_from_sample,
)
from toolkit.profile.preview import (
    _infer_granularity_from_columns as _tk_infer_gran,
)
from toolkit.scout.http import (
    fetch_html_body as _toolkit_html_body,
)
from toolkit.scout.http import (
    fetch_sdmx_years as _toolkit_sdmx_years,
)
from toolkit.scout.http import (
    resolve_preview_kind as _toolkit_preview_kind,
)
from toolkit.scout.sparql import (
    fetch_sparql_count as _toolkit_sparql_count,
)


def _infer_granularity_from_columns(columns: list[str]) -> str:
    """Backward compat: pure function wrapper su toolkit."""
    result: dict[str, str] = {}
    _tk_infer_gran(columns, result)
    return result.get("granularity", "non_determinato")


logger = logging.getLogger(__name__)

# ── Config HTTP (sovrascrivibile da configure_source_check_http) ──────────────

_DEFAULT_HTTP_TIMEOUT: tuple[int, int] = (5, 10)
_DEFAULT_HTTP_RETRIES = 2
_DEFAULT_CIRCUIT_THRESHOLD = 3

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
    "sparql_responding": None,
    "sparql_triple_count": None,
}


# ── Client HTTP condiviso ──────────────────────────────────────────────────────


def configure_source_check_http(
    *,
    circuit_fail_threshold: int = _DEFAULT_CIRCUIT_THRESHOLD,
    http_timeout: tuple[int, int] | None = None,
    http_max_retries: int = _DEFAULT_HTTP_RETRIES,
) -> HttpClient:
    """Crea un HttpClient configurato per bulk source-check.

    Il client include circuit breaker per-host: dopo ``circuit_fail_threshold``
    errori consecutivi sullo stesso host, le richieste successive restituiscono
    ``CircuitOpenError`` senza fare rete.
    """
    return HttpClient(
        timeout=http_timeout or _DEFAULT_HTTP_TIMEOUT,
        max_retries=max(1, int(http_max_retries)),
        circuit_threshold=max(0, int(circuit_fail_threshold)),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NOTA: Il circuit breaker e' ora gestito direttamente da ``HttpClient``
# (parametro ``circuit_threshold`` in ``configure_source_check_http``).
# Le vecchie funzioni ``_netloc``, ``_circuit_should_block``,
# ``_circuit_after_result``, ``_tracked_http_head`` e ``_tracked_http_get``
# sono state rimosse — usare ``client.head()`` / ``client.get()`` direttamente.
# ═══════════════════════════════════════════════════════════════════════════════


# ── Probe principale (usato da bulk_source_check) ────────────────────────────


def _http_head_with_retry(
    url: str,
    client: HttpClient | None = None,
    max_retries: int = 1,
) -> tuple[Optional[int], bool, str, Optional[str]]:
    """HTTP HEAD con retry e circuit breaker via HttpClient.

    Usa ``client.head(url)`` che internamente gestisce circuit breaker,
    retry su 5xx e connection error.  La format detection usa
    ``toolkit.scout.http.resolve_preview_kind``.

    Se *client* non e' fornito, ne crea uno di default (senza circuit breaker).

    Returns: (status_code, reachable, error, content_type_format).
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid", None

    if client is None:
        client = HttpClient(timeout=(5, 10))

    last_error = ""

    for attempt in range(max_retries + 1):
        result = client.head(url)
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
            if isinstance(result.err, CircuitOpenError):
                return None, False, "circuit_open", None
            err_name = type(result.err).__name__
            if "Timeout" in err_name and attempt < max_retries:
                last_error = "timeout"
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, False, err_name.lower(), None

        return None, False, last_error or "transient_error", None

    return None, False, last_error or "transient_error", None


# ── CKAN fetch (wrapper: adatta base_api SO a portal_url toolkit) ─────────────


# ── SDMX years ───────────────────────────────────────────────────────────────


def _fetch_sdmx_years(
    base_url: str,
    flow_id: str,
    client: HttpClient | None = None,
    *,
    allow_fetch: bool = True,
) -> tuple[Optional[int], Optional[int]]:
    """SDMX years via toolkit.scout con allow_fetch SO."""
    if not allow_fetch:
        return None, None
    try:
        return _toolkit_sdmx_years(base_url, flow_id, client=client)
    except Exception:
        return None, None


# ── SDMX dataflow annotations ────────────────────────────────────────────────


def _fetch_sdmx_dataflow(
    base_url: str, flow_id: str, client: HttpClient | None = None
) -> Optional[ET.Element]:
    """Fetch SDMX dataflow definition XML (annotations con keywords). SO-specific URL construction."""
    if client is None:
        client = HttpClient(timeout=_DEFAULT_HTTP_TIMEOUT)
    base = base_url.split("?")[0].rstrip("/")
    if base.endswith("/IT1"):
        root_url = base
    else:
        root_url = base.rsplit("/", 1)[0]
    url = f"{root_url}/{flow_id}"
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


# ── SPARQL probe ─────────────────────────────────────────────────────────────


def _fetch_sparql_count(
    endpoint: str,
    graph_uri: str | None = None,
    timeout: int = 15,
) -> int | None:
    """Conta triple su un endpoint SPARQL, con/senza named graph.

    Wrapper bulk-safe su toolkit.scout.sparql.fetch_sparql_count.
    Gestisce timeout e fallimenti senza sollevare eccezioni.
    """
    return _toolkit_sparql_count(
        endpoint=endpoint,
        graph_uri=graph_uri,
        timeout=timeout,
    )


# ── HTML metadata (format detection) ─────────────────────────────────────────


def _fetch_html_metadata(url: str, client: HttpClient | None = None) -> dict:
    """Scarica HTML e cerca formato dati. Usa toolkit.scout.fetch_html_body."""
    if not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "html_scrape_invalid_url"
        return result
    try:
        body = _toolkit_html_body(url, client=client)
        if not body or not body.get("html_text"):
            err = _EMPTY_ENRICH.copy()
            err["enrich_method"] = "html_scrape_fetch_failed"
            return err
        html = body["html_text"]
        resource_format: Optional[str] = None
        patterns = [
            (r"\.(csv|xlsx?|json|xml|zip|parquet)\b", 1),
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


# ── Data preview (toolkit profiler + SO enrichment) ──────────────────────────


# _YEAR_COLUMN_HINTS, REGION_COLUMNS, COMUNE_COLUMNS spostati in toolkit.profile.preview


# ── Orchestrator ────────────────────────────────────────────────────────────


def _fetch_data_preview(
    url: str,
    client: HttpClient | None = None,
    *,
    known_encoding: str | None = None,
    known_delim: str | None = None,
    known_decimal: str | None = None,
    known_skip: int | None = None,
) -> dict:
    """Fetch e parse content preview usando toolkit preview_url.

    Delega a ``toolkit.profile.preview.preview_url`` che fa HEAD → Range GET
    → sniff → DuckDB profile → infer in un colpo solo.
    """
    import json as _json

    if not isinstance(url, str) or not url.startswith("http"):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = "csv_preview_failed"
        return result

    from toolkit.profile.preview import preview_url

    p = preview_url(
        url,
        client=client,
        known_encoding=known_encoding,
        known_delim=known_delim,
        known_decimal=known_decimal,
        known_skip=known_skip,
    )

    if not p.get("reachable") or p.get("enrich_method") in (
        "probe_failed",
        "unsupported_format",
        "download_failed",
        "json_decode_failed",
    ):
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = p.get("enrich_method", "csv_preview_failed")
        return result

    result = _EMPTY_ENRICH.copy()
    result.update(
        {
            "columns": _json.dumps(p.get("columns")) if p.get("columns") else None,
            "col_types": _json.dumps(p.get("col_types")) if p.get("col_types") else None,
            "file_size": p.get("file_size"),
            "preview_row_count": p.get("preview_row_count"),
            "year_min": p.get("year_min"),
            "year_max": p.get("year_max"),
            "granularity": p.get("granularity", "non_determinato"),
            "resource_format": p.get("resource_format", ""),
            "enrich_method": "csv_preview",
            "encoding_suggested": p.get("encoding_suggested"),
            "delim_suggested": p.get("delim_suggested"),
            "decimal_suggested": p.get("decimal_suggested"),
            "skip_suggested": p.get("skip_suggested", 0),
            "robust_read_suggested": p.get("robust_read_suggested", False),
            "mapping_suggestions": _json.dumps(p.get("mapping_suggestions"))
            if isinstance(p.get("mapping_suggestions"), dict)
            else "{}",
        }
    )
    return result
