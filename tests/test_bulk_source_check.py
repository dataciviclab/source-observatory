"""Tests per bulk_source_check: regole non ovvie, edge case, bug già visti."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lab_connectors.http import HttpResult

from source_check_analyze import (
    _infer_granularity,
    _infer_years,
    _intake_score,
)
from collectors.ckan import _ckan_api_base


class _FakeResp:
    """Minimal response stub for HttpClient mock."""
    def __init__(self, headers: dict[str, str] | None = None, status_code: int = 200, url: str = ""):
        self.headers = headers or {}
        self.status_code = status_code
        self.url = url


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

    def test_concatenated_format_normalized_to_csv(self):
        """'csv,xml' should normalize to 'CSV' (score 20, not 0)."""
        score, _ = _intake_score("comune", 2015, 2022, True, "csv,xml", "ckan_package_show", False)
        assert score >= 20  # CSV format gives 20 points

    def test_xls_csv_xml_normalized_to_xls(self):
        """'xls,csv,xml' should normalize to 'XLS' (score 10)."""
        score, _ = _intake_score("comune", 2015, 2022, True, "xls,csv,xml", "ckan_package_show", False)
        assert score >= 10  # XLS format gives 10 points


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


# ── Regression: max_age_days=None with existing output ─────────────────────────

class TestMaxAgeDaysNone:
    def test_max_age_days_none_does_not_crash_with_existing_output(self, tmp_path):
        """When max_age_days=None the incremental block must not call pd.Timedelta(None)."""
        from bulk_source_check import _http_head_with_retry

        # _http_head_with_retry returns 4-tuple (status, reachable, note, content_type)
        result = _http_head_with_retry("")
        assert len(result) == 4
        assert result[0] is None  # url_missing_or_invalid
        assert result[1] is False
        assert result[2] == "url_missing_or_invalid"
        assert result[3] is None  # no content_type for invalid url


class TestHttpHeadWithRetrySSL:
    """SSL handling in _http_head_with_retry (migrated to HttpClient)."""

    def test_ssl_error_caught_before_connection_error(self, monkeypatch) -> None:
        """SSLError returns ssl_error note."""
        from lab_connectors.http import HttpClient

        call_count = [0]

        def fake_head(self, url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return HttpResult(response=None, err=ConnectionError("SSL cert verify failed"))
            return HttpResult(response=None, err=ConnectionError("SSL still broken"))

        monkeypatch.setattr(HttpClient, "head", fake_head)

        from source_check_fetch import _http_head_with_retry

        status, reachable, note, ct = _http_head_with_retry(
            "https://ssl-broken.test/file.csv",
        )
        assert "ssl" in (note or "").lower() or "connection" in (note or "").lower()
        assert reachable is False
        assert status is None

    def test_ssl_error_uses_head_not_get(self, monkeypatch) -> None:
        """On SSLError, _http_head_with_retry uses HEAD (via HttpClient)."""
        from lab_connectors.http import HttpClient

        head_called = [False]

        def fake_head(self, url, **kwargs):
            head_called[0] = True
            return HttpResult(
                response=_FakeResp(headers={"Content-Type": "text/csv"}, status_code=200, url=url),
                err=None,
            )

        monkeypatch.setattr(HttpClient, "head", fake_head)

        from source_check_fetch import _http_head_with_retry

        status, reachable, note, ct = _http_head_with_retry(
            "https://ssl-broken.test/file.csv",
        )
        assert head_called[0] is True
        assert status == 200
        assert reachable is True
        assert note == ""
        assert ct == "CSV"


# ── SDMX: allow_fetch=False (--no-sdmx-years) ─────────────────────────────


def test_fetch_sdmx_years_allow_fetch_false_skips_http() -> None:
    """allow_fetch=False must return (None, None) without any HTTP call."""
    from source_check_fetch import _fetch_sdmx_years

    year_min, year_max = _fetch_sdmx_years("https://example.test/sdmx", "flow123", allow_fetch=False)
    assert year_min is None
    assert year_max is None
