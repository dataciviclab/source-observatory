from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal

import jsonschema
import requests
from _constants import (
    RADAR_HISTORY_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    SCHEMA_DIR_PATH,
    STATUS_MD_PATH,
    append_radar_probe,
    load_radar_history,
    load_registry,
    save_radar_history,
    save_registry,
)
from lab_connectors.http import HttpClient, HttpFallbackError


def _validate_schema(instance: dict, schema_name: str) -> None:
    """Validate a dict against the JSON schema file in schemas/."""
    schema_path = SCHEMA_DIR_PATH / schema_name
    if not schema_path.exists():
        print(f"⚠️  Schema {schema_name} non trovato — skip validazione")
        return
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        print(f"❌ Validazione fallita ({schema_name}): {exc.message}")
        raise


USER_AGENT = "DataCivicLab-SourceObservatory/1.0"
TIMEOUT_SECONDS = 10


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


def validate_ckan_action_response(
    base_url: str, response: requests.Response
) -> tuple[str, str | None]:
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


def _is_sdmx_url(url: str) -> bool:
    """Detect SDMX endpoint by URL pattern."""
    sdmx_markers = ("/rest/", "/SDMXWS/", "/sdmx/")
    return any(marker in url for marker in sdmx_markers)


def _make_error_result(
    exc: requests.exceptions.RequestException,
    *,
    ssl_fallback_used: bool = False,
    ssl_failure: requests.exceptions.SSLError | None = None,
) -> ProbeResult:
    if isinstance(exc, requests.exceptions.Timeout):
        if ssl_fallback_used:
            note = f"SSL verify failed; fallback timed out ({(ssl_failure or exc).__class__.__name__})"
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
    response: requests.Response,
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


def _probe_once(base_url: str) -> ProbeResult:
    """Single probe attempt (no retry). Uses lab_connectors HttpClient with SSL fallback."""
    client = HttpClient(timeout=TIMEOUT_SECONDS, user_agent=USER_AGENT)
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
    error_exc: requests.exceptions.RequestException
    if isinstance(result.err, HttpFallbackError):
        ssl_failure_err = result.err.primary_error
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


def probe_url(base_url: str) -> ProbeResult:
    """Probe URL with retry/backoff for SDMX endpoints known to be intermittent."""
    if not _is_sdmx_url(base_url):
        result = _probe_once(base_url)
        # Retry once with shorter timeout on transient failures (timeout / connection error)
        if result.http_code == "-" and result.status == "YELLOW":
            result2 = _probe_once(base_url)
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

    # SDMX: HttpClient handles retry with backoff internally
    return _probe_once(base_url)


def build_status_report(
    registry: dict[str, dict[str, Any]],
    results: dict[str, ProbeResult],
    probe_date: str,
) -> str:
    status_counts = Counter(result.status for result in results.values())
    mode_counts = Counter(
        (meta.get("observation_mode") or "radar-only") for meta in registry.values()
    )
    kind_counts = Counter(
        (meta.get("source_kind") or "source") for meta in registry.values()
    )

    lines: list[str] = [
        "# Stato Radar",
        "",
        f"Ultimo run: {probe_date}",
        "",
        "## Sommario",
        "",
        f"- Fonti controllate: {len(registry)}",
        f"- GREEN: {status_counts.get('GREEN', 0)}",
        f"- YELLOW: {status_counts.get('YELLOW', 0)}",
        f"- RED: {status_counts.get('RED', 0)}",
        "",
        "## Tipi sorgente",
        "",
        "| Tipo | Conteggio |",
        "| --- | --- |",
        f"| catalog | {kind_counts.get('catalog', 0)} |",
        f"| portal | {kind_counts.get('portal', 0)} |",
        f"| source | {kind_counts.get('source', 0)} |",
        "",
        "## Modalita' osservazione",
        "",
        "| Modalita' | Conteggio | Significato |",
        "| --- | --- | --- |",
        f"| radar-only | {mode_counts.get('radar-only', 0)} | Salute della fonte senza segnali di inventario |",
        f"| catalog-watch | {mode_counts.get('catalog-watch', 0)} | Inventario e drift strutturale del catalogo |",
        f"| monitor-active | {mode_counts.get('monitor-active', 0)} | Caso ristretto con monitoraggio piu' vicino alla risorsa |",
        "",
        "Nota: lo stato radar descrive la salute della fonte, non il valore o l'aggiornamento del dataset.",
        "",
        "## Stato per fonte",
        "",
        "| Fonte | Tipo | Protocollo | Modalita' | Stato | HTTP code | Datasets collegati |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    notes: list[str] = []

    def format_probe_details(
        result: ProbeResult, fallback_note: str | None = None
    ) -> str:
        details: list[str] = []
        if result.http_code != "-":
            details.append(f"HTTP {result.http_code}")
        if result.content_type:
            details.append(f"content-type: {result.content_type}")
        if result.final_url:
            details.append(f"url finale: {result.final_url}")
        if result.note:
            details.append(result.note)
        elif fallback_note:
            details.append(fallback_note)
        return " | ".join(details) if details else "Nessuna nota"

    for portal, meta in registry.items():
        result = results[portal]
        datasets = meta.get("datasets_in_use") or []
        datasets_str = ", ".join(datasets) if datasets else "-"
        source_kind = meta.get("source_kind", "source")
        protocol = meta.get("protocol", "-")
        mode = meta.get("observation_mode", "radar-only")
        lines.append(
            f"| {portal} | {source_kind} | {protocol} | {mode} | {result.status} | {result.http_code} | {datasets_str} |"
        )
        if result.status in {"YELLOW", "RED"}:
            details = format_probe_details(result, meta.get("note"))
            notes.append(f"- `{portal}`: {details}")
        elif result.ssl_fallback_used:
            details = format_probe_details(result, meta.get("note"))
            notes.append(f"- `{portal}`: {details}")

    lines.extend(["", "## Note", ""])
    if notes:
        lines.extend(notes)
    else:
        lines.append("- Nessuna anomalia rilevata.")
    lines.append("")
    return "\n".join(lines)


def update_last_probed(registry: dict[str, dict[str, Any]], probe_date: str) -> None:
    for meta in registry.values():
        meta["last_probed"] = probe_date


def build_radar_summary(
    registry: dict[str, dict[str, Any]],
    results: dict[str, ProbeResult],
    probe_date: str,
    history: dict | None = None,
) -> tuple[dict[str, Any], list[dict]]:
    """Build compact radar summary JSON and sources list for history.

    If history is provided, computes RED/YELLOW streak from previous probes.
    Returns (summary_dict, sources_list) where sources_list is suitable for
    append_radar_probe.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    _missing = ProbeResult(status="RED", http_code="-", note="probe result missing")
    status_counts = Counter(result.status for result in results.values())
    sources_list = []
    persistent_red = 0

    probes = (history or {}).get("probes", [])
    # Reverse: index 0 = most recent (newest), so we traverse newest→oldest.
    # Streak increments while consecutive RED; breaks on first non-RED.
    recent_probes = list(reversed(probes)) if probes else []

    for source_id, meta in registry.items():
        result = results.get(source_id) or _missing

        # Compute RED streak
        streak = 0
        current_is_red = result.status == "RED"
        for probe in recent_probes:
            src = next((s for s in probe.get("sources", []) if s["id"] == source_id), None)
            if src and src.get("status") == "RED":
                streak += 1
            else:
                break

        # Only count as persistent if current status is RED and streak >= 2
        if current_is_red and streak >= 2:
            persistent_red += 1

        entry = {
            "id": source_id,
            "status": result.status,
            "protocol": meta.get("protocol", "-"),
            "http_code": result.http_code,
            "note": result.note,
        }
        if streak >= 2:
            entry["red_streak"] = streak
        sources_list.append(entry)

    summary = {
        "generated_at": generated_at,
        "probe_date": probe_date,
        "sources_total": len(registry),
        "status_counts": {
            "GREEN": status_counts.get("GREEN", 0),
            "YELLOW": status_counts.get("YELLOW", 0),
            "RED": status_counts.get("RED", 0),
        },
        "persistent_red": persistent_red,
        "sources": sources_list,
    }
    return summary, sources_list


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe radar source portals and build STATUS.md."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run probes without writing YAML or STATUS.md.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel probe workers (default: 4).",
    )
    return parser.parse_args()


def _probe_one(
    portal: str, base_url: str | None
) -> tuple[str, ProbeResult]:
    """Worker for ThreadPoolExecutor — probes a single portal."""
    if not base_url:
        return portal, ProbeResult(
            status="RED",
            http_code="-",
            note="Missing base_url in registry entry",
        )
    try:
        result = probe_url(base_url)
    except Exception as exc:
        result = ProbeResult(
            status="RED",
            http_code="-",
            note=f"Probe exception non gestita: {exc.__class__.__name__}: {exc}",
        )
    return portal, result


def main() -> int:
    args = parse_args()
    registry = load_registry(REGISTRY_PATH)
    probe_date = date.today().isoformat()

    # Parallel probe — each portal is an independent HTTP call
    results: dict[str, ProbeResult] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_probe_one, portal, meta.get("base_url")): portal
            for portal, meta in registry.items()
        }
        for future in as_completed(futures):
            portal, result = future.result()
            results[portal] = result

    report = build_status_report(registry, results, probe_date)

    if args.dry_run:
        print(report)
        # Build summary without history for dry-run output
        summary, _ = build_radar_summary(registry, results, probe_date)
        print("\n--- SUMMARY JSON ---")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    update_last_probed(registry, probe_date)

    # Load history and append probe
    history = load_radar_history()
    # Build sources_list with streak data from history
    _, sources_list = build_radar_summary(registry, results, probe_date, history)
    history = append_radar_probe(history, probe_date, sources_list)

    # Rebuild summary with updated history for final output
    summary, _ = build_radar_summary(registry, results, probe_date, history)

    _validate_schema(summary, "radar_summary.schema.json")

    STATUS_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_MD_PATH.write_text(report, encoding="utf-8")
    RADAR_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RADAR_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    save_radar_history(history)
    save_registry(REGISTRY_PATH, registry)
    print(f"Wrote {STATUS_MD_PATH}")
    print(f"Wrote {RADAR_SUMMARY_PATH}")
    if summary.get("persistent_red"):
        print(f"⚠️  Persistent RED: {summary['persistent_red']} fonti ({', '.join(s['id'] for s in summary['sources'] if s.get('red_streak'))})")
    print(f"Wrote {RADAR_HISTORY_PATH} ({len(history['probes'])} probes)")
    print(f"Updated {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
