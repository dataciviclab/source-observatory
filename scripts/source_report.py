"""
Source Report — logica di aggregazione e costruzione report per fonte.

Funzioni pubbliche:
    aggregate_inventory_rows(rows)       → formato/anni/organizzazioni
    aggregate_source_check(results)      → qualità item-level
    compute_operational_verdict(...)     → verdict composito
    build_report(...)                    → report JSON completo
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── AGGREGAZIONI ──────────────────────────────────────────────────────────────


def aggregate_inventory_rows(rows: list[dict]) -> dict:
    """Formati, anni, organizzazioni dalle righe inventory."""
    if not rows:
        return {"formats": {}, "years_range": None, "organizations": []}

    fmt_dist = Counter(_safe_str(r.get("format")).upper() for r in rows)

    years: set[int] = set()
    for r in rows:
        for k in ("year_min", "year_signal", "issued"):
            v = r.get(k)
            if v is not None:
                try:
                    years.add(int(v))
                except (ValueError, TypeError):
                    pass

    def _is_valid(val):
        return val is not None and not (isinstance(val, float) and math.isnan(val))

    orgs = {r.get("organization") for r in rows if _is_valid(r.get("organization"))}

    return {
        "formats": dict(fmt_dist.most_common()),
        "years_range": [min(years), max(years)] if years else None,
        "organizations": sorted(orgs) if orgs else [],
    }


def _safe_str(val, fallback="?"):
    """Converte in stringa, gestendo None e NaN."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return fallback
    return str(val)


def aggregate_source_check(results: list[dict]) -> dict:
    """Metriche qualità da validated.parquet (output nuova pipeline).

    Campi disponibili: dataset_group, source_id, reachable, url, format,
    columns, num_columns, readiness_score (0-4), status_code, content_type,
    dataset_group_year_min, dataset_group_year_max.
    """
    if not results:
        return {
            "total": 0,
            "reachable": 0,
            "formats": {},
            "with_csv_schema": 0,
            "avg_readiness": None,
            "no_year": 0,
            "problematic": [],
            "csv_count": 0,
            "top_items": [],
        }

    total = len(results)
    reachable = sum(1 for r in results if r.get("reachable") is True)
    not_reachable = sum(1 for r in results if r.get("reachable") is False)
    not_checked = sum(1 for r in results if r.get("reachable") is None)

    formats = Counter(r.get("format") or "?" for r in results)
    csv_count = sum(1 for r in results if r.get("format") and "csv" in r.get("format", "").lower())
    with_schema = [r for r in results if r.get("num_columns") and r["num_columns"] > 0]

    # Readiness score medio
    scores = [r["readiness_score"] for r in results if r.get("readiness_score") is not None]
    avg_readiness = round(sum(scores) / len(scores), 1) if scores else None

    # Anni
    no_year = sum(
        1
        for r in results
        if r.get("dataset_group_year_min") is None
        or (
            isinstance(r.get("dataset_group_year_min"), float)
            and math.isnan(r["dataset_group_year_min"])
        )
    )

    # Problematici (non reachable)
    problematic = [
        {
            "name": r.get("dataset_group", "?"),
            "url": str(r.get("url", ""))[:80],
            "error": r.get("error"),
        }
        for r in results
        if r.get("reachable") is False
    ]

    # Top items per readiness_score
    scored = [
        {
            "name": r.get("dataset_group", "?"),
            "score": r.get("readiness_score") or 0,
            "year_range": (
                [int(r["dataset_group_year_min"]), int(r["dataset_group_year_max"])]
                if r.get("dataset_group_year_min") is not None
                and r.get("dataset_group_year_max") is not None
                and not (
                    isinstance(r.get("dataset_group_year_min"), float)
                    and math.isnan(r["dataset_group_year_min"])
                )
                and not (
                    isinstance(r.get("dataset_group_year_max"), float)
                    and math.isnan(r["dataset_group_year_max"])
                )
                else None
            ),
            "format": r.get("format"),
            "reachable": r.get("reachable") is True,
        }
        for r in results
        if r.get("readiness_score") is not None
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)

    return {
        "total": total,
        "reachable": reachable,
        "not_reachable": not_reachable,
        "not_checked_non_csv": not_checked,
        "formats": dict(formats.most_common()),
        "csv_count": csv_count,
        "with_csv_schema": len(with_schema),
        "avg_readiness": avg_readiness,
        "no_year": no_year,
        "problematic": problematic[:3],
        "top_items": scored[:5],
        "last_run": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }


# ── FORMATO APERTO ────────────────────────────────────────────────────────────


def compute_formato_aperto(
    results: list[dict],
    rows: list[dict] | None = None,
) -> dict:
    """Metrica 'formato aperto': percentuale di item in formato aperto.

    I formati includono formati tabulari classici (CSV, JSON, XML)
    e formati RDF (RDF_TURTLE, RDF_N_TRIPLES, SPARQL).
    Usa source-check results se disponibili (formato reale via HTTP probe),
    altrimenti fallback su inventory rows (metadato).
    """
    APERTI = {
        "CSV",
        "JSON",
        "XML",
        "RDF",
        "TTL",
        "RDF_TURTLE",
        "RDF_N_TRIPLES",
        "RDF_XML",
        "SPARQL",
        "SPARQL_NAMED_GRAPH",
    }

    # Source-check: formato reale da probe HTTP
    probeable = [r for r in results if r.get("probe_applicable", True)]
    if probeable:
        total = len(probeable)
        n_aperto = 0
        reachable = 0
        for r in probeable:
            if r.get("reachable"):
                reachable += 1
            fmt = _safe_str(r.get("resource_format")).upper()
            if any(a in fmt for a in APERTI):
                n_aperto += 1

        perc_reachable = round(reachable / total * 100, 1) if total > 0 else 0.0
        perc_aperto = round(n_aperto / total * 100, 1) if total > 0 else 0.0

        # Scoring: stesso tiering di build_compliance_scores.py
        if perc_reachable < 30:
            score = 10.0
        elif perc_reachable < 50:
            score = 15.0
        elif perc_aperto >= 95:
            score = 90.0
        elif perc_aperto >= 80:
            score = 75.0
        elif perc_aperto >= 50:
            score = 55.0
        elif perc_aperto >= 20:
            score = 35.0
        elif perc_aperto > 0:
            score = 20.0
        else:
            score = 5.0

        return {
            "score": score,
            "perc_aperto": perc_aperto,
            "perc_reachable": perc_reachable,
            "total": total,
            "fonte": "source_check",
        }

    # Fallback inventory: metadato formato
    if rows:
        total = len(rows)
        n_aperto = 0
        for r in rows:
            fmt = _safe_str(r.get("format")).upper()
            if any(a in fmt for a in APERTI):
                n_aperto += 1

        perc_aperto = round(n_aperto / total * 100, 1) if total > 0 else 0.0
        if perc_aperto >= 95:
            score = 90.0
        elif perc_aperto >= 80:
            score = 75.0
        elif perc_aperto >= 50:
            score = 55.0
        elif perc_aperto >= 20:
            score = 35.0
        else:
            score = 20.0

        return {
            "score": score,
            "perc_aperto": perc_aperto,
            "total": total,
            "fonte": "inventory",
        }

    return {"score": 0.0, "perc_aperto": 0.0, "total": 0, "fonte": "missing"}


# ── VERDICT OPERATIVO ────────────────────────────────────────────────────────


def compute_operational_verdict(
    radar_result: dict | None,
    inventory_data: dict,
    source_check_data: dict,
) -> dict:
    """Verdict composito: STABLE / DOWN / INVENTORY_CHANGED / STALE / PARTIALLY_SCOPED."""
    triggers: list[str] = []

    radar_status = (radar_result or {}).get("status")
    if radar_status == "RED":
        triggers.append("radar_red")

    delta = inventory_data.get("delta")
    if delta is not None and delta != 0:
        triggers.append("inventory_changed")

    freshness = inventory_data.get("freshness_hours")
    if freshness is not None and freshness > 168:
        triggers.append("inventory_stale")

    coverage = source_check_data.get("coverage_pct")
    if coverage is not None and coverage < 50:
        triggers.append("source_check_partial")

    if not triggers:
        triggers.append("all_green")

    if "radar_red" in triggers:
        label = "DOWN"
        score = "down"
        next_action = "investigate downtime"
    elif "inventory_changed" in triggers:
        label = "INVENTORY_CHANGED"
        score = "changed"
        next_action = "review inventory changes"
    elif "inventory_stale" in triggers:
        label = "STALE"
        score = "stale"
        next_action = "refresh inventory"
    elif "source_check_partial" in triggers:
        label = "PARTIALLY_SCOPED"
        score = "partial"
        next_action = "complete source-check"
    else:
        label = "STABLE"
        score = "stable"
        next_action = None

    return {
        "label": label,
        "score": score,
        "triggers": triggers,
        "next_action": next_action,
    }


# ── BUILD REPORT ──────────────────────────────────────────────────────────────


def build_report(
    source_id: str,
    cfg: dict,
    radar_result: dict | None,
    rows: list[dict],
    captured_at: str | None,
    results: list[dict],
    health_entry: dict | None = None,
    timing: dict | None = None,
) -> dict:
    """Costruisce il source report JSON per una fonte.

    Args:
        source_id: ID dalla registry
        cfg: Config della fonte (da sources_registry.yaml)
        radar_result: Output di _radar() o None
        rows: Righe inventory (da CollectorResult.rows)
        captured_at: Timestamp ISO inventory
        results: Risultati source-check
        health_entry: Output di _health_score() o None
        timing: Dict {fase: secondi}
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    timing = timing or {}

    # Identity
    identity = {
        "source_id": source_id,
        "protocol": cfg.get("protocol"),
        "base_url": cfg.get("base_url"),
        "source_kind": cfg.get("source_kind"),
        "observation_mode": cfg.get("observation_mode"),
        "verdict": cfg.get("verdict"),
        "note": cfg.get("note"),
        "last_probed": cfg.get("last_probed"),
    }

    # Health
    health: dict | None = None
    if radar_result:
        health = {
            "radar_status": radar_result.get("status"),
            "http_code": radar_result.get("http_code"),
            "note": radar_result.get("note"),
            "ssl_fallback": radar_result.get("ssl_fallback_used", False),
        }

    # Inventory
    baseline = cfg.get("catalog_baseline") or {}
    inventory: dict = {
        "total_items": len(rows),
        "method": baseline.get("method"),
        "captured_at": captured_at,
        "baseline_value": baseline.get("value"),
        "baseline_date": baseline.get("captured_at"),
    }

    if captured_at and len(rows) > 0:
        try:
            cap = datetime.fromisoformat(captured_at)
            inventory["freshness_hours"] = round(
                (datetime.now(timezone.utc) - cap).total_seconds() / 3600, 1
            )
        except (ValueError, TypeError):
            pass

    delta = None
    bv = baseline.get("value")
    if bv is not None and len(rows) > 0:
        delta = len(rows) - bv
    inventory["delta"] = delta
    inventory["delta_pct"] = (
        round(delta / bv * 100, 1) if bv and bv > 0 and delta is not None else 0.0
    )

    inv_agg = aggregate_inventory_rows(rows)
    if inv_agg["formats"]:
        inventory["formats"] = inv_agg["formats"]
    if inv_agg["years_range"]:
        inventory["years_range"] = inv_agg["years_range"]

    # Source-check
    sc_agg = aggregate_source_check(results)
    source_check: dict = {
        "last_run": sc_agg.get("last_run"),
        "total_scored": sc_agg["total"],
        "reachable": sc_agg["reachable"],
        "csv_count": sc_agg.get("csv_count", 0),
        "with_csv_schema": sc_agg.get("with_csv_schema", 0),
        "avg_readiness": sc_agg.get("avg_readiness"),
        "top_items": sc_agg["top_items"],
        "coverage_pct": (
            round(sc_agg["total"] / len(rows) * 100, 1) if rows and sc_agg["total"] else None
        ),
        "formato_aperto": compute_formato_aperto(results, rows),
    }

    # Datasets in use
    datasets_in_use = [
        {"slug": slug, "status": "published"} for slug in (cfg.get("datasets_in_use") or [])
    ]

    # Signals (sostituiti da validated metrics — catalog_signals.json non più prodotto)
    signals = [
        {
            "type": "validated_metrics",
            "result": "stabile",
            "detail": "Metriche da validated.parquet.",
        }
    ]

    # Operational verdict
    operational_verdict = compute_operational_verdict(radar_result, inventory, source_check)

    report = {
        "source_id": source_id,
        "generated_at": now_iso,
        "report_version": 1,
        "timing": {k: v for k, v in timing.items() if not isinstance(v, str)},
        "identity": identity,
        "health": health,
        "inventory": inventory,
        "source_check": source_check,
        "datasets_in_use": datasets_in_use,
        "signals": signals,
        "operational_verdict": operational_verdict,
    }

    return {k: v for k, v in report.items() if v is not None}
