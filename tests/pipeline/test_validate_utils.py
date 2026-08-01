"""
Test validate utilities — probe, sniff, anni, cluster.

I test di rete usano ``fake_http`` (FakeHttpClient da lab_connectors.testing)
per essere deterministici e non dipendere da fonti esterne. I test smoke
(su URL reali) sono in ``TestSmokeNetwork``: non fanno parte del gate CI.

Tests cover:
  - URL selection (pick best CSV per group)
  - Reachability probe (HEAD)
  - CSV schema sniffing
  - Year extraction
"""

from __future__ import annotations

import pytest
from lab_connectors.http import HttpResult
from lab_connectors.testing import fake_response

from scripts._constants import format_score as _format_score
from scripts.collectors._validate_base import (
    _extract_year_range,
    _is_year_column,
    _sniff_csv_duckdb,
    _year_range_from_df,
    pick_best_url,
    probe_reachability,
    sniff_csv_schema,
)
from scripts.collectors._validate_base import (
    validate_tabular_group as validate_group,
)

pytestmark = pytest.mark.pure_unit

MEF_URL = (
    "https://www1.finanze.gov.it/finanze/analisi_stat/public/v_4_0_0/"
    "contenuti/REG_tipo_reddito_2025.csv?d=1615465800"
)
# URL senza query: validate_tabular_group fa url.split('?')[0] prima del probe
MEF_URL_NO_QUERY = MEF_URL.split("?")[0]

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


# ── Unit: reachability probe (FAKE, deterministico) ──────────────────────────


class TestProbeReachability:
    def test_reachable_url(self, monkeypatch, fake_http):
        """HEAD 200 → reachable True."""
        fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, ""), err=None)
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = probe_reachability(MEF_URL)
        assert result["reachable"] is True
        assert result["status_code"] == 200

    def test_404_url(self, monkeypatch, fake_http):
        """HEAD con response HTTP (anche 4xx) → is_ok True (err None)."""
        fake_http.responses[MEF_URL] = HttpResult(
            response=fake_response(404, "not found"), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = probe_reachability(MEF_URL)
        # HttpResult.is_ok = response presente e err None → 404 e' 'ok' come response
        assert result["reachable"] is True
        assert result["status_code"] == 404

    def test_connection_error(self, monkeypatch, fake_http):
        """HEAD con errore di rete → reachable False, error valorizzato."""
        from requests.exceptions import ConnectionError

        fake_http.responses[MEF_URL] = HttpResult(
            response=None, err=ConnectionError("connection refused")
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = probe_reachability(MEF_URL)
        assert result["reachable"] is False
        assert result["error"] is not None


# ── Unit: CSV sniffing (FAKE, deterministico) ────────────────────────────────


class TestSniffCSVSchema:
    def test_real_csv(self, monkeypatch, fake_http):
        """CSV reale (MEF) → colonne e dati."""
        csv_body = (
            "ANNO,REGIONE,CODICE_FISCALE,IMPORTO\n"
            "2024,Lazio,AAA000000000000X,1000\n"
            "2023,Lombardia,BBB000000000000Y,2000\n"
        )
        fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        assert result["error"] is None, f"Sniff error: {result['error']}"
        assert len(result["columns"]) > 0, "Should have columns"
        assert result["num_columns"] > 0
        assert result["delimiter"] is not None

    def test_binary_content(self, monkeypatch, fake_http):
        """Contenuto binario (ZIP) — il parser standard produce colonne spurie
        o errore; il fallback DuckDB deve recuperare senza crash."""
        fake_http.responses[MEF_URL] = HttpResult(
            response=fake_response(200, "PK\x03\x04binary"), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        # il parse standard su binario non deve andare in eccezione non gestita
        assert result["error"] is None or isinstance(result["error"], str)
        assert isinstance(result["columns"], list)

    def test_fetch_error(self, monkeypatch, fake_http):
        """GET con errore di rete → error valorizzato, nessun crash."""
        from requests.exceptions import ConnectionError

        fake_http.responses[MEF_URL] = HttpResult(response=None, err=ConnectionError("refused"))
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        assert result["error"] is not None

    def test_empty_body(self, monkeypatch, fake_http):
        """Body vuoto → error 'Empty response'."""
        fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, ""), err=None)
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        assert result["error"] is not None

    def test_bom_encoding(self, monkeypatch, fake_http):
        """CSV con BOM → encoding utf-8-sig, colonne parsate."""
        csv_body = "\ufeffANNO,REGIONE\n2020,Lazio\n"
        fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        assert result["encoding"] == "utf-8-sig"
        assert "ANNO" in (result["columns"] or [])

    def test_weird_delimiter_fallback(self, monkeypatch, fake_http):
        """Contenuto con delimitatore non sniffabile → fallback su virgola."""
        # testo senza delimitatori chiari: Sniffer fallisce, si usa ','
        csv_body = "abc\ndef\nghi\n"
        fake_http.responses[MEF_URL] = HttpResult(response=fake_response(200, csv_body), err=None)
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        result = sniff_csv_schema(MEF_URL)
        # nessun crash; colonne presenti o vuote ma error assente se parsabile
        assert isinstance(result["columns"], list)


# ── Unit: validate_group (FAKE, deterministico) ──────────────────────────────


class TestValidateGroup:
    def test_validate_mef_irpef_group(self, monkeypatch, fake_http):
        """Validazione gruppo CSV reale (fake) → reachable, colonne, anno."""
        csv_body = (
            "ANNO,REGIONE,CODICE_FISCALE,IMPORTO\n"
            "2024,Lazio,AAA000000000000X,1000\n"
            "2023,Lombardia,BBB000000000000Y,2000\n"
        )
        fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
            response=fake_response(200, csv_body), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": MEF_URL_NO_QUERY,
                "format": "csv",
                "year_signal": 2025,
            },
        ]
        result = validate_group(items)
        assert result["reachable"] is True
        assert result["url"] is not None
        assert len(result.get("columns", [])) > 0

    def test_validate_csv_with_sniff(self, monkeypatch, fake_http):
        """Validazione con sniff: anno estratto dalla colonna ANNO."""
        csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n2021,Lombardia,2000\n"
        fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
            response=fake_response(200, csv_body), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": MEF_URL_NO_QUERY,
                "format": "csv",
                "year_signal": 2025,
            }
        ]
        result = validate_group(items)
        assert result["reachable"] is True
        assert result.get("dataset_group_year_min") == 2020
        assert result.get("dataset_group_year_max") == 2021

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
                "distribution_url": "https://example.test/data_2024.zip",
                "format": "zip",
                "year_signal": 2024,
            }
        ]
        result = validate_group(items)
        # Non-CSV: skips HEAD, reachable=None (non verificato)
        assert result["reachable"] is None
        assert "note" in result
        assert "Non-CSV" in result["note"]

    def test_validate_nan_year_propagated(self, monkeypatch, fake_http):
        """Il merge pandas produce NaN (non None) per gli anni:
        il validatore deve trattarlo come 'assente' e usare lo sniff."""
        csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n2021,Lombardia,2000\n"
        fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
            response=fake_response(200, csv_body), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": MEF_URL,
                "format": "csv",
                # simula il merge pandas: year_min/max = NaN (float nan)
                "dataset_group_year_min": float("nan"),
                "dataset_group_year_max": float("nan"),
            }
        ]
        result = validate_group(items)
        # gli anni arrivano dallo sniff (2020-2021), non dal NaN del gruppo
        assert result.get("dataset_group_year_min") == 2020
        assert result.get("dataset_group_year_max") == 2021

    def test_validate_with_existing_years_keeps_them(self, monkeypatch, fake_http):
        """Se il gruppo fornisce gia' anni validi, lo sniff non li sovrascrive."""
        csv_body = "ANNO,REGIONE,IMPORTO\n2020,Lazio,1000\n"
        fake_http.responses[MEF_URL_NO_QUERY] = HttpResult(
            response=fake_response(200, csv_body), err=None
        )
        monkeypatch.setattr("scripts.collectors._validate_base.HttpClient", lambda **kw: fake_http)
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": MEF_URL,
                "format": "csv",
                "dataset_group_year_min": 2015,
                "dataset_group_year_max": 2024,
            }
        ]
        result = validate_group(items)
        assert result.get("dataset_group_year_min") == 2015
        assert result.get("dataset_group_year_max") == 2024


# ── Smoke: verifica su URL reali (richiede rete, NON nel gate CI) ────────────


@pytest.mark.smoke
class TestSmokeNetwork:
    def test_reachable_url(self):
        result = probe_reachability(MEF_URL)
        assert result["reachable"] is True
        assert result["status_code"] == 200

    def test_real_csv_from_mef(self):
        result = sniff_csv_schema(MEF_URL)
        assert result["error"] is None, f"Sniff error: {result['error']}"
        assert len(result["columns"]) > 0
        assert result["num_columns"] > 0
        assert result["delimiter"] is not None

    def test_validate_mef_irpef_group(self):
        items = [
            {
                "dataset_group": "mef_irpef/statistiche/reg-tipo-reddito",
                "source_id": "mef_irpef",
                "distribution_url": MEF_URL,
                "format": "csv",
                "year_signal": 2025,
            },
        ]
        result = validate_group(items)
        assert result["reachable"] is True
        assert result["url"] is not None
        assert "2025" in result["url"]


# ── Unit: year extraction (_extract_year_range) ───────────────────────────────


class TestExtractYearRange:
    def test_year_from_column_names(self):
        """Anni nei nomi colonna (es. anno_2020)."""
        ymin, ymax = _extract_year_range(
            raw=None,
            columns=["comune", "anno_2018", "valore"],
            sample=[],
            url="https://example.test/data.csv",
        )
        assert (ymin, ymax) == (2018, 2018)

    def test_year_from_filename(self):
        """Anni nel filename (es. beneficiari_2007-2013.zip)."""
        ymin, ymax = _extract_year_range(
            raw=None,
            columns=["comune", "valore"],
            sample=[],
            url="https://example.test/beneficiari_2007-2013.zip",
        )
        assert (ymin, ymax) == (2007, 2013)

    def test_year_from_values_via_duckdb(self):
        """Anni dai valori di una colonna-anno (ANNO), tipizzati via DuckDB."""
        csv_bytes = b"ANNO,REGIONE,VALORE\n2018,Lazio,1\n2019,Lazio,2\n2020,Lazio,3\n"
        ymin, ymax = _extract_year_range(
            raw=csv_bytes,
            columns=["ANNO", "REGIONE", "VALORE"],
            sample=[],
            url="https://example.test/data.csv",
        )
        assert (ymin, ymax) == (2018, 2020)

    def test_no_year_returns_none(self):
        ymin, ymax = _extract_year_range(
            raw=b"COMUNE,VALORE\nRoma,1\n",
            columns=["COMUNE", "VALORE"],
            sample=[],
            url="https://example.test/data.csv",
        )
        assert (ymin, ymax) == (None, None)

    def test_is_year_column(self):
        assert _is_year_column("ANNO")
        assert _is_year_column("time_period")
        assert _is_year_column("anno di riferimento")
        assert not _is_year_column("comune")
        assert not _is_year_column("valore")


# ── Unit: year range da DataFrame (colonna-anno) ──────────────────────────────


class TestYearRangeFromDF:
    def test_df_with_year_column(self):
        """Colonna-anno per nome hint (es. ANNO) → min/max."""
        import pandas as pd

        df = pd.DataFrame({"ANNO": [2018, 2019, 2020], "VALORE": [1, 2, 3]})
        assert _year_range_from_df(df) == (2018, 2020)

    def test_df_without_year_name_uses_numeric_fallback(self):
        """Senza nome hint, usa colonna numerica con 2+ valori 1900-2100."""
        import pandas as pd

        df = pd.DataFrame({"COMUNE": ["Roma", "Milano", "Napoli"], "ANNO_REF": [2018, 2019, 2020]})
        # ANNO_REF non e' in _YEAR_COLUMN_HINTS ma contiene anni → fallback numerico
        assert _year_range_from_df(df) == (2018, 2020)

    def test_df_empty_columns(self):
        import pandas as pd

        df = pd.DataFrame()
        assert _year_range_from_df(df) == (None, None)

    def test_df_no_year_values(self):
        """Nessuna colonna con valori nel range anni → (None, None)."""
        import pandas as pd

        df = pd.DataFrame({"COMUNE": ["Roma", "Milano"], "POP": [100, 200]})
        assert _year_range_from_df(df) == (None, None)

    def test_df_single_year_value(self):
        """Un solo valore anno → non sufficiente per il fallback numerico
        (serve 2+), ma la colonna con nome hint funziona comunque."""
        import pandas as pd

        df = pd.DataFrame({"ANNO": [2020], "VALORE": [1]})
        assert _year_range_from_df(df) == (2020, 2020)

    def test_df_numeric_fallback_without_year_name(self):
        """Colonna senza nome hint ma con valori anno → fallback numerico."""
        import pandas as pd

        # REF non ha nome hint (non inizia con 'anno', non e' in hints)
        df = pd.DataFrame({"ID": [1, 2, 3], "REF": [2018, 2019, 2020]})
        assert _year_range_from_df(df) == (2018, 2020)

    def test_df_with_nan_values(self):
        """Valori NaN nella colonna anno vengono ignorati."""
        import pandas as pd

        df = pd.DataFrame({"ANNO": [2018, None, 2020]})
        assert _year_range_from_df(df) == (2018, 2020)


# ── Unit: DuckDB fallback (sniff) ────────────────────────────────────────────


class TestSniffDuckDB:
    def test_duckdb_error_path(self):
        """Input non-CSV (es. binario) → error valorizzato, nessun crash."""
        result = _sniff_csv_duckdb(b"\x00\x01\x02binary", 1024)
        # colonne vuote e/o error presente — mai eccezione
        assert isinstance(result["columns"], list)
        assert result["error"] is None or isinstance(result["error"], str)

    def test_duckdb_parses_csv(self):
        """CSV semplice → colonne corrette via DuckDB."""
        result = _sniff_csv_duckdb(b"ANNO,REGIONE\n2020,Lazio\n", 1024)
        assert result["columns"] == ["ANNO", "REGIONE"]
        assert result["num_columns"] == 2
