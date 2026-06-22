#!/usr/bin/env python3
"""
Produce open_data_health_scores.json per ogni fonte monitorata.

Punteggio su 6 assi (0-100) basato su dati gia' disponibili in SO.
Artifact bridge verso data-advocacy: ogni asse indica se il dato e'
"computed" (da dati reali), "estimated" (default in assenza di info certa)
o "missing" (dato non disponibile, escluso dal punteggio).

Avvertenza: i punteggi sono diagnostici, non certificativi. Un punteggio
basso significa "abbiamo pochi dati o segnali di criticita'", non
necessariamente "violazione normativa". Le azioni raccomandate richiedono
verifica umana prima di essere intraprese.

Utilizzo:
    python scripts/build_compliance_scores.py
    python scripts/build_compliance_scores.py --out data/health/open_data_health_scores.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _constants import (
    CATALOG_SIGNALS_PATH,
    OPEN_DATA_HEALTH_SCORES_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    load_registry,
)

DEFAULT_RADAR = RADAR_SUMMARY_PATH
DEFAULT_SIGNALS = CATALOG_SIGNALS_PATH
DEFAULT_REGISTRY = REGISTRY_PATH
DEFAULT_OUT = OPEN_DATA_HEALTH_SCORES_PATH

# Pesi per ogni asse
PESI: dict[str, int] = {
    "formato_aperto": 3,
    "raggiungibilita": 2,
    "licenza_aperta": 1,
    "presenza_datigovit": 2,
    "hvd_compliance": 3,
    "accessibilita_foia": 1,
}

ASSI = {
    "formato_aperto": {"label": "A — Formato aperto", "max": 100},
    "raggiungibilita": {"label": "B — Raggiungibilita'", "max": 100},
    "licenza_aperta": {"label": "C — Licenza aperta", "max": 100},
    "presenza_datigovit": {"label": "D — Presenza dati.gov.it", "max": 100},
    "hvd_compliance": {"label": "E — HVD compliance", "max": 100},
    "accessibilita_foia": {"label": "F — Accessibilita' FOIA", "max": 100},
}


def _formato_score(protocol: str, signals: list[dict]) -> tuple[float, str]:
    """A — Formato aperto. Computed da protocol + segnali."""
    for sig in signals:
        detail = sig.get("detail", "")
        if "CSV" in detail and ("JSON" in detail or "XML" in detail):
            return (80.0, "computed")
        if "CSV" in detail:
            return (75.0, "computed")

    protocol_scores = {
        "ckan": 75.0,
        "sdmx": 70.0,
        "sparql": 65.0,
        "aem": 55.0,
        "rest": 55.0,
        "html": 50.0,
    }
    score = protocol_scores.get(protocol, 50.0)
    source_type = "computed" if protocol in protocol_scores else "estimated"
    return (score, source_type)


def _raggiungibilita_score(
    radar_entry: dict | None,
) -> tuple[float, str]:
    """B — Raggiungibilita'. Computed da radar_summary.

    Misura se il server e' raggiungibile, NON la freschezza dei dati.
    """
    if radar_entry is None:
        return (50.0, "estimated")

    status = radar_entry.get("status", "GREEN")
    note = radar_entry.get("note") or ""
    streak = radar_entry.get("red_streak", 0)

    if status == "GREEN":
        if "SSL" in note or "ssl" in note.lower():
            return (55.0, "computed")
        return (70.0, "computed")
    elif status == "YELLOW":
        return (30.0, "computed")
    elif status == "RED":
        if isinstance(streak, (int, float)) and streak >= 5:
            return (5.0, "computed")
        elif isinstance(streak, (int, float)) and streak >= 2:
            return (15.0, "computed")
        return (20.0, "computed")

    return (50.0, "estimated")


def _licenza_score(protocol: str) -> tuple[float, str]:
    """C — Licenza aperta. Stimato: non abbiamo dati certi."""
    return (50.0, "estimated")


def _datigovit_score() -> tuple[float, str]:
    """D — Presenza su dati.gov.it. Non ancora verificabile via API."""
    return (50.0, "estimated")


def _hvd_score() -> tuple[float, str]:
    """E — HVD compliance. Non ancora computabile."""
    return (50.0, "missing")


def _foia_access_score() -> tuple[float, str]:
    """F — Accessibilita' FOIA. Dipende da anagrafica in data-advocacy."""
    return (50.0, "missing")


def build_scores(
    registry: dict,
    radar_sources: list[dict],
    signals_data: dict | None,
) -> dict:
    """Calcola health score per ogni fonte nel registry."""
    radar_by_id: dict[str, dict] = {s["id"]: s for s in radar_sources}

    signals_by_source: dict[str, list[dict]] = {}
    if signals_data:
        for sig in signals_data.get("signals", []):
            src = sig.get("source", "")
            signals_by_source.setdefault(src, []).append(sig)

    scores_list = []

    for source_id, info in registry.items():
        if not isinstance(info, dict):
            continue

        protocol = info.get("protocol", "unknown")
        radar_entry = radar_by_id.get(source_id)
        signals = signals_by_source.get(source_id, [])

        formato, f_src = _formato_score(protocol, signals)
        raggiung, r_src = _raggiungibilita_score(radar_entry)
        lic, l_src = _licenza_score(protocol)
        dgov, d_src = _datigovit_score()
        hvd, h_src = _hvd_score()
        foia, fo_src = _foia_access_score()

        # Punteggio ponderato — assi "missing" esclusi dal denominatore
        assi_info = [
            (formato, f_src, "formato_aperto"),
            (raggiung, r_src, "raggiungibilita"),
            (lic, l_src, "licenza_aperta"),
            (dgov, d_src, "presenza_datigovit"),
            (hvd, h_src, "hvd_compliance"),
            (foia, fo_src, "accessibilita_foia"),
        ]
        numeratore = 0.0
        denominatore = 0
        for val, src, key in assi_info:
            if src != "missing":
                numeratore += val * PESI[key]
                denominatore += PESI[key]

        totale = round(numeratore / denominatore, 1) if denominatore > 0 else 0.0

        # Label qualitativo (prudenziale)
        if totale >= 80:
            livello = "buono"
        elif totale >= 55:
            livello = "medio"
        elif totale >= 25:
            livello = "debole"
        else:
            livello = "carente"

        # Azione raccomandata (richiede verifica umana)
        if totale < 25:
            azione = "FOIA + verifica DCD"
        elif totale < 50:
            azione = "FOIA"
        elif totale < 70 and formato < 40:
            azione = "segnalazione DCD (formato chiuso — verificare)"
        elif totale < 70 and raggiung < 30:
            azione = "verifica raggiungibilita'"
        else:
            azione = "monitoraggio"

        entry = {
            "source_id": source_id,
            "protocol": protocol,
            "totale": totale,
            "livello": livello,
            "azione_raccomandata": azione,
            "assi": {
                "formato_aperto": {"score": formato, "fonte": f_src},
                "raggiungibilita": {"score": raggiung, "fonte": r_src},
                "licenza_aperta": {"score": lic, "fonte": l_src},
                "presenza_datigovit": {"score": dgov, "fonte": d_src},
                "hvd_compliance": {"score": hvd, "fonte": h_src},
                "accessibilita_foia": {"score": foia, "fonte": fo_src},
            },
        }
        scores_list.append(entry)

    scores_list.sort(key=lambda x: x["totale"], reverse=True)

    dist = {
        "buono": sum(1 for s in scores_list if s["livello"] == "buono"),
        "medio": sum(1 for s in scores_list if s["livello"] == "medio"),
        "debole": sum(1 for s in scores_list if s["livello"] == "debole"),
        "carente": sum(1 for s in scores_list if s["livello"] == "carente"),
    }

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sources_scored": len(scores_list),
        "distribuzione": dist,
        "scores": scores_list,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce open_data_health_scores.json")
    parser.add_argument(
        "--radar",
        default=DEFAULT_RADAR,
        type=Path,
        help="Path a radar_summary.json",
    )
    parser.add_argument(
        "--signals",
        default=DEFAULT_SIGNALS,
        type=Path,
        help="Path a catalog_signals.json",
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY,
        type=Path,
        help="Path a sources_registry.yaml",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        type=Path,
        help="Path output open_data_health_scores.json",
    )
    args = parser.parse_args()

    registry = load_registry(args.registry)

    radar_sources: list[dict] = []
    if args.radar.exists():
        radar = json.loads(args.radar.read_text(encoding="utf-8"))
        radar_sources = radar.get("sources", [])

    signals_data: dict | None = None
    if args.signals.exists():
        signals_data = json.loads(args.signals.read_text(encoding="utf-8"))

    scores = build_scores(registry, radar_sources, signals_data)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(scores, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    dist = scores["distribuzione"]
    print(f"Health scores salvati in {args.out}")
    print(f"  Fonti: {scores['sources_scored']}")
    print(
        f"  Buono: {dist['buono']}, Medio: {dist['medio']}, "
        f"Debole: {dist['debole']}, Carente: {dist['carente']}"
    )

    critici = [s for s in scores["scores"] if s["livello"] in ("debole", "carente")]
    if critici:
        print(f"\nFonti deboli/carenti ({len(critici)}):")
        for s in critici:
            print(f"  {s['source_id']}: {s['totale']}/100 ({s['azione_raccomandata']})")


if __name__ == "__main__":
    main()
