"""Tests per bulk_source_check: regole non ovvie, edge case, bug già visti."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from bulk_source_check import (
    _infer_granularity,
    _infer_years,
    _intake_score,
)
from collectors.ckan import _ckan_api_base


# ── _infer_granularity ────────────────────────────────────────────────────────

class TestInferGranularity:
    def test_comune_wins_over_regione(self):
        # precedenza: comune > regione — ordine in _GRAN_PATTERNS è load-bearing
        assert _infer_granularity("comuni della regione Lombardia") == "comune"

    def test_provincia_wins_over_nazionale(self):
        assert _infer_granularity("dati provinciali italiani") == "provincia"

    def test_regione_not_matched_by_regional(self):
        # "regional" in inglese → nazionale, non regione (bug fix)
        assert _infer_granularity("regional statistics") == "nazionale"

    def test_regione_by_name(self):
        assert _infer_granularity("dati Lombardia 2022") == "regione"

    def test_europeo(self):
        assert _infer_granularity("indicatori europei UE") == "europeo"

    def test_non_determinato(self):
        assert _infer_granularity("dataset generico senza territorio") == "non_determinato"

    def test_empty_string(self):
        assert _infer_granularity("") == "non_determinato"


# ── _infer_years ──────────────────────────────────────────────────────────────

class TestInferYears:
    def test_single_year(self):
        assert _infer_years("dati 2022") == (2022, 2022)

    def test_range(self):
        assert _infer_years("copertura 2015-2023") == (2015, 2023)

    def test_no_partial_match_from_range(self):
        # "2013-2014" non deve estrarre "20" come anno separato (bug fix regex)
        ymin, ymax = _infer_years("periodo 2013-2014")
        assert ymin == 2013
        assert ymax == 2014

    def test_no_false_year_from_short_number(self):
        # "20" da soli non devono matchare
        assert _infer_years("20 comuni") == (None, None)

    def test_no_years(self):
        assert _infer_years("nessuna data qui") == (None, None)

    def test_future_year_excluded(self):
        # anni > 2029 non matchati dal pattern 20[012]\d
        assert _infer_years("proiezioni 2035") == (None, None)


# ── _intake_score ─────────────────────────────────────────────────────────────

class TestIntakeScore:
    def test_nan_format_does_not_crash(self):
        # bug già visto: float('nan') passato come resource_format crashava
        import math
        score, candidate = _intake_score(
            granularity="comune",
            year_min=2015,
            year_max=2022,
            reachable=True,
            resource_format=float("nan"),  # type: ignore[arg-type]
            enrich_method="ckan_package_show",
            needs_review=False,
        )
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_none_format_does_not_crash(self):
        score, _ = _intake_score("comune", 2015, 2022, True, None, "ckan_package_show", False)
        assert isinstance(score, int)

    def test_high_score_comune_long_span(self):
        score, candidate = _intake_score("comune", 2000, 2023, True, "CSV", "ckan_package_show", False)
        assert score >= 80
        assert candidate is True

    def test_no_candidate_if_needs_review(self):
        _, candidate = _intake_score("comune", 2000, 2023, True, "CSV", "ckan_package_show", True)
        assert candidate is False

    def test_score_capped_at_100(self):
        score, _ = _intake_score("comune", 1990, 2024, True, "CSV", "ckan_package_show", False)
        assert score <= 100

    def test_score_floor_at_zero(self):
        score, _ = _intake_score("non_determinato", None, None, False, None, "none", True)
        assert score >= 0


# ── _ckan_api_base ────────────────────────────────────────────────────────────

class TestCkanApiBase:
    def test_standard_endpoint(self):
        url = "https://dati.consip.it/api/3/action/package_list?limit=1"
        assert _ckan_api_base(url) == "https://dati.consip.it/api/3/action"

    def test_inps_nonstandard_endpoint(self):
        # caso reale: INPS usa /odapi/ invece di /api/3/action/
        url = "https://serviziweb2.inps.it/odapi/package_list?limit=1"
        assert _ckan_api_base(url) == "https://serviziweb2.inps.it/odapi"

    def test_package_search_endpoint(self):
        url = "https://example.org/api/3/action/package_search?rows=1"
        assert _ckan_api_base(url) == "https://example.org/api/3/action"

    def test_empty_string_returns_none(self):
        assert _ckan_api_base("") is None

    def test_none_returns_none(self):
        assert _ckan_api_base(None) is None  # type: ignore[arg-type]
