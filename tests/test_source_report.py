"""Smoke test per scripts/source_report.py: aggregazioni, build_report, verdict."""

from __future__ import annotations

import pytest

from scripts.source_report import (
    aggregate_inventory_rows,
    aggregate_source_check,
    build_report,
    compute_formato_aperto,
    compute_operational_verdict,
)

# ── Sample data ──────────────────────────────────────────────────────────────

_SAMPLE_ROWS = [
    {"item_id": "1", "format": "CSV", "organization": "Test Org", "year_min": 2020},
    {"item_id": "2", "format": "JSON", "organization": "Test Org", "year_min": 2021},
    {"item_id": "3", "format": "PDF", "organization": "Other Org", "year_min": 2020},
]

_SAMPLE_RESULTS = [
    {
        "item_name": "test-dataset-1",
        "title": "Test Dataset 1",
        "reachable": True,
        "intake_score": 50.0,
        "intake_candidate": False,
        "needs_review": False,
        "resource_format": "CSV",
        "check_notes": None,
        "http_status": 200,
        "granularity": "comunale",
        "year_min": 2020.0,
        "year_max": 2020.0,
        "probe_applicable": True,
        "check_timestamp": "2026-07-16T10:00:00+00:00",
    },
    {
        "item_name": "test-dataset-2",
        "title": "Test Dataset 2",
        "reachable": True,
        "intake_score": 80.0,
        "intake_candidate": True,
        "needs_review": False,
        "resource_format": "JSON",
        "check_notes": None,
        "http_status": 200,
        "granularity": "regionale",
        "year_min": 2021.0,
        "year_max": 2021.0,
        "probe_applicable": True,
        "check_timestamp": "2026-07-16T10:00:00+00:00",
    },
    {
        "item_name": "test-dataset-3",
        "title": "Test Dataset 3",
        "reachable": False,
        "intake_score": 10.0,
        "intake_candidate": False,
        "needs_review": True,
        "resource_format": "XLSX",
        "check_notes": "circuit_open",
        "http_status": 0,
        "granularity": "non_determinato",
        "year_min": None,
        "year_max": None,
        "probe_applicable": True,
        "check_timestamp": "2026-07-16T10:00:00+00:00",
    },
]

_SAMPLE_CFG = {
    "protocol": "ckan",
    "base_url": "https://example.com/api",
    "source_kind": "catalog",
    "observation_mode": "catalog-watch",
    "verdict": "go",
    "note": "Test source",
    "last_probed": "2026-07-16",
    "catalog_baseline": {
        "method": "package_search",
        "value": 3,
        "captured_at": "2026-05-01",
    },
    "datasets_in_use": ["test_dataset"],
}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestAggregateInventoryRows:
    @pytest.mark.smoke
    def test_empty(self):
        agg = aggregate_inventory_rows([])
        assert agg["formats"] == {}
        assert agg["years_range"] is None
        assert agg["organizations"] == []

    @pytest.mark.smoke
    def test_basic(self):
        agg = aggregate_inventory_rows(_SAMPLE_ROWS)
        assert agg["formats"] == {"CSV": 1, "JSON": 1, "PDF": 1}
        assert agg["years_range"] == [2020, 2021]
        assert sorted(agg["organizations"]) == ["Other Org", "Test Org"]

    @pytest.mark.smoke
    def test_handles_nan_format(self):
        rows = [{"item_id": "1", "format": float("nan"), "organization": "Org"}]
        agg = aggregate_inventory_rows(rows)
        assert "?" in agg["formats"] or "NAN" in agg["formats"]


class TestAggregateSourceCheck:
    @pytest.mark.smoke
    def test_empty(self):
        agg = aggregate_source_check([])
        assert agg["total"] == 0
        assert agg["reachable"] == 0

    @pytest.mark.smoke
    def test_basic(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert agg["total"] == 3
        assert agg["reachable"] == 2
        assert agg["intake_candidates"] == 1
        assert agg["needs_review"] == 1
        assert agg["circuit"] == 1
        assert agg["last_run"] == "2026-07-16T10:00:00+00:00"

    @pytest.mark.smoke
    def test_top_items(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert len(agg["top_items"]) == 3  # tutti e 3 hanno intake_score
        assert agg["top_items"][0]["name"] == "test-dataset-2"
        assert agg["top_items"][0]["score"] == 80.0

    @pytest.mark.smoke
    def test_problematic(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert len(agg["problematic"]) >= 1
        assert agg["problematic"][0]["item_name"] == "test-dataset-3"


class TestComputeFormatoAperto:
    @pytest.mark.smoke
    def test_from_source_check(self):
        res = compute_formato_aperto(_SAMPLE_RESULTS, None)
        # 1 CSV (aperto) + 1 JSON (aperto) + 1 XLSX (chiuso) = 2/3 aperti ≈ 66.7%
        assert res["fonte"] == "source_check"
        assert res["score"] == 55.0  # >= 50% → 55
        assert res["perc_aperto"] == pytest.approx(66.7, rel=0.1)

    @pytest.mark.smoke
    def test_from_inventory_fallback(self):
        res = compute_formato_aperto([], _SAMPLE_ROWS)
        assert res["fonte"] == "inventory"
        # CSV(1) + JSON(1) su 3 = 66.7%
        assert res["score"] == 55.0

    @pytest.mark.smoke
    def test_empty(self):
        res = compute_formato_aperto([], [])
        assert res["fonte"] == "missing"
        assert res["score"] == 0.0


class TestComputeOperationalVerdict:
    @pytest.mark.smoke
    def test_stable(self):
        v = compute_operational_verdict(
            {"status": "GREEN"},
            {"delta": 0},
            {"coverage_pct": 100},
        )
        assert v["label"] == "STABLE"
        assert "all_green" in v["triggers"]

    @pytest.mark.smoke
    def test_down(self):
        v = compute_operational_verdict(
            {"status": "RED"},
            {"delta": 0},
            {"coverage_pct": 100},
        )
        assert v["label"] == "DOWN"
        assert v["next_action"] == "investigate downtime"

    @pytest.mark.smoke
    def test_inventory_changed(self):
        v = compute_operational_verdict(
            {"status": "GREEN"},
            {"delta": 5},
            {"coverage_pct": 100},
        )
        assert v["label"] == "INVENTORY_CHANGED"
        assert v["next_action"] == "review inventory changes"

    @pytest.mark.smoke
    def test_stale(self):
        v = compute_operational_verdict(
            {"status": "GREEN"},
            {"delta": 0, "freshness_hours": 200},
            {"coverage_pct": 100},
        )
        assert v["label"] == "STALE"
        assert v["next_action"] == "refresh inventory"

    @pytest.mark.smoke
    def test_partial(self):
        v = compute_operational_verdict(
            {"status": "GREEN"},
            {"delta": 0},
            {"coverage_pct": 30},
        )
        assert v["label"] == "PARTIALLY_SCOPED"
        assert v["next_action"] == "complete source-check"


class TestBuildReport:
    @pytest.mark.smoke
    def test_minimal(self):
        """Report con soli dati essenziali (nessun radar, inventory vuoto)."""
        report = build_report(
            source_id="test-source",
            cfg=_SAMPLE_CFG,
            radar_result=None,
            rows=[],
            captured_at=None,
            results=[],
        )
        assert report["source_id"] == "test-source"
        assert report["report_version"] == 1
        assert report["identity"]["protocol"] == "ckan"
        assert report.get("health") is None  # no radar → omesso dal dict
        assert report["inventory"]["total_items"] == 0
        assert report["source_check"]["total_scored"] == 0
        assert report["datasets_in_use"] == [{"slug": "test_dataset", "status": "published"}]
        assert report["operational_verdict"]["label"] == "STABLE"

    @pytest.mark.smoke
    def test_with_data(self):
        """Report con dati reali radar, inventory e source-check."""
        report = build_report(
            source_id="test-source",
            cfg=_SAMPLE_CFG,
            radar_result={
                "status": "GREEN",
                "http_code": "200",
                "note": None,
                "ssl_fallback_used": False,
            },
            rows=_SAMPLE_ROWS,
            captured_at="2026-07-16T12:00:00+00:00",
            results=_SAMPLE_RESULTS,
        )
        assert report["health"]["radar_status"] == "GREEN"
        assert report["inventory"]["total_items"] == 3
        assert report["inventory"]["delta"] == 0  # 3 items, baseline = 3
        assert report["inventory"]["formats"]["CSV"] == 1
        assert report["inventory"]["years_range"] == [2020, 2021]
        assert report["source_check"]["total_scored"] == 3
        assert report["source_check"]["intake_candidates"] == 1
        assert report["source_check"]["formato_aperto"]["fonte"] == "source_check"
        assert report["operational_verdict"]["label"] == "STABLE"

    @pytest.mark.smoke
    def test_timing_filtered(self):
        """timing deve filtrare valori stringa ('skip')."""
        report = build_report(
            source_id="test-source",
            cfg=_SAMPLE_CFG,
            radar_result=None,
            rows=[],
            captured_at=None,
            results=[],
            timing={"RADAR": "skip", "TOTALE": 1.5},
        )
        assert "RADAR" not in report.get("timing", {})
        assert report.get("timing", {}).get("TOTALE") == 1.5
