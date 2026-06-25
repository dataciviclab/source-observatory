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
import xml.etree.ElementTree as ET
from typing import Any, Optional

from lab_connectors.http import CircuitOpenError, HttpClient

# backward compat per test SO: importa funzioni pubbliche di toolkit
from toolkit.profile.preview import (  # noqa: F401
    extract_year_values_from_sample as _extract_year_values_from_sample,
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
from toolkit.scout.infer import infer_granularity as _infer_granularity
from toolkit.scout.sparql import (
    fetch_sparql_count as _toolkit_sparql_count,
)


def _infer_granularity_from_columns(columns: list[str]) -> str:
    """Backward compat: pure function, inferisce da nomi colonna."""
    combined = " ".join(c.lower().replace("_", " ") for c in columns) if columns else ""
    return _infer_granularity(combined)


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
    "paqa_score": None,
    "paqa_verdict": None,
    "paqa_flags": None,
    "paqa_ontologies": None,
    "paqa_sampled": None,  # bool: True = campione, False/None = file completo
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
    """HEAD probe via toolkit, con backward compat per caller SO.

    Delega a ``toolkit.scout.http.probe_url_headers`` che fa:
      HEAD → retry → GET+Range fallback → HTTPS fallback

    Returns: (status_code, reachable, error, content_type_format).
    """
    from toolkit.scout.http import probe_url_headers as _toolkit_probe

    if not isinstance(url, str) or not url.startswith("http"):
        return None, False, "url_missing_or_invalid", None

    try:
        # Circuit breaker check solo per URL gia' HTTPS.
        # Per HTTP, il toolkit ha _try_https() che usa client
        # separato (circuit_threshold=0). Se blocchiamo qui,
        # l'HTTPS fallback non parte mai.
        if (
            client is not None
            and not url.startswith("http://")
            and client._circuit_should_block(url)
        ):
            return None, False, "circuit_open", None
        result = _toolkit_probe(url, client=client)
        status: int = result["status_code"]
        ct: str | None = result.get("content_type")
        cd: str | None = result.get("content_disposition")
        fmt = _toolkit_preview_kind(url, ct, cd)
        reachable = status < 400
        return status, reachable, "", fmt
    except CircuitOpenError:
        return None, False, "circuit_open", None
    except RuntimeError as exc:
        err_msg = str(exc) or "probe_failed"
        return None, False, err_msg, None


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

    if p.status != "success":
        result = _EMPTY_ENRICH.copy()
        result["enrich_method"] = p.status
        return result

    result = _EMPTY_ENRICH.copy()
    result.update(
        {
            "columns": _json.dumps(p.columns) if p.columns else None,
            "col_types": _json.dumps(p.col_types) if p.col_types else None,
            "file_size": p.file_size,
            "preview_row_count": p.preview_row_count,
            "year_min": p.year_min,
            "year_max": p.year_max,
            "granularity": p.granularity,
            "resource_format": p.resource_format or "",
            "enrich_method": "csv_preview",
            "encoding_suggested": p.encoding_suggested,
            "delim_suggested": p.delim_suggested,
            "decimal_suggested": p.decimal_suggested,
            "skip_suggested": p.skip_suggested,
            "robust_read_suggested": p.robust_read_suggested,
            "mapping_suggestions": _json.dumps(p.mapping_suggestions)
            if isinstance(p.mapping_suggestions, dict)
            else "{}",
            "paqa_score": p.quality_score,
            "paqa_verdict": p.quality_verdict,
            "paqa_flags": _json.dumps(p.quality_flags) if p.quality_flags else None,
            "paqa_ontologies": _json.dumps(p.quality_ontologies) if p.quality_ontologies else None,
            "paqa_sampled": p.quality_sampled,  # bool: True se campione
        }
    )
    return result
