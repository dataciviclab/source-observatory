from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from typing import Any

from scripts._constants import (
    RADAR_HISTORY_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    STATUS_MD_PATH,
    append_radar_probe,
    load_radar_history,
    load_registry,
    save_radar_history,
    save_registry,
    validate_schema,
)
from scripts.engine.probe import ProbeResult, probe_url


def build_status_report(
    registry: dict[str, dict[str, Any]],
    results: dict[str, ProbeResult],
    probe_date: str,
) -> str:
    status_counts = Counter(result.status for result in results.values())
    mode_counts = Counter(
        (meta.get("observation_mode") or "radar-only") for meta in registry.values()
    )
    kind_counts = Counter((meta.get("source_kind") or "source") for meta in registry.values())

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

    def format_probe_details(result: ProbeResult, fallback_note: str | None = None) -> str:
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
        ssl_fallback_used = result.ssl_fallback_used

        # Compute RED streak
        streak = 0
        current_is_red = result.status == "RED"
        for probe in recent_probes:
            src = next((s for s in probe.get("sources", []) if s["id"] == source_id), None)
            if src and src.get("status") == "RED":
                streak += 1
            else:
                break

        # Compute SSL streak (consecutive probes with SSL issue).
        # Come per red_streak: conta dalla history, che include il probe
        # corrente solo nella seconda build (dopo append_radar_probe).
        # Lo stato corrente è catturato da ssl_issue.
        ssl_streak = 0
        for probe in recent_probes:
            src = next((s for s in probe.get("sources", []) if s["id"] == source_id), None)
            if src and src.get("ssl_fallback_used"):
                ssl_streak += 1
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
            "ssl_fallback_used": ssl_fallback_used,
        }
        if streak >= 2:
            entry["red_streak"] = streak
        if ssl_fallback_used:
            entry["ssl_issue"] = True
        if ssl_streak >= 2:
            entry["ssl_streak"] = ssl_streak
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
    parser = argparse.ArgumentParser(description="Probe radar source portals and build STATUS.md.")
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


def _probe_one(portal: str, base_url: str | None) -> tuple[str, ProbeResult]:
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

    validate_schema(summary, "radar_summary.schema.json")

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
        print(
            f"⚠️  Persistent RED: {summary['persistent_red']} fonti ({', '.join(s['id'] for s in summary['sources'] if s.get('red_streak'))})"
        )
    print(f"Wrote {RADAR_HISTORY_PATH} ({len(history['probes'])} probes)")
    print(f"Updated {REGISTRY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
