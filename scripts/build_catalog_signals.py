#!/usr/bin/env python3
"""
Genera catalog_signals.json e CATALOG_WATCH_REPORT.md da catalog_inventory_report.json.

Confronta con il report precedente (se disponibile) per rilevare
solo drift e inventory: la salute pura della connessione è delegata a radar_summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_report.json"
DEFAULT_OUT = REPO_ROOT / "data" / "catalog" / "catalog_signals.json"
DEFAULT_REPORT_OUT = REPO_ROOT / "data" / "catalog" / "CATALOG_WATCH_REPORT.md"


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

    # Errori/recovery di connettività sono coperti da radar_summary.
    # Il catalog_signals mantiene solo segnali inventariali e strutturali.
    if status == "error":
        return {
            "source": source_id,
            "protocol": protocol,
            "signal_type": "no signal",
            "result": "skipped",
            "metric_value": None,
            "detail": (
                "Connessione/endpoint coperti da radar_summary; "
                "nessun segnale inventariale affidabile in questo run."
            ),
            "suggested_action": "nessuna",
        }

    # Ok
    if status == "ok":
        rows = info.get("rows", 0)
        method = info.get("method", "n/d")
        prev_status = prev_info.get("status") if prev_info else None

        # Recovery di connettività ignorata: il radar la presidia.
        if prev_status == "error":
            return {
                "source": source_id,
                "protocol": protocol,
                "signal_type": "no signal",
                "result": "stabile",
                "metric_value": rows,
                "detail": f"{rows} item ({method}), connettività presidiata da radar_summary.",
                "suggested_action": "nessuna",
            }

        # Inventory change — solo se il metodo di conteggio coincide (policy comparabilità)
        if prev_info and prev_info.get("status") == "ok":
            prev_rows = prev_info.get("rows", 0)
            prev_method = prev_info.get("method")
            if prev_method and prev_method != method:
                return {
                    "source": source_id,
                    "protocol": protocol,
                    "signal_type": "missing_data",
                    "result": "missing_data",
                    "metric_value": rows,
                    "detail": (
                        f"Metodo cambiato: precedente '{prev_method}', attuale '{method}'. "
                        "Delta non confrontabile con la baseline."
                    ),
                    "suggested_action": "verificare causa cambio metodo; non usare delta come segnale",
                }
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

    # Fallback: nessun segnale inventariale utile.
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


_SIGNAL_EMOJI = {
    "inventory change": "📦",
    "structural drift": "⚠️",
    "missing_data": "❓",
    "follow-up candidate": "🔍",
    "no signal": "✅",
}


def build_watch_report(signals: dict) -> str:
    captured_at = signals.get("captured_at", "n/d")
    sources_checked = signals.get("sources_checked", 0)
    signal_list = signals.get("signals", [])

    actionable = [s for s in signal_list if s.get("signal_type") not in ("no signal", "")]
    stable = [s for s in signal_list if s.get("signal_type") in ("no signal", "")]

    lines = [
        "# Catalog Watch Report",
        "",
        f"_Generato: {captured_at} — {sources_checked} fonti controllate_",
        "",
    ]

    if actionable:
        lines += ["## Segnali attivi", ""]
        for s in actionable:
            emoji = _SIGNAL_EMOJI.get(s.get("signal_type", ""), "•")
            lines.append(f"### {emoji} `{s['source']}` — {s.get('signal_type', 'n/d')}")
            lines.append("")
            lines.append(f"- **Protocollo**: {s.get('protocol', 'n/d')}")
            lines.append(f"- **Dettaglio**: {s.get('detail', '')}")
            if s.get("metric_value") is not None:
                lines.append(f"- **Item**: {s['metric_value']}")
            action = s.get("suggested_action", "nessuna")
            if action and action != "nessuna":
                lines.append(f"- **Azione**: {action}")
            lines.append("")
    else:
        lines += ["## Segnali attivi", "", "_Nessun segnale di drift o inventory change._", ""]

    lines += [
        "## Fonti stabili / skipped",
        "",
        f"_{len(stable)} fonti senza segnali inventariali in questo run._",
        "",
        "Per problemi di connettività o HTTP vedere `data/radar/radar_summary.json`.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera catalog_signals.json e CATALOG_WATCH_REPORT.md da catalog_inventory_report.json (drift/inventory only)."
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
    parser.add_argument(
        "--report-out",
        type=Path,
        default=DEFAULT_REPORT_OUT,
        help="Path di output per CATALOG_WATCH_REPORT.md.",
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

    watch_report = build_watch_report(signals)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(watch_report, encoding="utf-8")
    print(f"Wrote watch report to {args.report_out}")


if __name__ == "__main__":
    main()
