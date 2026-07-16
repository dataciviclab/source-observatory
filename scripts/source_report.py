"""
Source Report — logica di aggregazione e costruzione report per fonte.

Funzioni pubbliche:
    aggregate_inventory_rows(rows)       → formato/anni/organizzazioni
    aggregate_source_check(results)      → qualità item-level
    compute_operational_verdict(...)     → verdict composito
    build_report(...)                    → report JSON completo
"""

from __future__ import annotations

import json
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
    """Metriche qualità dai risultati source-check."""
    if not results:
        return {
            "total": 0,
            "reachable": 0,
            "circuit": 0,
            "content_mismatch": 0,
            "formats": {},
            "statuses": {},
            "with_preview_count": 0,
            "paqa_avg": None,
            "paqa_verdicts": {},
            "no_gran": 0,
            "no_year": 0,
            "has_no_url": 0,
            "problematic": [],
            "intake_candidates": 0,
            "needs_review": 0,
            "top_items": [],
            "last_run": None,
        }

    total = len(results)
    reachable = sum(1 for r in results if r.get("reachable"))
    circuit = sum(1 for r in results if _safe_str(r.get("check_notes")) == "circuit_open")
    content_mismatch = sum(
        1 for r in results if _safe_str(r.get("check_notes")).startswith("content_mismatch")
    )
    formats = Counter(r.get("resource_format") or "?" for r in results)
    statuses = Counter(_safe_str(r.get("http_status")) for r in results)

    # Preview / PAQA
    with_preview = [r for r in results if r.get("paqa_score") is not None]
    paqa_avg = None
    paqa_verdicts: Counter = Counter()
    if with_preview:
        paqa_avg = sum(r["paqa_score"] for r in with_preview if r["paqa_score"] is not None) / len(
            with_preview
        )
        paqa_verdicts = Counter(r.get("paqa_verdict") or "?" for r in with_preview)

    # Needs review
    no_gran = sum(1 for r in results if r.get("granularity") in (None, "", "non_determinato"))
    no_year = 0
    for r in results:
        ym = r.get("year_min")
        if ym is None or (isinstance(ym, float) and math.isnan(ym)):
            no_year += 1
    has_no_url = sum(1 for r in results if not r.get("url_checked"))
    problematic = [r for r in results if not r.get("reachable")]

    # Intake
    intake_candidates = sum(1 for r in results if r.get("intake_candidate"))
    needs_review = sum(1 for r in results if r.get("needs_review"))

    # Top items per intake_score
    scored = [
        {
            "name": r.get("item_name") or r.get("title", "?"),
            "score": r.get("intake_score") or 0,
            "year_range": (
                [int(r["year_min"]), int(r["year_max"])]
                if r.get("year_min") is not None
                and r.get("year_max") is not None
                and not (isinstance(r.get("year_min"), float) and math.isnan(r["year_min"]))
                and not (isinstance(r.get("year_max"), float) and math.isnan(r["year_max"]))
                else None
            ),
            "format": r.get("resource_format"),
            "reachable": r.get("reachable", False),
        }
        for r in results
        if r.get("intake_score") is not None
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)

    last_run = results[0].get("check_timestamp") if results else None

    return {
        "total": total,
        "reachable": reachable,
        "circuit": circuit,
        "content_mismatch": content_mismatch,
        "formats": dict(formats.most_common()),
        "statuses": dict(statuses.most_common()),
        "with_preview_count": len(with_preview),
        "paqa_avg": round(paqa_avg, 1) if paqa_avg is not None else None,
        "paqa_verdicts": dict(paqa_verdicts.most_common()),
        "no_gran": no_gran,
        "no_year": no_year,
        "has_no_url": has_no_url,
        "problematic": problematic[:3],
        "intake_candidates": intake_candidates,
        "needs_review": needs_review,
        "top_items": scored[:5],
        "last_run": last_run,
    }


# ── FORMATO APERTO ────────────────────────────────────────────────────────────


def compute_formato_aperto(
    results: list[dict],
    rows: list[dict] | None = None,
) -> dict:
    """Metrica 'formato aperto': percentuale di item in formato aperto (CSV/JSON/XML).

    Usa source-check results se disponibili (formato reale via HTTP probe),
    altrimenti fallback su inventory rows (metadato).
    """
    APERTI = {"CSV", "JSON", "XML"}

    # Source-check: formato reale da probe HTTP
    probeable = [r for r in results if r.get("probe_applicable", True)]
    if probeable:
        total = len(probeable)
        n_aperto = 0
        reachable = 0
        for r in probeable:
            if r.get("reachable"):
                reachable += 1
            fmt = _safe_str(r.get("resource_format")).upper().strip()
            if fmt in APERTI:
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
            fmt = _safe_str(r.get("format")).upper().strip()
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
        "last_run": sc_agg["last_run"],
        "total_scored": sc_agg["total"],
        "reachable": sc_agg["reachable"],
        "intake_candidates": sc_agg["intake_candidates"],
        "needs_review": sc_agg["needs_review"],
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

    # Signals (da catalog_signals.json se presente)
    signals: list[dict] = []
    signals_path = REPO_ROOT / "data" / "catalog" / "catalog_signals.json"
    if signals_path.exists():
        try:
            all_signals = json.loads(signals_path.read_text()).get("signals", [])
            signals = [
                {
                    "type": s.get("signal_type"),
                    "result": s.get("result"),
                    "detail": s.get("detail"),
                    "metric_value": s.get("metric_value"),
                    "suggested_action": s.get("suggested_action"),
                }
                for s in all_signals
                if s.get("source") == source_id
            ]
        except Exception:
            pass

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
