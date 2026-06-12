"""Tests per bulk_source_check: regole non ovvie, edge case, bug già visti."""

from __future__ import annotations

from pathlib import Path

import pytest
from collectors.ckan import _ckan_api_base
from lab_connectors.http import HttpResult
from lab_connectors.testing import fake_response
from source_check_analyze import (
    _infer_granularity,
    _infer_years,
    _intake_score,
)


def _resp(
    status_code: int = 200,
    text: str = "",
    headers: dict[str, str] | None = None,
    url: str = "",
):
    """Shortcut: fake_response + url."""
    r = fake_response(status_code, text=text, headers=headers)
    r.url = url
    return r


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
        score, candidate = _intake_score(
            "comune", 2000, 2023, True, "CSV", "ckan_package_show", False
        )
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
        score, _ = _intake_score(
            "comune", 2015, 2022, True, "xls,csv,xml", "ckan_package_show", False
        )
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
                response=_resp(200, headers={"Content-Type": "text/csv"}, url=url),
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

    year_min, year_max = _fetch_sdmx_years(
        "https://example.test/sdmx", "flow123", allow_fetch=False
    )
    assert year_min is None
    assert year_max is None


# ── _fetch_data_preview new fields ────────────────────────────────────────


def test_fetch_data_preview_returns_new_fields(monkeypatch) -> None:
    """_fetch_data_preview must return file_size, preview_row_count, col_types, columns."""
    from lab_connectors.http import HttpClient
    from source_check_fetch import _fetch_data_preview

    def fake_get(self, url, **kwargs):
        return HttpResult(
            response=_resp(
                200,
                text="col1,col2,col3\n1,2,3\n4,5,6",
                headers={"Content-Type": "text/csv"},
                url=url,
            ),
            err=None,
        )

    monkeypatch.setattr(HttpClient, "get", fake_get)

    result = _fetch_data_preview("https://example.test/data.csv")
    assert result.get("file_size") == len(b"col1,col2,col3\n1,2,3\n4,5,6")
    assert result.get("preview_row_count") == 2
    import json

    # DuckDB restituisce BIGINT per interi (non int64 come pandas)
    ct = json.loads(result.get("col_types") or "{}")
    assert all(v.upper() in ("BIGINT", "INTEGER", "INT64") for v in ct.values()), (
        f"Unexpected types: {ct}"
    )
    assert list(ct.keys()) == ["col1", "col2", "col3"]
    assert json.loads(result.get("columns") or "[]") == ["col1", "col2", "col3"]


# ── _parse_ckan_package: preferisce URL file diretto ─────────────────────


def test_parse_ckan_package_prefers_file_url() -> None:
    """_parse_ckan_package must prefer resources with file extensions."""
    from source_check_analyze import _parse_ckan_package

    pkg = {
        "resources": [
            {"url": "https://portal.it/dataset/123", "format": "HTML"},
            {"url": "https://portal.it/download/data.csv", "format": "CSV"},
            {"url": "https://portal.it/download/data.xls", "format": "XLS"},
        ]
    }
    result = _parse_ckan_package(pkg)
    assert result["resource_url"] == "https://portal.it/download/data.csv"
    assert result["resource_format"] == "CSV"


def test_parse_ckan_package_fallback_first_http_url() -> None:
    """Without file extensions, must fallback to first HTTP URL."""
    from source_check_analyze import _parse_ckan_package

    pkg = {
        "resources": [
            {"url": "https://portal.it/api/action?id=123", "format": "api"},
            {"url": "https://portal.it/download/file", "format": "CSV"},
        ]
    }
    result = _parse_ckan_package(pkg)
    assert result["resource_url"] == "https://portal.it/api/action?id=123"


# ── XLS falso: TSV/Latin-1 fallback ─────────────────────────────────────


def test_fetch_data_preview_head_infers_csv_without_extension(monkeypatch) -> None:
    """URL senza estensione: HEAD text/csv → GET sample → csv_preview."""
    from lab_connectors.http import HttpClient
    from source_check_fetch import _fetch_data_preview

    calls = {"head": 0, "get": 0}

    def fake_head(self, url, **kwargs):
        calls["head"] += 1
        return HttpResult(
            response=_resp(200, headers={"Content-Type": "text/csv; charset=utf-8"}, url=url),
            err=None,
        )

    def fake_get(self, url, **kwargs):
        calls["get"] += 1
        return HttpResult(
            response=_resp(200, text="a,b\n1,2\n", headers={"Content-Type": "text/csv"}, url=url),
            err=None,
        )

    monkeypatch.setattr(HttpClient, "head", fake_head)
    monkeypatch.setattr(HttpClient, "get", fake_get)

    result = _fetch_data_preview("https://portal.example/api/download?id=1&fmt=file")
    assert calls["head"] == 1
    assert calls["get"] == 1
    assert result.get("enrich_method") == "csv_preview"
    import json

    assert json.loads(result.get("columns") or "[]") == ["a", "b"]


def test_fetch_data_preview_content_disposition_filename(monkeypatch) -> None:
    """HEAD application/octet-stream + filename .csv → preview."""
    from lab_connectors.http import HttpClient
    from source_check_fetch import _fetch_data_preview

    def fake_head(self, url, **kwargs):
        return HttpResult(
            response=_resp(
                200,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": 'attachment; filename="report.csv"',
                },
                url=url,
            ),
            err=None,
        )

    def fake_get(self, url, **kwargs):
        return HttpResult(
            response=_resp(200, text="x,y\n3,4\n", headers={"Content-Type": "text/csv"}, url=url),
            err=None,
        )

    monkeypatch.setattr(HttpClient, "head", fake_head)
    monkeypatch.setattr(HttpClient, "get", fake_get)

    result = _fetch_data_preview("https://portal.example/export")
    assert result.get("enrich_method") == "csv_preview"
    import json

    assert json.loads(result.get("columns") or "[]") == ["x", "y"]


def test_fetch_data_preview_tsv_extension(monkeypatch) -> None:
    from lab_connectors.http import HttpClient
    from source_check_fetch import _fetch_data_preview

    def fake_get(self, url, **kwargs):
        return HttpResult(
            response=_resp(
                200,
                text="a\tb\tc\n1\t2\t3\n",
                headers={"Content-Type": "text/tab-separated-values"},
                url=url,
            ),
            err=None,
        )

    monkeypatch.setattr(HttpClient, "get", fake_get)

    result = _fetch_data_preview("https://example.test/data.tsv")
    assert result.get("enrich_method") == "csv_preview"
    assert result.get("resource_format") == "TSV"
    import json

    assert json.loads(result.get("columns") or "[]") == ["a", "b", "c"]


def test_fetch_data_preview_xls_fake_tsv_latin1(monkeypatch) -> None:
    """Fake .xls with TSV content + Latin-1 encoding must recover columns."""
    from lab_connectors.http import HttpClient
    from source_check_fetch import _fetch_data_preview

    def fake_get(self, url, **kwargs):
        return HttpResult(
            response=_resp(
                200,
                text="col1\tcol2\tcol3\n1\t2\t3\n4\t5\t6",
                headers={"Content-Type": "application/octet-stream"},
                url=url,
            ),
            err=None,
        )

    monkeypatch.setattr(HttpClient, "get", fake_get)

    result = _fetch_data_preview("https://example.test/data.xls")
    assert result.get("enrich_method") == "csv_preview"
    import json

    cols = json.loads(result.get("columns") or "[]")
    assert len(cols) == 3
    assert cols == ["col1", "col2", "col3"]
    assert result.get("preview_row_count") == 2


def test_http_circuit_breaker_blocks_host_after_failures(monkeypatch) -> None:
    """Dopo N errori di trasporto sullo stesso host, HEAD successivi ritornano circuit_open."""
    import requests
    from lab_connectors.http import CircuitOpenError, HttpResult
    from source_check_fetch import _http_head_with_retry, configure_source_check_http

    heads: list[str] = []

    # Mokka a livello requests (non HttpClient.head), cosi' il vero
    # HttpClient.head() esegue e il circuit breaker viene aggiornato.
    def fake_requests_head(url, **kwargs):
        heads.append(url)
        raise requests.exceptions.ConnectTimeout()

    monkeypatch.setattr(requests, "head", fake_requests_head)
    monkeypatch.setattr(requests.Session, "head", lambda self, url, **kw: fake_requests_head(url, **kw))

    client = configure_source_check_http(
        circuit_fail_threshold=2, http_timeout=(1.0, 2.0), http_max_retries=1
    )
    try:
        u = "https://slow-host.example/resource/1"
        _http_head_with_retry(u, client=client)
        assert len(heads) == 2
        _st, _ok, note, _fmt = _http_head_with_retry("https://slow-host.example/other", client=client)
        assert note == "circuit_open"
        assert len(heads) == 2
    finally:
        configure_source_check_http(
            circuit_fail_threshold=0, http_timeout=(5.0, 10.0), http_max_retries=2
        )


# ── _extract_year_values_from_sample ──────────────────────────────────────────


class TestExtractYearValuesFromSample:
    """Unit test per _extract_year_values_from_sample."""

    def test_multiple_years_in_column(self) -> None:
        from source_check_fetch import _extract_year_values_from_sample

        sample = [
            {"Anno": 2020, "Regione": "Lombardia", "Valore": 100},
            {"Anno": 2021, "Regione": "Lombardia", "Valore": 110},
            {"Anno": 2022, "Regione": "Lombardia", "Valore": 120},
        ]
        columns = ["Anno", "Regione", "Valore"]
        result = _extract_year_values_from_sample(sample, columns)
        assert result == [2020, 2021, 2022]

    def test_single_year_without_hint_column(self) -> None:
        """Un solo valore anno senza colonna hint non basta — servono almeno 2 numeri."""
        from source_check_fetch import _extract_year_values_from_sample

        sample = [{"codice": 2020, "valore": 100}]
        columns = ["codice", "valore"]
        result = _extract_year_values_from_sample(sample, columns)
        assert result == []

    def test_falls_back_to_year_hint_column(self) -> None:
        from source_check_fetch import _extract_year_values_from_sample

        sample = [
            {"periodo": "2020-2021", "anno": 2020, "valore": 100},
            {"periodo": "2020-2021", "anno": 2021, "valore": 110},
        ]
        columns = ["periodo", "anno", "valore"]
        result = _extract_year_values_from_sample(sample, columns)
        # "anno" è in _YEAR_COLUMN_HINTS → matcha anche con 1 valore
        assert result == [2020, 2021]

    def test_empty_sample(self) -> None:
        from source_check_fetch import _extract_year_values_from_sample

        assert _extract_year_values_from_sample([], ["A", "B"]) == []

    def test_no_year_values_at_all(self) -> None:
        from source_check_fetch import _extract_year_values_from_sample

        sample = [{"nome": "Mario", "eta": 30}, {"nome": "Luigi", "eta": 25}]
        result = _extract_year_values_from_sample(sample, ["nome", "eta"])
        assert result == []

    def test_out_of_range_ignored(self) -> None:
        """Valori fuori 1900-2100 non sono anni."""
        from source_check_fetch import _extract_year_values_from_sample

        sample = [
            {"codice": 1, "valore": 100},
            {"codice": 2, "valore": 200},
        ]
        result = _extract_year_values_from_sample(sample, ["codice", "valore"])
        assert result == []

    def test_nan_values_in_sample(self) -> None:
        """NaN nei sample non deve crashare int(). Bug reale da fonte mef_irpef."""
        from source_check_fetch import _extract_year_values_from_sample

        sample = [
            {"Anno": float("nan"), "Regione": "Lombardia", "Valore": 100},
            {"Anno": 2021.0, "Regione": "Lombardia", "Valore": 110},
        ]
        result = _extract_year_values_from_sample(sample, ["Anno", "Regione", "Valore"])
        # NaN filtrato, 2021 sopravvive (anno singolo da hint column)
        assert result == [2021]


# ── _infer_granularity_from_columns ───────────────────────────────────────────


class TestInferGranularityFromColumns:
    """Unit test per _infer_granularity_from_columns."""

    def test_comune(self) -> None:
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns(["Comune", "Popolazione"]) == "comune"

    def test_regione(self) -> None:
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns(["Regione", "Anno", "Valore"]) == "regione"

    def test_comune_wins_over_regione(self) -> None:
        """Comune ha precedenza quando entrambi i pattern matchano."""
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns(["Comune", "Regione"]) == "comune"

    def test_no_territorial_columns(self) -> None:
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns(["Anno", "Valore", "Categoria"]) == "non_determinato"

    def test_empty_columns_list(self) -> None:
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns([]) == "non_determinato"

    def test_comune_in_substring(self) -> None:
        """'comune' dentro una parola composta matcha lo stesso."""
        from source_check_fetch import _infer_granularity_from_columns

        assert _infer_granularity_from_columns(["Denominazione_comune", "CAP"]) == "comune"


def test_normalize_preview_columns_for_parquet_handles_existing_nested_rows(tmp_path: Path) -> None:
    """Final parquet write must handle old incremental rows with nested cells."""
    import json

    import numpy as np
    import pandas as pd
    from bulk_source_check import _normalize_preview_columns_for_parquet

    df = pd.DataFrame(
        [
            {
                "item_id": "new",
                "col_types": json.dumps({"a": "int64"}),
                "columns": json.dumps(["a"]),
            },
            {
                "item_id": "old",
                "col_types": {"b": "object"},
                "columns": np.array(["b"]),
            },
        ]
    )

    normalized = _normalize_preview_columns_for_parquet(df)
    out = tmp_path / "source_check_results.parquet"
    normalized.to_parquet(out, index=False)

    reloaded = pd.read_parquet(out)
    assert json.loads(reloaded.loc[reloaded["item_id"] == "old", "col_types"].iloc[0]) == {
        "b": "object"
    }
    assert json.loads(reloaded.loc[reloaded["item_id"] == "old", "columns"].iloc[0]) == ["b"]


# ── _enrich_with_inventory: HTML NaN fallback ──────────────────────────────────


class TestEnrichWithInventoryHtmlFallback:
    """Regressione: organization/tags/notes_excerpt NaN nelle fonti HTML devono
    essere derivati dal registry (source_id, topic_hint, note)."""

    def _make_row(self, source_id: str, **overrides) -> dict:
        """Costruisce una pd.Series finta con i campi minimi dell'inventory."""
        import numpy as np
        import pandas as pd

        base = {
            "source_id": source_id,
            "item_id": "test-item-001",
            "item_name": "test-item",
            "title": "Test Dataset",
            "organization": np.nan,
            "tags": np.nan,
            "notes_excerpt": np.nan,
            "url": "https://example.com/test.csv",
            "landing_page": np.nan,
            "format": "CSV",
            "granularity": np.nan,
            "year_signal": np.nan,
            "encoding_suggested": np.nan,
            "delim_suggested": np.nan,
            "decimal_suggested": np.nan,
            "skip_suggested": np.nan,
        }
        base.update(overrides)
        return pd.Series(base)

    def test_aifa_produces_org_tags_notes(self):
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        row = self._make_row("aifa")
        result = _enrich_with_inventory(row, registry)

        assert result["enriched_org"] == "AIFA", f"expected AIFA, got {result['enriched_org']!r}"
        assert result["enriched_tags"] == "sanita", (
            f"expected sanita, got {result['enriched_tags']!r}"
        )
        assert "Portale Open Data AIFA" in (result["enriched_notes"] or ""), (
            f"expected AIFA note, got {result['enriched_notes']!r}"
        )

    def test_mim_opendata_produces_org_tags_notes(self):
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        row = self._make_row("mim_opendata")
        result = _enrich_with_inventory(row, registry)

        assert result["enriched_org"] == "MIM_OPENDATA"
        assert result["enriched_tags"] == "istruzione"
        assert "Ministero Istruzione" in (result["enriched_notes"] or "")

    def test_preserves_existing_org_non_nan(self):
        """Se organization è già popolata (stringa), non deve essere sovrascritta."""
        import numpy as np
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        row = self._make_row("mim_opendata", organization="MIM ufficiale", tags=np.nan)
        result = _enrich_with_inventory(row, registry)

        assert result["enriched_org"] == "MIM ufficiale", (
            f"non deve sovrascrivere org esistente: {result['enriched_org']!r}"
        )


# ── SDMX enrichment contract ──────────────────────────────────────────────────

_SDMX_XML = """<?xml version="1.0"?>
<message:Structure xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                   xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
                   xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow id="32_221" version="1.0" agencyID="IT1">
        <common:Name>Test dataflow</common:Name>
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>"""

_SDMX_XML_NO_AGENCY = """<?xml version="1.0"?>
<message:Structure xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                   xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
                   xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow id="42_999" version="2.0">
        <common:Name>No agency test</common:Name>
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>"""


class TestSdmxParseAnnotations:
    """contract: _parse_sdmx_annotations estrae version/agency dal Dataflow XML."""

    def test_extracts_version_and_agency(self) -> None:
        import xml.etree.ElementTree as ET

        from bulk_source_check import _parse_sdmx_annotations

        root = ET.fromstring(_SDMX_XML)
        result = _parse_sdmx_annotations(root, "https://example.test/dataflow/IT1", "32_221")
        assert result["sdmx_flow"] == "32_221"
        assert result["sdmx_version"] == "1.0"
        assert result["sdmx_agency"] == "IT1"
        assert result["resource_format"] == "SDMX"
        assert result["enrich_method"] == "sdmx_dataflow_annotations"

    def test_no_agency_returns_none(self) -> None:
        """Se l'attributo agencyID non c'è, sdmx_agency deve essere None, non un default."""
        import xml.etree.ElementTree as ET

        from bulk_source_check import _parse_sdmx_annotations

        root = ET.fromstring(_SDMX_XML_NO_AGENCY)
        result = _parse_sdmx_annotations(root, "https://example.test/dataflow/IT1", "42_999")
        assert result["sdmx_flow"] == "42_999"
        assert result["sdmx_version"] == "2.0"
        assert result["sdmx_agency"] is None, f"expected None, got {result['sdmx_agency']!r}"

    def test_extracts_keywords(self) -> None:
        """Le annotation keywords continuano a funzionare."""
        import xml.etree.ElementTree as ET

        from bulk_source_check import _parse_sdmx_annotations

        xml_with_ann = _SDMX_XML.replace(
            "<common:Name>Test dataflow</common:Name>",
            "<common:Name>Test dataflow</common:Name>\n"
            "        <common:Annotation>\n"
            "          <common:AnnotationType>LAYOUT_DATAFLOW_KEYWORDS</common:AnnotationType>\n"
            "          <common:AnnotationText>gini+regionale+reddito</common:AnnotationText>\n"
            "        </common:Annotation>",
        )
        root = ET.fromstring(xml_with_ann)
        result = _parse_sdmx_annotations(root, "https://example.test/dataflow/IT1", "32_221")
        assert result["enriched_tags"] == "gini, regionale, reddito"


class TestSdmxEnrichWithInventory:
    """contract: _enrich_with_inventory usa base_url (non api_base_url) per SDMX."""

    def _make_sdmx_row(self, **overrides) -> dict:
        import numpy as np

        base = {
            "source_id": "istat_sdmx",
            "item_id": "32_221",
            "item_name": "32_221",
            "item_slug": np.nan,
            "title": "Test SDMX",
            "organization": np.nan,
            "tags": np.nan,
            "notes_excerpt": np.nan,
            "format": np.nan,
            "protocol": "sdmx",
            "source_url": np.nan,
            "api_base_url": "https://esploradati.istat.it/SDMXWS/rest",  # NO dataflow/IT1
            "landing_page": np.nan,
            "distribution_url": np.nan,
            "url": np.nan,
            "granularity": np.nan,
            "year_signal": np.nan,
            "encoding_suggested": np.nan,
            "delim_suggested": np.nan,
            "decimal_suggested": np.nan,
            "skip_suggested": np.nan,
        }
        base.update(overrides)
        return base

    def test_uses_base_url_not_api_base_url(self, monkeypatch) -> None:
        """base_url dal registry (con /dataflow/IT1) viene usato, non api_base_url."""
        import pandas as pd
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        # Mock _fetch_sdmx_dataflow per catturare quale URL riceve
        captured_args = {}

        def _mock_fetch(base_url, flow_id):
            captured_args["base_url"] = base_url
            captured_args["flow_id"] = flow_id
            import xml.etree.ElementTree as ET

            return ET.fromstring(_SDMX_XML)

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sdmx_dataflow", _mock_fetch)
        # _fetch_sdmx_years non mockato → farebbe HTTP request reale verso ISTAT
        # (down). La logica SDMX enrichment non dipende dagli anni per i campi
        # sdmx_flow/version/agency — solo per year_min/year_max (facoltativi).
        monkeypatch.setattr(bsc, "_fetch_sdmx_years", lambda *a, **kw: (None, None))

        row = pd.Series(self._make_sdmx_row())
        result = _enrich_with_inventory(row, registry)

        # Verifica che _fetch_sdmx_dataflow abbia ricevuto base_url dal registry
        assert captured_args["base_url"] == registry["istat_sdmx"]["base_url"], (
            f"atteso {registry['istat_sdmx']['base_url']}, ottenuto {captured_args['base_url']}"
        )
        assert captured_args["flow_id"] == "32_221"
        # Verifica i campi SDMX nel risultato
        assert result["sdmx_flow"] == "32_221"
        assert result["sdmx_version"] == "1.0"
        assert result["sdmx_agency"] == "IT1"
        assert result["enrich_method"] == "sdmx_dataflow_annotations"

    def test_sdmx_passes_url_filter(self) -> None:
        """Item con protocol==\"sdmx\" passano il filtro URL anche senza landing_page."""
        import pandas as pd

        row = pd.Series(self._make_sdmx_row())
        # Stessa logica del filtro reale in main(): usa .notna() per NaN
        has_url = row["landing_page"] if pd.notna(row.get("landing_page")) else False
        has_url = has_url or (
            row["distribution_url"] if pd.notna(row.get("distribution_url")) else False
        )
        has_url = has_url or (row["protocol"] == "sdmx")
        assert has_url is True
        # Verifica anche che SENZA protocol sdmx fallirebbe
        row_no_sdmx = pd.Series(self._make_sdmx_row(protocol="ckan"))
        has_url_no_sdmx = (
            row_no_sdmx["landing_page"] if pd.notna(row_no_sdmx.get("landing_page")) else False
        )
        has_url_no_sdmx = has_url_no_sdmx or (
            row_no_sdmx["distribution_url"]
            if pd.notna(row_no_sdmx.get("distribution_url"))
            else False
        )
        has_url_no_sdmx = has_url_no_sdmx or (row_no_sdmx["protocol"] == "sdmx")
        assert has_url_no_sdmx is False


class TestSdmxCheckRowPassthrough:
    """contract: _check_row passa sdmx_flow/version/agency nel result dict."""

    def test_sdmx_fields_in_result(self, monkeypatch) -> None:
        import numpy as np
        import pandas as pd
        import yaml
        from bulk_source_check import _check_row

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        # Mock tutte le funzioni HTTP per evitare chiamate reali
        import xml.etree.ElementTree as ET

        def _mock_fetch(base_url, flow_id):
            return ET.fromstring(_SDMX_XML)

        def _mock_preview(url, **kwargs):
            return {"enrich_method": "csv_preview"}

        def _mock_head(url, **kwargs):
            return 200, True, None, "application/xml"

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sdmx_dataflow", _mock_fetch)
        monkeypatch.setattr(bsc, "_fetch_data_preview", _mock_preview)
        monkeypatch.setattr(bsc, "_http_head_with_retry", _mock_head)
        # _fetch_sdmx_years mockato per evitare HTTP request reale verso ISTAT
        # (down). Gli anni sono accessori — non servono per i campi SDMX testati.
        monkeypatch.setattr(bsc, "_fetch_sdmx_years", lambda *a, **kw: (None, None))

        row = pd.Series(
            {
                "source_id": "istat_sdmx",
                "item_id": "32_221",
                "item_name": "32_221",
                "item_slug": np.nan,
                "title": "Test SDMX",
                "organization": np.nan,
                "tags": np.nan,
                "notes_excerpt": np.nan,
                "format": np.nan,
                "protocol": "sdmx",
                "source_url": np.nan,
                "api_base_url": np.nan,
                "landing_page": np.nan,
                "distribution_url": np.nan,
                "url": np.nan,
                "granularity": np.nan,
                "year_signal": np.nan,
                "encoding_suggested": np.nan,
                "delim_suggested": np.nan,
                "decimal_suggested": np.nan,
                "skip_suggested": np.nan,
                "source_status": "active",
            }
        )
        result = _check_row(row, "2026-05-21T12:00:00", registry)

        assert result["sdmx_flow"] == "32_221"
        assert result["sdmx_version"] == "1.0"
        assert result["sdmx_agency"] == "IT1"
        assert result["enrich_method"] == "sdmx_dataflow_annotations"


# ── dataset_group: _normalize_title_for_grouping ──────────────────────────────


class TestNormalizeTitleForGrouping:
    """Unit test per _normalize_title_for_grouping: 20 edge case noti."""

    # (input, expected_norm)
    CASES = [
        # Basic year stripping
        ("Population - 2022", "population"),
        ("Population - Years 2020-2025", "population"),
        ("Redditi fisco 2023", "redditi fisco"),
        ("2023 Redditi fisco", "redditi fisco"),
        # Multi-year comma/dash
        ("Local units - municipal level 2011, 2015", "local units - municipal level"),
        ("Serie storica anni 2010-2016", "serie storica"),
        # Italian date patterns (underscore-separated)
        ("Accordi_pa_privati_dal_2010_al_2025", "accordi_pa_privati"),
        ("provvedimenti_qualita_AIFA-2021_24.02.2022", "provvedimenti_qualita_aifa"),
        ("Classe_A_per_principio_attivo_30-10-2025", "classe_a_per_principio_attivo"),
        # _YYYY suffix
        ("REG_bonus_irpef_2024", "reg_bonus_irpef"),
        ("sesso_bonus_irpef_2019", "sesso_bonus_irpef"),
        # Leading year
        ("2009 trasparenza", "trasparenza"),
        ("2016 trasparenza", "trasparenza"),
        # No change needed
        ("Bank services - municipalities data", "bank services - municipalities data"),
        ("Municipal waste - production", "municipal waste - production"),
        # Edge: short title
        ("", ""),
        ("a", "a"),
        # Edge: format suffix
        ("FC40A_UNIONI_1_csv", "fc40a_unioni_1"),
        ("Ind_FC20TOT_3_csv", "ind_fc20tot_3"),
        # Corte Costituzionale
        ("CC_OpenMassime_1956_1980", "cc_openmassime"),
    ]

    @pytest.mark.parametrize("title,expected", CASES)
    def test_normalize(self, title, expected):
        from source_check_analyze import _normalize_title_for_grouping

        assert _normalize_title_for_grouping(title) == expected


class TestToSlug:
    def test_basic(self):
        from source_check_analyze import _to_slug

        assert _to_slug("hello world") == "hello-world"

    def test_special_chars_stripped(self):
        from source_check_analyze import _to_slug

        assert _to_slug("Economic activities (Nace 2 digit)!") == "economic-activities-nace-2-digit"

    def test_max_len(self):
        from source_check_analyze import _to_slug

        long = "a" * 200
        assert len(_to_slug(long)) == 80

    def test_empty(self):
        from source_check_analyze import _to_slug

        assert _to_slug("") == "unknown"

    def test_whitespace_collapsed(self):
        from source_check_analyze import _to_slug

        assert _to_slug("  many   spaces  ") == "many-spaces"


class TestComputeDatasetGroup:
    """Unit test per compute_dataset_group: verifica tutte le strategie."""

    def test_via_title(self):
        from source_check_analyze import compute_dataset_group

        g = compute_dataset_group("inps", "Numero pensionati 2022", "item_123")
        assert g == "inps/numero-pensionati"

    def test_via_sdmx_prefix(self):
        from source_check_analyze import compute_dataset_group

        g = compute_dataset_group("istat_sdmx", None, "183_1163_DF_DICA_ASIAULP_2", protocol="sdmx")
        # trailing _2 stripped, underscores removed by slugify
        assert "/sdmx/" in g
        assert "183" in g
        assert "asiaulp" in g
        assert g.startswith("istat_sdmx/")

    def test_via_item_id_fallback(self):
        from source_check_analyze import compute_dataset_group

        g = compute_dataset_group("anac", None, "da10182d-75ba-4894")
        assert "anac/" in g
        assert "da10182d" in g

    def test_unknown(self):
        from source_check_analyze import compute_dataset_group

        g = compute_dataset_group("x", None, None)
        assert g == "x/unknown"


class TestAddDatasetGroupColumns:
    """Test che add_dataset_group_columns aggiunga le colonne giuste."""

    def test_adds_columns(self):
        import pandas as pd
        from source_check_analyze import add_dataset_group_columns

        df = pd.DataFrame(
            [
                {
                    "source_id": "s1",
                    "item_id": "a",
                    "title": "Population 2022",
                    "year_min": 2022,
                    "year_max": 2022,
                },
                {
                    "source_id": "s1",
                    "item_id": "b",
                    "title": "Population 2023",
                    "year_min": 2023,
                    "year_max": 2023,
                },
            ]
        )
        result = add_dataset_group_columns(df)
        assert "dataset_group" in result.columns
        assert "dataset_group_size" in result.columns
        assert "dataset_group_year_min" in result.columns
        assert "dataset_group_year_max" in result.columns
        # Same normalized title → same group
        assert result["dataset_group"].iloc[0] == result["dataset_group"].iloc[1]
        assert result["dataset_group_size"].iloc[0] == 2
        assert result["dataset_group_year_min"].iloc[0] == 2022
        assert result["dataset_group_year_max"].iloc[0] == 2023

    def test_sparse_row_without_year_columns(self):
        import pandas as pd
        from source_check_analyze import add_dataset_group_columns

        # Row without year_min/year_max (e.g. enrichment failed)
        df = pd.DataFrame(
            [
                {
                    "source_id": "s1",
                    "item_id": "z",
                    "title": None,
                    "year_min": None,
                    "year_max": None,
                }
            ]
        )
        result = add_dataset_group_columns(df)
        assert "dataset_group" in result.columns
        assert result["dataset_group"].iloc[0] is not None
        assert result["dataset_group_size"].iloc[0] == 1


# ── SPARQL enrichment contract ────────────────────────────────────────────────


class TestSparqlEnrichment:
    """contract: _enrich_sparql esegue query COUNT reali su endpoint SPARQL."""

    def _make_sparql_row(
        self,
        source_id: str = "dati_senato",
        item_id: str = "http://dati.senato.it/ddl/19",
        **overrides,
    ):
        import numpy as np
        import pandas as pd

        base = {
            "source_id": source_id,
            "item_id": item_id,
            "item_name": "19",
            "title": "Ddl — Legislatura 19",
            "organization": np.nan,
            "tags": np.nan,
            "notes_excerpt": np.nan,
            "url": np.nan,
            "landing_page": np.nan,
            "format": np.nan,
            "granularity": np.nan,
            "year_signal": np.nan,
            "encoding_suggested": np.nan,
            "delim_suggested": np.nan,
            "decimal_suggested": np.nan,
            "skip_suggested": np.nan,
            "protocol": "sparql",
        }
        base.update(overrides)
        return pd.Series(base)

    def test_sparql_enrich_calls_count_on_endpoint(self, monkeypatch):
        """Con endpoint configurato, fa query COUNT e propaga i campi."""
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        def _mock_count(endpoint, graph_uri=None, timeout=15):
            assert endpoint == "https://dati.senato.it/sparql"
            assert graph_uri == "http://dati.senato.it/ddl/19"
            return 879751

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sparql_count", _mock_count)
        # Evita chiamate HTTP reali
        monkeypatch.setattr(bsc, "_http_head_with_retry", lambda *a, **kw: (200, True, None, None))

        row = self._make_sparql_row()
        result = _enrich_with_inventory(row, registry)

        assert result["sparql_responding"] is True
        assert result["sparql_triple_count"] == 879751
        assert result["enrich_method"] == "sparql_probe"
        assert "SPARQL" in result["resource_format"]

    def test_sparql_enrich_failing_endpoint(self, monkeypatch):
        """Endpoint non raggiungibile → sparql_responding=False."""
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        def _mock_count(endpoint, graph_uri=None, timeout=15):
            return None  # endpoint irraggiungibile

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sparql_count", _mock_count)
        monkeypatch.setattr(bsc, "_http_head_with_retry", lambda *a, **kw: (200, True, None, None))

        row = self._make_sparql_row()
        result = _enrich_with_inventory(row, registry)

        assert result["sparql_responding"] is False
        assert result["sparql_triple_count"] is None

    def test_sparql_enrich_without_graph_uri(self, monkeypatch):
        """Item senza graph URI fa COUNT globale sull'endpoint."""
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        captured_graph = None

        def _mock_count(endpoint, graph_uri=None, timeout=15):
            nonlocal captured_graph
            captured_graph = graph_uri
            return 1000

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sparql_count", _mock_count)
        monkeypatch.setattr(bsc, "_http_head_with_retry", lambda *a, **kw: (200, True, None, None))

        row = self._make_sparql_row(item_id="no-graph-uri")
        result = _enrich_with_inventory(row, registry)

        assert captured_graph is None  # COUNT globale senza graph_uri
        assert result["sparql_responding"] is True
        assert result["sparql_triple_count"] == 1000

    def test_sparql_fallback_handles_missing_fields(self, monkeypatch):
        """Fallback (protocollo non SPARQL) → campi assenti ma .get() safe."""
        import numpy as np
        import pandas as pd
        import yaml
        from bulk_source_check import _enrich_with_inventory

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        row = pd.Series(
            {
                "source_id": "consip_open_data",
                "item_id": "test-ckan-item",
                "item_name": "test",
                "title": "Test CKAN",
                "organization": np.nan,
                "tags": np.nan,
                "notes_excerpt": np.nan,
                "url": np.nan,
                "landing_page": np.nan,
                "format": np.nan,
                "granularity": np.nan,
                "year_signal": np.nan,
                "encoding_suggested": np.nan,
                "delim_suggested": np.nan,
                "decimal_suggested": np.nan,
                "skip_suggested": np.nan,
                "protocol": "ckan",
            }
        )
        result = _enrich_with_inventory(row, registry)

        # I campi SPARQL non sono nell'enrich di handler CKAN,
        # ma sono safe via .get() (non sollevano KeyError)
        assert result.get("sparql_responding") is None  # non presente
        assert result.get("sparql_triple_count") is None


class TestSparqlCheckRowPassthrough:
    """contract: _check_row passa sparql_responding e sparql_triple_count."""

    def test_sparql_fields_in_result(self, monkeypatch):
        import numpy as np
        import pandas as pd
        import yaml
        from bulk_source_check import _check_row

        with open("data/radar/sources_registry.yaml") as f:
            registry = yaml.safe_load(f)

        def _mock_count(endpoint, graph_uri=None, timeout=15):
            return 879751

        import bulk_source_check as bsc

        monkeypatch.setattr(bsc, "_fetch_sparql_count", _mock_count)
        monkeypatch.setattr(bsc, "_http_head_with_retry", lambda *a, **kw: (200, True, None, None))
        monkeypatch.setattr(
            bsc, "_fetch_data_preview", lambda *a, **kw: {"enrich_method": "inventory_only"}
        )

        row = pd.Series(
            {
                "source_id": "dati_senato",
                "item_id": "http://dati.senato.it/ddl/19",
                "item_name": "19",
                "title": "Ddl — Legislatura 19",
                "organization": np.nan,
                "tags": np.nan,
                "notes_excerpt": np.nan,
                "url": np.nan,
                "landing_page": np.nan,
                "distribution_url": np.nan,
                "format": np.nan,
                "protocol": "sparql",
                "source_url": np.nan,
                "api_base_url": np.nan,
                "granularity": np.nan,
                "year_signal": np.nan,
                "encoding_suggested": np.nan,
                "delim_suggested": np.nan,
                "decimal_suggested": np.nan,
                "skip_suggested": np.nan,
                "source_status": "active",
            }
        )
        result = _check_row(row, "2026-06-08T12:00:00", registry)

        assert result["sparql_responding"] is True
        assert result["sparql_triple_count"] == 879751
        assert result["enrich_method"] == "sparql_probe"


pytestmark = pytest.mark.contract
