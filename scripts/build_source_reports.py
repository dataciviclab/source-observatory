#!/usr/bin/env python3
"""
CI script: carica artifact CI e produce source report per ogni fonte.

Legge:
  - sources_registry.yaml
  - radar_summary.json
  - catalog_inventory_latest.parquet
  - catalog_inventory_report.json
  - source_check_results.parquet
  - catalog_signals.json

Produce:
  - data/reports/source_reports/{source_id}.json   (33 file)
  - data/reports/sources_dashboard.json             (index)

Utilizzo:
    python scripts/build_source_reports.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from _constants import load_registry  # noqa: E402

from scripts.source_report import build_report  # noqa: E402


def _load_radar() -> dict[str, dict]:
    """Carica radar_summary.json → {source_id: entry}."""
    path = REPO_ROOT / "data" / "radar" / "radar_summary.json"
    if not path.exists():
        print("⚠️  radar_summary.json non trovato")
        return {}
    data = json.loads(path.read_text())
    return {s["id"]: s for s in data.get("sources", [])}


def _load_inventory_rows() -> dict[str, list[dict]]:
    """Carica inventory parquet → {source_id: [rows]}."""
    path = (
        REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_latest.parquet"
    )
    if not path.exists():
        print("⚠️  catalog_inventory_latest.parquet non trovato")
        return {}
    import duckdb

    con = duckdb.connect()
    rows = con.execute(f"SELECT * FROM '{path}'").fetchdf().to_dict("records")
    result: dict[str, list[dict]] = {}
    for r in rows:
        sid = r.get("source_id")
        if sid:
            result.setdefault(sid, []).append(r)
    return result


def _load_inventory_report() -> dict:
    """Carica inventoy report → {captured_at, sources: {source_id: info}}."""
    path = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_report.json"
    if not path.exists():
        print("⚠️  catalog_inventory_report.json non trovato")
        return {"captured_at": None, "sources": {}}
    data = json.loads(path.read_text())
    return {
        "captured_at": data.get("captured_at"),
        "sources": data.get("sources", {}),
    }


def _load_source_check() -> dict[str, list[dict]]:
    """Carica source-check parquet → {source_id: [results]}."""
    path = REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
    if not path.exists():
        print("⚠️  source_check_results.parquet non trovato")
        return {}
    import duckdb

    con = duckdb.connect()
    rows = con.execute(f"SELECT * FROM '{path}'").fetchdf().to_dict("records")
    result: dict[str, list[dict]] = {}
    for r in rows:
        sid = r.get("source_id")
        if sid:
            result.setdefault(sid, []).append(r)
    return result


def _make_radar_result(entry: dict | None) -> dict | None:
    """Converte entry radar in formato atteso da build_report."""
    if not entry:
        return None
    return {
        "status": entry.get("status"),
        "http_code": entry.get("http_code"),
        "note": entry.get("note"),
        "ssl_fallback_used": entry.get("ssl_fallback_used", False),
    }


def main() -> int:
    t_start = datetime.now()

    # 1. Carica artifact
    reg = load_registry()
    radar_map = _load_radar()
    inventory_rows = _load_inventory_rows()
    inventory_report = _load_inventory_report()
    sc_results = _load_source_check()

    global_captured_at = inventory_report.get("captured_at")

    # 2. Directory output
    reports_dir = REPO_ROOT / "data" / "reports" / "source_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 3. Genera report per ogni fonte
    source_summaries: list[dict] = []
    ok = 0
    skip = 0

    for source_id, cfg in sorted(reg.items()):
        # Radar
        radar_result = _make_radar_result(radar_map.get(source_id))

        # Inventory rows
        rows = inventory_rows.get(source_id, [])

        # captured_at: dal report se disponibile, altrimenti dalla riga inventory
        captured_at = global_captured_at
        if not captured_at and rows:
            captured_at = rows[0].get("captured_at")

        # Source-check results
        results = sc_results.get(source_id, [])

        # Build report
        try:
            report = build_report(
                source_id=source_id,
                cfg=cfg,
                radar_result=radar_result,
                rows=rows,
                captured_at=captured_at,
                results=results,
            )
        except Exception as e:
            print(f"  ❌ {source_id}: build_report fallito — {e}")
            skip += 1
            continue

        # Salva (default=str gestisce Timestamp/datetime da pandas)
        (reports_dir / f"{source_id}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str)
        )
        ok += 1

        # Riga per dashboard
        verdict = report.get("operational_verdict", {})
        source_summaries.append(
            {
                "source_id": source_id,
                "protocol": cfg.get("protocol"),
                "radar": (radar_result or {}).get("status"),
                "inventory_items": len(rows),
                "scored_items": report.get("source_check", {}).get("total_scored", 0),
                "intake_candidates": report.get("source_check", {}).get("intake_candidates", 0),
                "datasets_in_use": len(cfg.get("datasets_in_use") or []),
                "verdict": verdict.get("label"),
                "verdict_score": verdict.get("score"),
                "last_inventory": captured_at,
            }
        )

    # 4. Dashboard index
    dashboard = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_version": 1,
        "total_sources": len(reg),
        "summary": {
            "by_verdict": dict(Counter(s["verdict"] for s in source_summaries if s["verdict"])),
            "by_protocol": dict(Counter(s["protocol"] for s in source_summaries)),
            "tot_inventory_items": sum(s["inventory_items"] for s in source_summaries),
            "tot_scored_items": sum(s["scored_items"] for s in source_summaries),
            "tot_intake_candidates": sum(s["intake_candidates"] for s in source_summaries),
            "tot_datasets_in_use": sum(s["datasets_in_use"] for s in source_summaries),
        },
        "sources": source_summaries,
    }

    dashboard_path = REPO_ROOT / "data" / "reports" / "sources_dashboard.json"
    dashboard_path.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False, default=str))

    elapsed = (datetime.now() - t_start).total_seconds()
    print(f"\n✅ Report: {ok} generati, {skip} falliti  ({elapsed:.1f}s)")
    print(f"   Report:    {reports_dir}/")
    print(f"   Dashboard: {dashboard_path}")
    return 0 if skip == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
