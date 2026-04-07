from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date
import json
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from urllib3.exceptions import InsecureRequestWarning


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = WORKSPACE_ROOT / "data" / "radar" / "sources_registry.yaml"
STATUS_PATH = WORKSPACE_ROOT / "data" / "radar" / "STATUS.md"
USER_AGENT = "Mozilla/5.0"
TIMEOUT_SECONDS = 10

# Retry/backoff per SDMX endpoints noti instabili (es. ISTAT).
# Condivisi con build_catalog_inventory.py per coerenza.
SDMX_RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
SDMX_RETRY_DELAYS_SECONDS = (2, 5)


@dataclass
class ProbeResult:
    status: str
    http_code: str
    note: str | None = None
    ssl_fallback_used: bool = False
    final_url: str | None = None
    content_type: str | None = None


def load_registry(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry YAML at {path} must contain a top-level mapping.")
    return data


def save_registry(path: Path, registry: dict[str, dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(registry, fh, sort_keys=False, allow_unicode=True)


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


def _probe_once(base_url: str) -> ProbeResult:
    """Single probe attempt (no retry)."""
    headers = {"User-Agent": USER_AGENT}
    try:
        with requests.get(
            base_url,
            timeout=TIMEOUT_SECONDS,
            headers=headers,
            allow_redirects=True,
            stream=True,
        ) as response:
            status, note = validate_ckan_action_response(base_url, response)
            return ProbeResult(
                status=status,
                http_code=str(response.status_code),
                note=note,
                final_url=str(response.url),
                content_type=response.headers.get("content-type"),
            )
    except requests.exceptions.SSLError as exc:
        try:
            with requests.Session() as session:
                requests.packages.urllib3.disable_warnings(
                    category=InsecureRequestWarning
                )
                with session.get(
                    base_url,
                    timeout=TIMEOUT_SECONDS,
                    headers=headers,
                    allow_redirects=True,
                    verify=False,
                    stream=True,
                ) as response:
                    status, probe_note = validate_ckan_action_response(
                        base_url, response
                    )
                    note = f"SSL verify failed; fallback verify=False used ({exc.__class__.__name__})"
                    if probe_note:
                        note = f"{note} | {probe_note}"
                    return ProbeResult(
                        status=status,
                        http_code=str(response.status_code),
                        note=note,
                        ssl_fallback_used=True,
                        final_url=str(response.url),
                        content_type=response.headers.get("content-type"),
                    )
        except requests.exceptions.Timeout:
            return ProbeResult(
                status="YELLOW",
                http_code="-",
                note=f"SSL verify failed; fallback timed out ({exc.__class__.__name__})",
                ssl_fallback_used=True,
            )
        except requests.exceptions.ConnectionError as fallback_exc:
            return ProbeResult(
                status="RED",
                http_code="-",
                note=f"SSL verify failed; fallback connection error ({fallback_exc.__class__.__name__})",
                ssl_fallback_used=True,
            )
        except requests.exceptions.RequestException as fallback_exc:
            return ProbeResult(
                status="RED",
                http_code="-",
                note=f"SSL verify failed; fallback request error ({fallback_exc.__class__.__name__})",
                ssl_fallback_used=True,
            )
    except requests.exceptions.Timeout as exc:
        return ProbeResult(
            status="YELLOW",
            http_code="-",
            note=f"Timeout ({exc.__class__.__name__})",
        )
    except requests.exceptions.ConnectionError as exc:
        return ProbeResult(
            status="RED",
            http_code="-",
            note=f"Connection error ({exc.__class__.__name__})",
        )
    except requests.exceptions.RequestException as exc:
        return ProbeResult(
            status="RED",
            http_code="-",
            note=f"Request error ({exc.__class__.__name__})",
        )


def probe_url(base_url: str) -> ProbeResult:
    """Probe URL with retry/backoff for SDMX endpoints known to be intermittent."""
    if not _is_sdmx_url(base_url):
        return _probe_once(base_url)

    # SDMX: retry on known intermittent status codes
    last_result = None
    for attempt, delay in enumerate([0, *SDMX_RETRY_DELAYS_SECONDS], start=1):
        if delay > 0:
            time.sleep(delay)
        result = _probe_once(base_url)
        last_result = result

        # Success or non-retryable error: stop
        if result.status == "GREEN":
            return result
        http_code = int(result.http_code) if result.http_code != "-" else 0
        if http_code not in SDMX_RETRYABLE_STATUS_CODES:
            if attempt > 1:
                note = f"Retry dopo {attempt - 1} tentativi: {result.note or 'nessun dettaglio'}"
                return ProbeResult(
                    status=result.status,
                    http_code=result.http_code,
                    note=note,
                    final_url=result.final_url,
                    content_type=result.content_type,
                )
            return result

    # All retries exhausted
    if last_result:
        note = (
            f"SDMX retry esaurito ({len(SDMX_RETRY_DELAYS_SECONDS) + 1} tentativi): "
            f"{last_result.note or 'nessun dettaglio'}"
        )
        return ProbeResult(
            status=last_result.status,
            http_code=last_result.http_code,
            note=note,
            final_url=last_result.final_url,
            content_type=last_result.content_type,
        )
    return last_result or ProbeResult(
        status="RED", http_code="-", note="SDMX probe fallito"
    )


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe radar source portals and build STATUS.md."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run probes without writing YAML or STATUS.md.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_registry(REGISTRY_PATH)
    probe_date = date.today().isoformat()

    results: dict[str, ProbeResult] = {}
    for portal, meta in registry.items():
        base_url = meta.get("base_url")
        if not base_url:
            results[portal] = ProbeResult(
                status="RED",
                http_code="-",
                note="Missing base_url in registry entry",
            )
            continue
        results[portal] = probe_url(str(base_url))

    report = build_status_report(registry, results, probe_date)

    if args.dry_run:
        print(report)
        return 0

    update_last_probed(registry, probe_date)
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(report, encoding="utf-8")
    save_registry(REGISTRY_PATH, registry)
    print(f"Wrote {STATUS_PATH}")
    print(f"Updated {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
