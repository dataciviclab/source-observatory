#!/usr/bin/env python3
"""
Genera catalog_signals.json da catalog_inventory_report.json.

Confronta con il report precedente (se disponibile) per rilevare
regressioni, recovery e variazioni di inventory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_report.json"
DEFAULT_OUT = REPO_ROOT / "data" / "catalog" / "catalog_signals.json"


def _classify(
    source_id: str,
    info: dict,
    prev_info: dict | None,
) -> dict:
    status = info.get("status")
    protocol = info.get("protocol", "n/d")

    # Non inventariabile: includi solo se era ok prima (regressione strutturale)
    if status in ("non_inventariabile", "protocol_not_supported"):
        prev_status = prev_info.get("status") if prev_info else None
        if prev_status == "ok":
            return {
                "source": source_id,
                "protocol": protocol,
                "signal_type": "structural drift",
                "result": "regressione",
                "metric_value": None,
                "detail": info.get("reason", "Fonte non più inventariabile."),
                "suggested_action": "verificare causa — fonte precedentemente ok",
            }
        return {
            "source": source_id,
            "protocol": protocol,
            "signal_type": "no signal",
            "result": "stabile",
            "metric_value": None,
            "detail": info.get("reason", "Fonte non inventariabile."),
            "suggested_action": "nessuna",
        }

    # Errore
    if status == "error":
        error_msg = info.get("error", "errore sconosciuto")
        prev_status = prev_info.get("status") if prev_info else None
        if prev_status == "error":
            prev_error = prev_info.get("error", "")
            changed = prev_error != error_msg
            detail = f"Errore persistente: {error_msg}"
            if changed:
                detail += " (messaggio cambiato rispetto al run precedente)"
            return {
                "source": source_id,
                "protocol": protocol,
                "signal_type": "health",
                "result": "regressione",
                "metric_value": None,
                "detail": detail,
                "suggested_action": "valutare declassamento a radar-only se persiste",
            }
        # Nuova regressione
        return {
            "source": source_id,
            "protocol": protocol,
            "signal_type": "health",
            "result": "regressione",
            "metric_value": None,
            "detail": f"Errore: {error_msg}",
            "suggested_action": "monitorare nei prossimi run",
        }

    # Ok
    if status == "ok":
        rows = info.get("rows", 0)
        method = info.get("method", "n/d")
        prev_status = prev_info.get("status") if prev_info else None

        # Recovery
        if prev_status == "error":
            return {
                "source": source_id,
                "protocol": protocol,
                "signal_type": "health",
                "result": "recovery",
                "metric_value": rows,
                "detail": f"Tornato ok. {rows} item ({method}).",
                "suggested_action": "nessuna",
            }

        # Inventory change
        if prev_info and prev_info.get("status") == "ok":
            prev_rows = prev_info.get("rows", 0)
            if rows != prev_rows:
                delta = rows - prev_rows
                delta_str = f"+{delta}" if delta > 0 else str(delta)
                return {
                    "source": source_id,
                    "protocol": protocol,
                    "signal_type": "inventory change",
                    "result": "inventory change",
                    "metric_value": rows,
                    "detail": f"{rows} item ({method}), delta {delta_str} rispetto al run precedente ({prev_rows}).",
                    "suggested_action": "verificare se variazione attesa; avviare catalog-inventory-scout se nuovi dataset",
                }

        # Stabile
        return {
            "source": source_id,
            "protocol": protocol,
            "signal_type": "no signal",
            "result": "stabile",
            "metric_value": rows,
            "detail": f"{rows} item ({method}), in linea con la baseline.",
            "suggested_action": "nessuna",
        }

    # Fallback
    return {
        "source": source_id,
        "protocol": protocol,
        "signal_type": "no signal",
        "result": "stabile",
        "metric_value": None,
        "detail": f"Status non gestito: {status}",
        "suggested_action": "nessuna",
    }


def build_signals(report: dict, prev_report: dict | None) -> dict:
    sources = report.get("sources", {})
    prev_sources = (prev_report or {}).get("sources", {})

    signals = []
    for source_id, info in sources.items():
        prev_info = prev_sources.get(source_id)
        signals.append(_classify(source_id, info, prev_info))

    # Rimuovi metric_value None per pulizia (campi opzionali)
    for s in signals:
        if s.get("metric_value") is None:
            del s["metric_value"]

    return {
        "captured_at": report.get("captured_at", ""),
        "sources_checked": len(sources),
        "signals": signals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera catalog_signals.json da catalog_inventory_report.json."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Path al report inventory attuale.",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        default=None,
        help="Path al report inventory precedente (opzionale, per rilevare regressioni).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Path di output per catalog_signals.json.",
    )
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    prev_report = None
    if args.previous and args.previous.exists():
        prev_report = json.loads(args.previous.read_text(encoding="utf-8"))
        if not prev_report.get("sources"):
            prev_report = None  # primo run

    signals = build_signals(report, prev_report)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(signals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(signals['signals'])} signals to {args.out}")


if __name__ == "__main__":
    main()
