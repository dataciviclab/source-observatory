"""Smoke test per scripts/engine/report.py: aggregazioni, build_report, verdict."""

from __future__ import annotations

import pytest

from scripts.engine.report import (
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
        "dataset_group": "src/group1",
        "source_id": "test",
        "reachable": True,
        "readiness_score": 3,
        "format": "csv",
        "num_columns": 8,
        "dataset_group_year_min": 2020,
        "dataset_group_year_max": 2024,
        "url": "https://example.com/data1.csv",
    },
    {
        "dataset_group": "src/group2",
        "source_id": "test",
        "reachable": True,
        "readiness_score": 2,
        "format": "csv",
        "num_columns": 5,
        "dataset_group_year_min": 2021,
        "dataset_group_year_max": 2021,
        "url": "https://example.com/data2.csv",
    },
    {
        "dataset_group": "src/group3",
        "source_id": "test",
        "reachable": False,
        "readiness_score": 0,
        "format": "zip",
        "num_columns": 0,
        "dataset_group_year_min": None,
        "dataset_group_year_max": None,
        "url": "https://example.com/data3.zip",
        "error": "HTTP 404",
    },
]


# ── aggregate_inventory_rows ─────────────────────────────────────────────────


class TestAggregateInventoryRows:
    @pytest.mark.smoke
    def test_empty(self):
        agg = aggregate_inventory_rows([])
        assert agg == {"formats": {}, "years_range": None, "organizations": []}

    @pytest.mark.smoke
    def test_basic(self):
        agg = aggregate_inventory_rows(_SAMPLE_ROWS)
        assert agg["formats"] == {"CSV": 1, "JSON": 1, "PDF": 1}
        assert agg["years_range"] == [2020, 2021]
        assert set(agg["organizations"]) == {"Test Org", "Other Org"}

    @pytest.mark.smoke
    def test_handles_nan_format(self):
        rows = [{"item_id": "x", "format": None}]
        agg = aggregate_inventory_rows(rows)
        assert agg["formats"] == {"?": 1}


# ── aggregate_source_check (nuovo schema validated.parquet) ──────────────────


class TestAggregateSourceCheck:
    @pytest.mark.smoke
    def test_empty(self):
        agg = aggregate_source_check([])
        assert agg["total"] == 0

    @pytest.mark.smoke
    def test_basic(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert agg["total"] == 3
        assert agg["reachable"] == 2
        assert agg["csv_count"] == 2
        assert agg["with_csv_schema"] == 2
        assert agg["avg_readiness"] == pytest.approx(1.7, 0.1)

    @pytest.mark.smoke
    def test_top_items(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert len(agg["top_items"]) == 3
        assert agg["top_items"][0]["score"] == 3  # readiness_score piu' alto

    @pytest.mark.smoke
    def test_problematic(self):
        agg = aggregate_source_check(_SAMPLE_RESULTS)
        assert len(agg["problematic"]) == 1
        assert "404" in agg["problematic"][0]["error"]


class TestAggregateSourceCheckCatalogOnly:
    def test_skipped_rows_excluded_from_formats(self):
        results = [
            {"dataset_group": "a", "validation_skipped": True},
            {"dataset_group": "b", "validation_skipped": True},
            {"dataset_group": "c", "format": "csv", "num_columns": 3, "readiness_score": 9},
        ]
        agg = aggregate_source_check(results)
        assert agg["validation_skipped"] == 2
        assert agg["formats"] == {"csv": 1}
        assert agg["no_year"] == 1


# ── compute_formato_aperto ──────────────────────────────────────────────────


class TestFormatoAperto:
    @pytest.mark.smoke
    def test_from_source_check(self):
        result = compute_formato_aperto(_SAMPLE_RESULTS)
        assert result["total"] == 3
        assert result["fonte"] == "source_check"
        assert result["perc_aperto"] == pytest.approx(66.7)

    @pytest.mark.smoke
    def test_from_inventory_fallback(self):
        result = compute_formato_aperto([], rows=_SAMPLE_ROWS)
        assert result["total"] == 3
        assert result["perc_aperto"] == pytest.approx(66.7)

    @pytest.mark.smoke
    def test_nan_resource_format_falls_back(self):
        results = [{"reachable": True, "resource_format": float("nan"), "format": "csv"}]
        result = compute_formato_aperto(results)
        assert result["perc_aperto"] == 100.0


# ── compute_operational_verdict ──────────────────────────────────────────────


class TestOperationalVerdict:
    @pytest.mark.smoke
    def test_empty(self):
        v = compute_operational_verdict({}, {"total_items": 0}, {"total_scored": 0})
        assert v["label"] == "NO_DATA"

    def test_health_only(self):
        v = compute_operational_verdict(
            {}, {"total_items": 0}, {"total_scored": 0}, observation_mode="radar-only"
        )
        assert v["label"] == "HEALTH_ONLY"

    @pytest.mark.smoke
    def test_stable(self):
        v = compute_operational_verdict(
            {},
            {"total_items": 10},
            {"total_scored": 10, "reachable": 10, "coverage_pct": 100.0},
        )
        assert v["score"] == "stable"

    @pytest.mark.smoke
    def test_down(self):
        radar = {"status": "RED"}
        v = compute_operational_verdict(radar, {"total_items": 10}, {"total_scored": 10})
        assert v["label"] == "DOWN"

    @pytest.mark.smoke
    def test_inventory_changed(self):
        inventory = {"total_items": 50, "delta": 10}
        v = compute_operational_verdict(
            {}, inventory, {"total_scored": 50, "reachable": 50, "coverage_pct": 100.0}
        )
        assert v["label"] == "INVENTORY_CHANGED"

    def test_unreachable(self):
        v = compute_operational_verdict(
            {}, {"total_items": 10}, {"total_scored": 10, "reachable": 2, "coverage_pct": 100.0}
        )
        assert v["label"] == "UNREACHABLE"

    def test_catalog_only(self):
        v = compute_operational_verdict(
            {},
            {"total_items": 10},
            {"total_scored": 10, "reachable": 0, "validation_skipped": 10},
        )
        assert v["label"] == "CATALOG_ONLY"

    def test_catalog_only_inventory_changed(self):
        v = compute_operational_verdict(
            {},
            {"total_items": 10, "delta": 10},
            {"total_scored": 10, "reachable": 0, "validation_skipped": 10},
        )
        assert v["label"] == "INVENTORY_CHANGED"
        assert "catalog_only" in v["triggers"]

    def test_not_probeable(self):
        v = compute_operational_verdict(
            {},
            {"total_items": 27},
            {"total_scored": 27, "reachable": 0, "not_checked_non_csv": 27, "coverage_pct": 100.0},
        )
        assert v["label"] == "NOT_PROBEABLE"

    def test_stale_rows(self):
        v = compute_operational_verdict(
            {},
            {"total_items": 10, "stale_items": 3},
            {"total_scored": 10, "reachable": 10, "coverage_pct": 100.0},
        )
        assert v["label"] == "STALE"


# ── build_report (integration smoke) ─────────────────────────────────────────


class TestBuildReport:
    """Test minimale che build_report non crashi con dati realistici."""

    def _make_source_check(self) -> list[dict]:
        return [
            {
                "dataset_group": f"test_src/ds{i}",
                "source_id": "test_src",
                "reachable": True,
                "readiness_score": 3,
                "format": "csv",
                "num_columns": 10,
                "dataset_group_year_min": 2020,
                "dataset_group_year_max": 2024,
            }
            for i in range(5)
        ]

    @pytest.mark.smoke
    def test_minimal(self):
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": "1", "format": "CSV", "organization": "Test"}],
            captured_at="2026-07-16T10:00:00+00:00",
            results=[],
        )
        assert report["source_id"] == "test_src"
        assert report["inventory"]["total_items"] == 1

    @pytest.mark.smoke
    def test_with_data(self):
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": "1", "format": "CSV", "organization": "Test"}],
            captured_at="2026-07-16T10:00:00+00:00",
            results=self._make_source_check(),
        )
        assert report["source_check"]["total_scored"] == 5
        assert report["source_check"]["reachable"] == 5
        assert report["source_check"]["avg_readiness"] == 3.0

    @pytest.mark.smoke
    def test_coverage_uses_logical_groups(self):
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": "1", "format": "CSV", "organization": "Test"}],
            captured_at="2026-07-16T10:00:00+00:00",
            results=self._make_source_check(),
            total_groups=10,
        )
        assert report["source_check"]["coverage_pct"] == 50.0
        assert report["source_check"]["reachability_pct"] == 100.0

    @pytest.mark.smoke
    def test_catalog_only_report(self):
        results = [
            {"dataset_group": f"test_src/ds{i}", "validation_skipped": True} for i in range(3)
        ]
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": str(i)} for i in range(3)],
            captured_at=None,
            results=results,
            total_groups=3,
        )
        assert report["source_check"]["catalog_only"] is True
        assert report["source_check"]["probeable_items"] == 0
        assert report["operational_verdict"]["label"] == "CATALOG_ONLY"

    @pytest.mark.smoke
    def test_not_probeable_report(self):
        results = [
            {"dataset_group": f"test_src/ds{i}", "reachable": None, "format": "xlsx,json"}
            for i in range(3)
        ]
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": str(i)} for i in range(3)],
            captured_at=None,
            results=results,
            total_groups=3,
        )
        assert report["source_check"]["probeable_items"] == 0
        assert report["source_check"]["reachability_pct"] is None
        assert report["operational_verdict"]["label"] == "NOT_PROBEABLE"

    @pytest.mark.smoke
    def test_timing_filtered(self):
        recent = self._make_source_check()
        report = build_report(
            source_id="test_src",
            cfg={"source_kind": "catalog", "protocol": "html", "base_url": "https://example.com"},
            radar_result={},
            rows=[{"item_id": "1", "format": "CSV", "organization": "Test"}],
            captured_at="2026-07-16T10:00:00+00:00",
            results=recent,
        )
        assert report["source_check"]["total_scored"] == 5


class TestAggregateBlocked:
    def test_blocked_excluded_from_not_checked(self):
        results = [
            {"dataset_group": "a", "reachable": None, "blocked": True},
            {"dataset_group": "b", "reachable": None, "format": "zip"},
            {"dataset_group": "c", "reachable": True, "num_columns": 3},
        ]
        agg = aggregate_source_check(results)
        assert agg["blocked_items"] == 1
        assert agg["not_checked_non_csv"] == 1
        assert agg["reachable"] == 1

    def test_nan_blocked_is_not_counted(self):
        """NaN arriva dal parquet per le righe senza colonna: non è un blocco."""
        results = [{"dataset_group": "a", "reachable": None, "blocked": float("nan")}]
        agg = aggregate_source_check(results)
        assert agg["blocked_items"] == 0
        assert agg["not_checked_non_csv"] == 1


class TestVerdictBlocked:
    def test_all_blocked_is_unreachable_not_not_probeable(self):
        v = compute_operational_verdict(
            {},
            {},
            {
                "total_scored": 10,
                "reachable": 0,
                "not_checked_non_csv": 0,
                "blocked_items": 10,
                "validation_skipped": 0,
            },
        )
        assert v["label"] == "UNREACHABLE"
        assert "blocked" in v["triggers"]

    def test_blocked_with_healthy_rest_is_stable(self):
        v = compute_operational_verdict(
            {},
            {},
            {
                "total_scored": 10,
                "reachable": 5,
                "not_checked_non_csv": 0,
                "blocked_items": 5,
                "validation_skipped": 0,
            },
        )
        assert v["label"] == "STABLE"
