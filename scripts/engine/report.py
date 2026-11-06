"""
Source Report — logica di aggregazione e costruzione report per fonte.

Primitiva del motore: è **stdlib puro** e la usano entrambi i ruoli — il
centrale (``scripts/build_source_reports.py``, report di fonte in
``data/reports/``) e il motore (``scripts/catalog/build.py``, ``catalog.json``).
Stava in ``scripts/source_report.py``; ora il centrale importa da qui.

Funzioni pubbliche:
    aggregate_inventory_rows(rows)       → formato/anni/organizzazioni
    aggregate_source_check(results)      → qualità item-level
    compute_operational_verdict(...)     → verdict composito
    build_report(...)                    → report JSON completo
"""

from __future__ import annotations

import math
import time
from collections import Counter
from datetime import datetime, timezone

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
    columns, num_columns, readiness_score (0-10), status_code, content_type,
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
            "not_checked_non_csv": 0,
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
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
            fmt = (
                _safe_str(r.get("resource_format"), fallback="") or _safe_str(r.get("format"))
            ).upper()
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
    observation_mode: str | None = None,
) -> dict:
    """Verdict composito, con priorità esplicita.

    Ordine: DOWN > NO_DATA/HEALTH_ONLY > UNREACHABLE > STALE >
    INVENTORY_CHANGED > PARTIALLY_SCOPED > STABLE.

    Regola: ``STABLE`` non è il default. Se non c'è misura, il verdict è
    ``NO_DATA`` (o ``HEALTH_ONLY`` per le fonti radar-only).
    """
    triggers: list[str] = []

    radar_status = (radar_result or {}).get("status")
    if radar_status == "RED":
        triggers.append("radar_red")

    scored = int(source_check_data.get("total_scored") or 0)
    reachable = int(source_check_data.get("reachable") or 0)
    not_checked = int(source_check_data.get("not_checked_non_csv") or 0)
    probeable = max(0, scored - not_checked)
    reachability = round(reachable / probeable * 100, 1) if probeable else None
    if scored == 0:
        triggers.append("health_only" if observation_mode == "radar-only" else "no_data")
    elif probeable == 0:
        triggers.append("not_probeable")
    elif reachability is not None and reachability < 50:
        triggers.append("unreachable")

    stale_items = int(inventory_data.get("stale_items") or 0)
    if stale_items:
        triggers.append("stale_rows")
    freshness = inventory_data.get("freshness_hours")
    if freshness is not None and freshness > 168:
        triggers.append("inventory_stale")

    delta = inventory_data.get("delta")
    if delta is not None and delta != 0:
        triggers.append("inventory_changed")

    coverage = source_check_data.get("coverage_pct")
    if coverage is not None and coverage < 50:
        triggers.append("source_check_partial")

    if not triggers:
        triggers.append("all_green")

    if "radar_red" in triggers:
        label, score, next_action = "DOWN", "down", "investigate downtime"
    elif "no_data" in triggers:
        label, score, next_action = "NO_DATA", "no_data", "run inventory/validate"
    elif "health_only" in triggers:
        label, score, next_action = "HEALTH_ONLY", "health_only", None
    elif "not_probeable" in triggers:
        label, score, next_action = (
            "NOT_PROBEABLE",
            "not_probeable",
            "add a probeable format/schema",
        )
    elif "unreachable" in triggers:
        label, score, next_action = "UNREACHABLE", "unreachable", "verify used items"
    elif "stale_rows" in triggers or "inventory_stale" in triggers:
        label, score, next_action = "STALE", "stale", "refresh inventory"
    elif "inventory_changed" in triggers:
        label, score, next_action = "INVENTORY_CHANGED", "changed", "review inventory changes"
    elif "source_check_partial" in triggers:
        label, score, next_action = "PARTIALLY_SCOPED", "partial", "complete source-check"
    else:
        label, score, next_action = "STABLE", "stable", None

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
    total_groups: int | None = None,
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
        total_groups: Gruppi logici attesi prima della validazione
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
    stale_items = sum(1 for row in rows if row.get("source_status") == "stale")
    inventory: dict = {
        "total_items": len(rows),
        "active_items": len(rows) - stale_items,
        "stale_items": stale_items,
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
        "not_checked_non_csv": sc_agg["not_checked_non_csv"],
        "probeable_items": sc_agg["total"] - sc_agg["not_checked_non_csv"],
        "reachability_pct": (
            round(
                sc_agg["reachable"] / (sc_agg["total"] - sc_agg["not_checked_non_csv"]) * 100,
                1,
            )
            if sc_agg["total"] - sc_agg["not_checked_non_csv"]
            else None
        ),
        "coverage_pct": (round(sc_agg["total"] / total_groups * 100, 1) if total_groups else None),
        "formato_aperto": compute_formato_aperto(results, rows),
    }

    # Datasets in use: status = stato d'uso, non stage editoriale.
    datasets_in_use = [
        {"slug": slug, "status": "in_use"} for slug in (cfg.get("datasets_in_use") or [])
    ]

    # Signals legacy: catalog_signals.json è ancora scritto per ACB.
    signals = [
        {
            "type": "validated_metrics",
            "result": "stabile",
            "detail": "Metriche da validated.parquet.",
        }
    ]

    # Operational verdict
    operational_verdict = compute_operational_verdict(
        radar_result,
        inventory,
        source_check,
        observation_mode=cfg.get("observation_mode"),
    )

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
