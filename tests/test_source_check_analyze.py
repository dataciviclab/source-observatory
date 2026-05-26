"""Test scripts/source_check_analyze.py — logica di analisi pura."""

from __future__ import annotations

import pandas as pd
import pytest

from source_check_analyze import (
    _fallback_infer,
    _finalize_scores,
    _intake_score,
    _normalize_format,
    _parse_ckan_package,
)

pytestmark = pytest.mark.pure_unit


class TestParseCkanPackage:
    def test_empty_package(self):
        result = _parse_ckan_package({})
        assert result["enriched_title"] is None
        assert result["granularity"] is not None

    def test_tags_and_groups(self):
        pkg = {
            "title": "Test",
            "tags": [{"name": "sanità"}, {"name": "regioni"}],
            "groups": [{"display_name": "Salute"}],
            "resources": [],
            "notes": "Dati sanitari regionali",
        }
        result = _parse_ckan_package(pkg)
        assert "sanità" in result["enriched_tags"]
        assert "regioni" in result["enriched_tags"]
        assert result["resource_url"] is None
        assert result["granularity"] is not None

    def test_resource_prefers_direct_url(self):
        pkg = {
            "resources": [
                {"url": "https://example.gov.it/api/3/action/package_show?id=123"},
                {"url": "https://example.gov.it/data.csv", "format": "CSV"},
            ]
        }
        result = _parse_ckan_package(pkg)
        assert result["resource_url"] == "https://example.gov.it/data.csv"
        assert result["resource_format"] == "CSV"

    def test_resource_fallback_to_first_http(self):
        pkg = {
            "resources": [
                {"url": "https://example.gov.it/api/page"},
                {"url": "/local/file.pdf"},
            ]
        }
        result = _parse_ckan_package(pkg)
        assert result["resource_url"] == "https://example.gov.it/api/page"

    def test_temporal_from_extras(self):
        pkg = {
            "extras": [
                {"key": "temporal_coverage_from", "value": "2020"},
                {"key": "temporal_coverage_to", "value": "2023"},
            ]
        }
        result = _parse_ckan_package(pkg)
        assert result["year_min"] == 2020
        assert result["year_max"] == 2023

    def test_notes_truncated(self):
        pkg = {"notes": "x" * 1000}
        result = _parse_ckan_package(pkg)
        assert result["enriched_notes"] is not None
        assert len(result["enriched_notes"]) <= 300

    def test_temporal_from_periodo_riferimento(self):
        pkg = {
            "extras": [{"key": "Periodo di riferimento", "value": "2015-2022"}],
            "resources": [],
        }
        result = _parse_ckan_package(pkg)
        assert result["year_min"] == 2015
        assert result["year_max"] == 2022


class TestNormalizeFormat:
    def test_empty(self):
        assert _normalize_format("") == ""

    def test_none(self):
        assert _normalize_format(None) == ""  # type: ignore[arg-type]

    def test_csv(self):
        assert _normalize_format("CSV") == "CSV"

    def test_csv_lowercase(self):
        assert _normalize_format("csv") == "CSV"

    def test_csv_substring(self):
        assert _normalize_format("text/csv") == "CSV"

    def test_xlsx(self):
        assert _normalize_format("XLSX") == "XLSX"

    def test_pdf(self):
        assert _normalize_format("application/pdf") == "PDF"

    def test_unknown(self):
        assert _normalize_format("application/octet-stream") == ""


class TestIntakeScore:
    def test_baseline(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format="CSV",
            enrich_method="ckan_package_show", needs_review=False,
        )
        assert score >= 50
        assert candidate is True

    def test_not_reachable(self):
        score, candidate = _intake_score(
            granularity="non_determinato", year_min=None, year_max=None,
            reachable=False, resource_format=None,
            enrich_method="none", needs_review=True,
        )
        assert score == 0
        assert candidate is False

    def test_single_year(self):
        score, candidate = _intake_score(
            granularity="comune", year_min=2020, year_max=None,
            reachable=True, resource_format="CSV",
            enrich_method="none", needs_review=False,
        )
        assert score > 0

    def test_stale_source(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format="CSV",
            enrich_method="ckan_package_show", needs_review=False,
            source_status="stale",
        )
        # stale sottrae 10 e forza needs_review=True → candidate=False
        assert candidate is False

    def test_robust_read(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format="CSV",
            enrich_method="ckan_package_show", needs_review=False,
            robust_read_suggested=True,
        )
        assert candidate is False  # needs_review forced

    def test_format_from_extension(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format=".csv",
            enrich_method="none", needs_review=False,
        )
        assert score > 0

    def test_format_non_matching_extension_returns_empty(self):
        assert _normalize_format("application/octet-stream") == ""

    def test_format_with_long_dotted_string_maps_to_ext(self):
        """Formato come 'application/vnd.ms-excel.sheet.binary' entra nel branch
        di estrazione estensione (dot + len > 6) ma .binary non e' in valid list."""
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format="application/vnd.ms-excel.sheet.binary",
            enrich_method="none", needs_review=False,
        )
        assert score > 0  # format non riconosciuto ma score arriva da altri fattori

    def test_intake_score_single_mapping_col(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format=None,
            enrich_method="none", needs_review=False,
            mapping_suggestions='{"a": "int"}',
        )
        assert score > 0

    def test_intake_score_invalid_mapping_json(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format=None,
            enrich_method="none", needs_review=False,
            mapping_suggestions="not valid json",
        )
        assert score > 0  # gracefully ignored

    def test_encoding_signal(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format="CSV",
            enrich_method="none", needs_review=False,
            encoding_suggested="utf-8",
        )
        assert score > 0

    def test_score_capped_at_100(self):
        score, candidate = _intake_score(
            granularity="comune", year_min=2000, year_max=2024,
            reachable=True, resource_format="CSV",
            enrich_method="ckan_package_show", needs_review=False,
            encoding_suggested="utf-8", delim_suggested=",",
            mapping_suggestions='{"col1": "int", "col2": "str"}',
        )
        assert score <= 100

    def test_mapping_suggestions_gives_bonus(self):
        score, candidate = _intake_score(
            granularity="regione", year_min=2010, year_max=2020,
            reachable=True, resource_format=None,
            enrich_method="none", needs_review=False,
            mapping_suggestions='{"a": "int", "b": "str"}',
        )
        assert score > 0


class TestFinalizeScores:
    def test_finalize_adds_score(self):
        result = _finalize_scores({"granularity": "regione", "reachable": True, "needs_review": False})
        assert "intake_score" in result
        assert "intake_candidate" in result
        assert isinstance(result["intake_score"], int)
        assert isinstance(result["intake_candidate"], bool)


class TestFallbackInfer:
    def test_fallback_from_title_and_tags(self):
        row = pd.Series({"title": "Bilancio regionale", "tags": "finanza", "notes_excerpt": None})
        granularity, ymin, ymax = _fallback_infer(row)
        assert granularity is not None
