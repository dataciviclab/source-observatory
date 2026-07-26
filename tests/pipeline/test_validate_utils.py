"""
Test validate utilities with real URLs from inventory.

Tests cover:
  - URL selection (pick best CSV per group)
  - Reachability probe (HEAD)
  - CSV schema sniffing
"""

from __future__ import annotations

import pytest

from scripts._constants import format_score as _format_score
from scripts.collectors._validate_base import (
    pick_best_url,
    probe_reachability,
    sniff_csv_schema,
)
from scripts.collectors._validate_base import (
    validate_tabular_group as validate_group,
)

pytestmark = pytest.mark.pure_unit

# ── Unit: format scoring ──────────────────────────────────────────────────────


class TestFormatScore:
    def test_csv_scores_10(self):
        assert _format_score("csv") == 10
        assert _format_score("CSV") == 10
        assert _format_score("csv,zip") == 10
        assert _format_score("csv,xml") == 10

    def test_json_scores_9(self):
        assert _format_score("json") == 9

    def test_xml_scores_7(self):
        assert _format_score("xml") == 7

    def test_zip_scores_3(self):
        assert _format_score("zip") == 3
        assert _format_score("ZIP") == 3

    def test_none_scores_0(self):
        assert _format_score(None) == 0

    def test_unknown_scores_1(self):
        assert _format_score("pdf") == 1


# ── Unit: pick_best_url ───────────────────────────────────────────────────────


class TestPickBestURL:
    def test_pick_csv_over_zip(self):
        items = [
            {
                "distribution_url": "http://example.com/data.zip",
                "format": "zip",
                "year_signal": 2024,
            },
            {
                "distribution_url": "http://example.com/data.csv",
                "format": "csv",
                "year_signal": 2024,
            },
        ]
        best = pick_best_url(items)
        assert best is not None
        assert best["format"] == "csv"

    def test_pick_recent_year(self):
        items = [
            {
                "distribution_url": "http://example.com/data_2022.csv",
                "format": "csv",
                "year_signal": 2022,
            },
            {
                "distribution_url": "http://example.com/data_2024.csv",
                "format": "csv",
                "year_signal": 2024,
            },
        ]
        best = pick_best_url(items)
        assert best is not None
        assert "2024" in best["distribution_url"]

    def test_empty_items_returns_none(self):
        assert pick_best_url([]) is None

    def test_items_without_url_returns_none(self):
        items = [{"format": "csv", "year_signal": 2024}]
        assert pick_best_url(items) is None


# ── Integration: reachability probe (REAL URLs) ──────────────────────────────


class TestProbeReachability:
    def test_reachable_url(self):
        """A known-good CSV from ACI."""
        result = probe_reachability(
            "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2025.csv?d=1615465800"
        )
        assert result["reachable"] is True
        assert result["status_code"] == 200

    def test_404_url(self):
        result = probe_reachability("https://httpstat.us/404")
        assert result["reachable"] is False

    def test_invalid_url(self):
        result = probe_reachability("https://this-domain-does-not-exist-12345.com/data.csv")
        assert result["reachable"] is False
        assert result["error"] is not None


# ── Integration: CSV sniffing (REAL CSV) ─────────────────────────────────────


class TestSniffCSVSchema:
    def test_real_csv_from_mef(self):
        """MEF IRPEF CSV — should have columns and data."""
        result = sniff_csv_schema(
            "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2025.csv?d=1615465800"
        )
        assert result["error"] is None, f"Sniff error: {result['error']}"
        assert len(result["columns"]) > 0, "Should have columns"
        assert result["num_columns"] > 0
        assert result["delimiter"] is not None

    def test_binary_url_returns_no_columns(self):
        """ZIP file — should return error or empty columns."""
        result = sniff_csv_schema(
            "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/Redditi_e_principali_variabili_IRPEF_su_base_comunale_CSV_2024.zip?d=1615465800"
        )
        # ZIP is not CSV, so parse will fail gracefully
        assert result["num_columns"] == 0 or result["error"] is not None

    def test_404_url_returns_error(self):
        result = sniff_csv_schema("https://httpstat.us/404")
        assert result["error"] is not None


# ── Integration: validate_group (END-TO-END) ─────────────────────────────────


class TestValidateGroup:
    def test_validate_mef_irpef_group(self):
        """Validate a real MEF IRPEF group (REG_tipo_reddito)."""
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2025.csv?d=1615465800",
                "format": "csv",
                "year_signal": 2025,
            },
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2024.csv?d=1615465800",
                "format": "csv",
                "year_signal": 2024,
            },
        ]
        result = validate_group(items)
        assert result["reachable"] is True
        assert result["url"] is not None
        assert "2025" in result["url"]  # picks most recent year

    def test_validate_csv_with_sniff(self):
        """Full validation with CSV sniff on real data."""
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/REG_tipo_reddito_2025.csv?d=1615465800",
                "format": "csv",
                "year_signal": 2025,
            }
        ]
        result = validate_group(items)
        assert result["reachable"] is True
        if result.get("sniff_error") is None:
            assert len(result.get("columns", [])) > 0
            assert result.get("num_columns", 0) > 0

    def test_validate_no_url_returns_error(self):
        items = [{"dataset_group": "test/no-url", "source_id": "test", "format": "csv"}]
        result = validate_group(items)
        assert result["reachable"] is False
        assert result["error"] is not None

    def test_validate_non_csv_format(self):
        """ZIP format — should skip probe and mark non-CSV."""
        items = [
            {
                "dataset_group": "test/zip",
                "source_id": "test",
                "distribution_url": "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/contenuti/Redditi_e_principali_variabili_IRPEF_su_base_comunale_CSV_2024.zip?d=1615465800",
                "format": "zip",
                "year_signal": 2024,
            }
        ]
        result = validate_group(items)
        # Non-CSV: skips HEAD, reachable=None (non verificato)
        assert result["reachable"] is None
        assert "note" in result
        assert "Non-CSV" in result["note"]
