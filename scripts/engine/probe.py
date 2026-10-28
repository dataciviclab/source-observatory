"""Probe HTTP di una fonte — primitiva condivisa del motore.

Estrae il probe (radar + catalog) da ``scripts/radar_check.py``: il centrale
lo usa per il radar, il motore per l'``health`` del ``catalog.json``. Prima
il motore importava il modulo centrale (``scripts.radar_check``, 501 righe)
per due soli simboli.

Dipendenze: ``requests`` + ``lab_connectors``. L'unico aggancio al resto del
motore è ``scripts.collectors.sdmx.catalog_fetch_url``, importato lazy solo
per gli URL SDMX.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import requests
from lab_connectors.discovery.classify import is_sdmx_url
from lab_connectors.http import HttpClient, HttpFallbackError
from lab_connectors.http.types import ResponseLike

USER_AGENT = "DataCivicLab-SourceObservatory/1.0"
TIMEOUT_SECONDS = 10
# SDMX: i cataloghi serializzano migliaia di dataflow in una risposta unica
# (es. ISTAT ~80s anche con detail=allstubs) → timeout dedicato più alto.
SDMX_TIMEOUT_SECONDS = 180


@dataclass
class ProbeResult:
    status: str
    http_code: str
    note: str | None = None
    ssl_fallback_used: bool = False
    final_url: str | None = None
    content_type: str | None = None


def classify_response(status_code: int) -> str:
    if 200 <= status_code < 400:
        return "GREEN"
    if 400 <= status_code < 500:
        return "YELLOW"
    return "RED"


def validate_ckan_action_response(base_url: str, response: ResponseLike) -> tuple[str, str | None]:
    if "/api/3/action/" not in base_url:
        return classify_response(response.status_code), None

    status = classify_response(response.status_code)
    if status != "GREEN":
        return status, None

    content_type = (response.headers.get("content-type") or "").lower()
    if "json" not in content_type:
        return "YELLOW", "CKAN API returned non-JSON content"

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return "YELLOW", "CKAN API returned invalid JSON"
    except ValueError:
        return "YELLOW", "CKAN API returned unreadable payload"

    if not isinstance(payload, dict) or "success" not in payload:
        return "YELLOW", "CKAN API payload missing expected keys"

    return status, None


def _make_error_result(
    exc: Exception,
    *,
    ssl_fallback_used: bool = False,
    ssl_failure: requests.exceptions.SSLError | None = None,
) -> ProbeResult:
    if isinstance(exc, requests.exceptions.Timeout):
        if ssl_fallback_used:
            note = (
                f"SSL verify failed; fallback timed out ({(ssl_failure or exc).__class__.__name__})"
            )
        else:
            note = f"Timeout ({exc.__class__.__name__})"
        return ProbeResult(
            status="YELLOW",
            http_code="-",
            note=note,
            ssl_fallback_used=ssl_fallback_used,
        )

    if isinstance(exc, requests.exceptions.ConnectionError):
        detail = "connection error" if ssl_fallback_used else "Connection error"
    else:
        detail = "request error" if ssl_fallback_used else "Request error"

    if ssl_fallback_used:
        note = f"SSL verify failed; fallback {detail} ({exc.__class__.__name__})"
    else:
        note = f"{detail} ({exc.__class__.__name__})"

    return ProbeResult(
        status="RED",
        http_code="-",
        note=note,
        ssl_fallback_used=ssl_fallback_used,
    )


def _build_probe_result(
    base_url: str,
    response: ResponseLike,
    *,
    ssl_failure: requests.exceptions.SSLError | Literal[True] | None = None,
) -> ProbeResult:
    status, probe_note = validate_ckan_action_response(base_url, response)
    note = probe_note
    ssl_fallback_used = ssl_failure is not None
    if ssl_failure is not None:
        failure_type = "SSLError" if ssl_failure is True else ssl_failure.__class__.__name__
        note = f"SSL verify failed; fallback verify=False used ({failure_type})"
        if probe_note:
            note = f"{note} | {probe_note}"
    return ProbeResult(
        status=status,
        http_code=str(response.status_code),
        note=note,
        ssl_fallback_used=ssl_fallback_used,
        final_url=str(response.url),
        content_type=response.headers.get("content-type"),
    )


def _probe_once(
    base_url: str, timeout: int = TIMEOUT_SECONDS, user_agent: str | None = None
) -> ProbeResult:
    """Single probe attempt (no retry). Uses lab_connectors HttpClient with SSL fallback."""
    client = HttpClient(timeout=timeout, user_agent=user_agent or USER_AGENT)
    result = client.get(
        base_url,
        allow_redirects=True,
        stream=True,
    )
    # ssl_fallback_used=True → primary SSL failed, fallback succeeded → GREEN
    # ssl_fallback_used=False → both failed
    # ssl_fallback_used=None → primary succeeded (no fallback needed)
    if result.is_ok and result.response is not None:
        return _build_probe_result(
            base_url,
            result.response,
            ssl_failure=result.ssl_fallback_used if result.ssl_fallback_used else None,
        )
    # Both failed — result.err carries the final error
    if result.err is None:
        # response=None with no exception — should not happen, treat as hard error
        return ProbeResult(
            status="RED",
            http_code="-",
            note="Unexpected: response=None without exception from HttpClient.get",
        )
    ssl_failure_err: requests.exceptions.SSLError | None = None
    error_exc: Exception
    if isinstance(result.err, HttpFallbackError):
        ssl_failure_err = (
            result.err.primary_error
            if isinstance(result.err.primary_error, requests.exceptions.SSLError)
            else None
        )
        if isinstance(result.err.fallback_error, requests.exceptions.RequestException):
            error_exc = result.err.fallback_error
        else:
            error_exc = result.err.fallback_error
    elif isinstance(result.err, requests.exceptions.SSLError):
        ssl_failure_err = result.err
        error_exc = result.err
    elif isinstance(result.err, requests.exceptions.RequestException):
        error_exc = result.err
    else:
        # Non-RequestException escaped HttpClient.get — treat as RED
        return ProbeResult(
            status="RED",
            http_code="-",
            note=f"Unexpected exception type in _probe_once: {type(result.err).__name__}: {result.err}",
        )
    return _make_error_result(
        error_exc,
        ssl_fallback_used=ssl_failure_err is not None,
        ssl_failure=ssl_failure_err,
    )


def probe_url(base_url: str, user_agent: str | None = None) -> ProbeResult:
    """Probe URL with retry/backoff for SDMX endpoints known to be intermittent."""
    if not is_sdmx_url(base_url):
        result = _probe_once(base_url, user_agent=user_agent)
        # Retry once with shorter timeout on transient failures (timeout / connection error)
        if result.http_code == "-" and result.status == "YELLOW":
            result2 = _probe_once(base_url, user_agent=user_agent)
            # Only upgrade if second attempt succeeds — otherwise keep original note
            if result2.status == "GREEN":
                return result2
            # Annotate with retry info, but keep original status (don't compound)
            retry_note = f"Retry timeout/connection: {result2.note or result2.status}"
            return ProbeResult(
                status=result.status,
                http_code=result2.http_code,
                note=retry_note,
                ssl_fallback_used=result.ssl_fallback_used or result2.ssl_fallback_used,
                final_url=result2.final_url or result.final_url,
                content_type=result2.content_type or result.content_type,
            )
        return result

    # SDMX: catalogo lento (ISTAT ~80s anche con detail=allstubs).
    # Timeout dedicato + payload ridotto per evitare ReadTimeout su cataloghi
    # che serializzano migliaia di dataflow in una risposta unica.
    from scripts.collectors.sdmx import catalog_fetch_url

    sdmx_fetch_url = catalog_fetch_url(base_url)
    return _probe_once(sdmx_fetch_url, timeout=SDMX_TIMEOUT_SECONDS, user_agent=user_agent)
