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
    INVENTORY_PARQUET_PATH,
    OPEN_DATA_HEALTH_SCORES_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    load_registry,
)

DEFAULT_RADAR = RADAR_SUMMARY_PATH
DEFAULT_SIGNALS = CATALOG_SIGNALS_PATH
DEFAULT_REGISTRY = REGISTRY_PATH
DEFAULT_INVENTORY = INVENTORY_PARQUET_PATH
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


def _load_inventory_format_stats(path: Path) -> dict[str, dict]:
    """Legge inventory parquet e calcola % formato aperto per fonte CKAN.

    Restituisce dict: source_id → {"total": N, "aperti": N, "perc_aperto": 0-100}.
    Per fonti non CKAN o senza dati, il source_id non e' presente.
    """
    if not path.exists():
        return {}

    try:
        import duckdb

        con = duckdb.connect()
        rows = con.execute(
            """
            SELECT source_id,
                   COUNT(*) as total,
                   COUNT(CASE WHEN format IS NOT NULL AND format != '' THEN 1 END) as con_formato,
                   SUM(CASE WHEN LOWER(format) LIKE '%csv%' OR LOWER(format) LIKE '%json%' OR LOWER(format) LIKE '%xml%' THEN 1 ELSE 0 END) as aperti
            FROM '"""
            + str(path)
            + """'
            WHERE protocol = 'ckan'
            GROUP BY source_id
        """
        ).fetchall()
        stats = {}
        for sid, total, con_formato, aperti in rows:
            stats[sid] = {
                "total": int(total),
                "con_formato": int(con_formato),
                "aperti": int(aperti),
                "perc_aperto": round(int(aperti) / int(total) * 100, 1) if int(total) > 0 else 0.0,
                "copertura": round(int(con_formato) / int(total) * 100, 1)
                if int(total) > 0
                else 0.0,
            }
        return stats
    except Exception as exc:
        print(f"⚠️  Inventory parquet non elaborabile: {exc}")
        return {}


def _load_inventory_license_stats(path: Path) -> dict[str, dict]:
    """Legge inventory parquet e classifica licenze e HVD per fonte.

    Restituisce dict: source_id → {"license_open_pct": 0-100, "has_hvd": bool}.
    Se le colonne license_id/hvd_category non esistono ancora nel parquet
    (generato prima di questo PR), torna vuoto senza errori.
    """
    if not path.exists():
        return {}

    try:
        import duckdb

        con = duckdb.connect()
        # Verifica colonne disponibili — backward compat
        schema = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{path}'").fetchall()}
        if "license_id" not in schema:
            return {}
    except Exception:
        return {}

    try:
        con = duckdb.connect()
        rows = con.execute(
            f"""
            SELECT source_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN LOWER(license_id) LIKE '%cc-by%' OR LOWER(license_id) LIKE '%cc-zero%' OR LOWER(license_id) LIKE '%cc0%' OR LOWER(license_id) LIKE '%odbl%' OR LOWER(license_id) LIKE '%iodl%' OR LOWER(license_id) = 'other-open' OR LOWER(license_title) LIKE '%creative commons%' OR LOWER(license_title) LIKE '%iodl%' THEN 1 ELSE 0 END) as licenze_aperte,
                   SUM(CASE WHEN hvd_category IS NOT NULL AND hvd_category != '' THEN 1 ELSE 0 END) as con_hvd
            FROM '{path}'
            WHERE protocol = 'ckan'
            GROUP BY source_id
        """
        ).fetchall()
        stats = {}
        for sid, total, licenze_aperte, con_hvd in rows:
            stats[sid] = {
                "total": int(total),
                "licenze_aperte": int(licenze_aperte),
                "perc_licenza_aperta": round(int(licenze_aperte) / int(total) * 100, 1)
                if int(total) > 0
                else 0.0,
                "has_hvd": int(con_hvd) > 0,
            }
        return stats
    except Exception as exc:
        print(f"⚠️  Inventory licenza non elaborabile: {exc}")
        return {}


def _formato_score(
    protocol: str,
    signals: list[dict],
    inventory_stats: dict | None = None,
    source_id: str = "",
) -> tuple[float, str]:
    """A — Formato aperto.

    Se disponibili, usa i formati reali dall'inventory (CKAN).
    Altrimenti stima da protocol + segnali HTML.
    """
    # 1. Se abbiamo dati reali dall'inventory CKAN, usali
    if inventory_stats and source_id in inventory_stats:
        stats = inventory_stats[source_id]
        perc = stats["perc_aperto"]
        # Se la copertura e' bassa (<50% dei dataset con formato noto),
        # il dato e' parziale — non lo marcamo "computed"
        fonte = "computed" if stats["copertura"] >= 50.0 else "parziale"
        if perc >= 95.0:
            return (90.0, fonte)
        elif perc >= 80.0:
            return (75.0, fonte)
        elif perc >= 50.0:
            return (55.0, fonte)
        elif perc >= 20.0:
            return (35.0, fonte)
        else:
            return (20.0, fonte)

    # 2. Fallback: segnali HTML (csv_magnet)
    for sig in signals:
        detail = sig.get("detail", "")
        if "CSV" in detail and ("JSON" in detail or "XML" in detail):
            return (80.0, "computed")
        if "CSV" in detail:
            return (75.0, "computed")

    # 3. Stima per protocollo
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
        # SSL issue strutturato (ssl_issue field) — più affidabile della nota testuale
        if radar_entry and radar_entry.get("ssl_issue"):
            return (55.0, "computed")
        # Fallback: nota testuale per history precedente all'introduzione di ssl_issue
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


def _licenza_score(
    protocol: str,
    license_stats: dict | None = None,
    source_id: str = "",
) -> tuple[float, str]:
    """C — Licenza aperta. Computed da inventory se disponibile."""
    if license_stats and source_id in license_stats:
        stats = license_stats[source_id]
        perc = stats["perc_licenza_aperta"]
        if perc >= 90.0:
            return (85.0, "computed")
        elif perc >= 50.0:
            return (60.0, "computed")
        elif perc > 0:
            return (40.0, "computed")
        else:
            return (50.0, "estimated")
    return (50.0, "estimated")


def _datigovit_score() -> tuple[float, str]:
    """D — Presenza su dati.gov.it. Non ancora verificabile via API."""
    return (50.0, "estimated")


def _hvd_score(
    license_stats: dict | None = None,
    source_id: str = "",
) -> tuple[float, str]:
    """E — HVD compliance. Computed da inventory se disponibile."""
    if license_stats and source_id in license_stats:
        if license_stats[source_id]["has_hvd"]:
            return (80.0, "computed")
        # Sappiamo che non ha HVD (inventory ha la colonna, e' vuota)
        return (50.0, "computed")
    return (50.0, "missing")


def _foia_access_score() -> tuple[float, str]:
    """F — Accessibilita' FOIA. Dipende da anagrafica in data-advocacy."""
    return (50.0, "missing")


def build_scores(
    registry: dict,
    radar_sources: list[dict],
    signals_data: dict | None,
    inventory_stats: dict | None = None,
    license_stats: dict | None = None,
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

        formato, f_src = _formato_score(protocol, signals, inventory_stats, source_id)
        raggiung, r_src = _raggiungibilita_score(radar_entry)
        lic, l_src = _licenza_score(protocol, license_stats, source_id)
        dgov, d_src = _datigovit_score()
        hvd, h_src = _hvd_score(license_stats, source_id)
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
        if livello == "carente":
            azione = "FOIA + verifica DCD"
        elif livello == "debole":
            azione = "verifica umana"
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
        "--inventory",
        default=DEFAULT_INVENTORY,
        type=Path,
        help="Path a catalog_inventory_latest.parquet",
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

    inventory_stats = _load_inventory_format_stats(args.inventory)
    license_stats = _load_inventory_license_stats(args.inventory)

    scores = build_scores(registry, radar_sources, signals_data, inventory_stats, license_stats)

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
