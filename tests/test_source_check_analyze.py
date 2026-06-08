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
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format="CSV",
            enrich_method="ckan_package_show",
            needs_review=False,
        )
        assert score >= 50
        assert candidate is True

    def test_not_reachable(self):
        score, candidate = _intake_score(
            granularity="non_determinato",
            year_min=None,
            year_max=None,
            reachable=False,
            resource_format=None,
            enrich_method="none",
            needs_review=True,
        )
        assert score == 0
        assert candidate is False

    def test_single_year(self):
        score, candidate = _intake_score(
            granularity="comune",
            year_min=2020,
            year_max=None,
            reachable=True,
            resource_format="CSV",
            enrich_method="none",
            needs_review=False,
        )
        assert score > 0

    def test_stale_source(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format="CSV",
            enrich_method="ckan_package_show",
            needs_review=False,
            source_status="stale",
        )
        # stale sottrae 10 e forza needs_review=True → candidate=False
        assert candidate is False

    def test_robust_read(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format="CSV",
            enrich_method="ckan_package_show",
            needs_review=False,
            robust_read_suggested=True,
        )
        assert candidate is False  # needs_review forced

    def test_format_from_extension(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format=".csv",
            enrich_method="none",
            needs_review=False,
        )
        assert score > 0

    def test_format_non_matching_extension_returns_empty(self):
        assert _normalize_format("application/octet-stream") == ""

    def test_format_with_long_dotted_string_maps_to_ext(self):
        """Formato come 'application/vnd.ms-excel.sheet.binary' entra nel branch
        di estrazione estensione (dot + len > 6) ma .binary non e' in valid list."""
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format="application/vnd.ms-excel.sheet.binary",
            enrich_method="none",
            needs_review=False,
        )
        assert score > 0  # format non riconosciuto ma score arriva da altri fattori

    def test_intake_score_single_mapping_col(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format=None,
            enrich_method="none",
            needs_review=False,
            mapping_suggestions='{"a": "int"}',
        )
        assert score > 0

    def test_intake_score_invalid_mapping_json(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format=None,
            enrich_method="none",
            needs_review=False,
            mapping_suggestions="not valid json",
        )
        assert score > 0  # gracefully ignored

    def test_encoding_signal(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format="CSV",
            enrich_method="none",
            needs_review=False,
            encoding_suggested="utf-8",
        )
        assert score > 0

    def test_score_capped_at_100(self):
        score, candidate = _intake_score(
            granularity="comune",
            year_min=2000,
            year_max=2024,
            reachable=True,
            resource_format="CSV",
            enrich_method="ckan_package_show",
            needs_review=False,
            encoding_suggested="utf-8",
            delim_suggested=",",
            mapping_suggestions='{"col1": "int", "col2": "str"}',
        )
        assert score <= 100

    def test_mapping_suggestions_gives_bonus(self):
        score, candidate = _intake_score(
            granularity="regione",
            year_min=2010,
            year_max=2020,
            reachable=True,
            resource_format=None,
            enrich_method="none",
            needs_review=False,
            mapping_suggestions='{"a": "int", "b": "str"}',
        )
        assert score > 0


class TestFinalizeScores:
    def test_finalize_adds_score(self):
        result = _finalize_scores(
            {"granularity": "regione", "reachable": True, "needs_review": False}
        )
        assert "intake_score" in result
        assert "intake_candidate" in result
        assert isinstance(result["intake_score"], int)
        assert isinstance(result["intake_candidate"], bool)

    def test_finalize_adds_join_keys_mapping(self):
        """_finalize_scores produce join_keys come mapping {key: [colonne]}."""
        import json

        columns_raw = json.dumps(["Comune", "Anno", "Sesso", "Importo"])
        result = _finalize_scores(
            {
                "columns": columns_raw,
                "granularity": "comune",
                "year_min": 2020,
                "year_max": 2024,
                "reachable": True,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": False,
            }
        )
        assert "join_keys" in result
        assert "joinability_score" in result
        assert result["joinability_score"] > 0

        # join_keys deve essere dict {key: [colonne_matched]}
        parsed = json.loads(result["join_keys"])
        assert isinstance(parsed, dict), f"expected dict, got {type(parsed)}"
        assert "istat_comune" in parsed
        assert parsed["istat_comune"] == ["Comune"]
        assert "anno" in parsed
        assert parsed["anno"] == ["Anno"]

    def test_finalize_join_keys_none_without_columns(self):
        """Senza colonne profilate, join_keys deve essere None."""
        result = _finalize_scores(
            {
                "columns": None,
                "granularity": "non_determinato",
                "year_min": None,
                "year_max": None,
                "reachable": False,
                "enrich_method": "inventory_only",
                "needs_review": True,
            }
        )
        assert result["join_keys"] is None
        assert result["joinability_score"] == 0

    # ── Pattern anno lasco (ANNO_DEPOSITO sì, ANNOTAZIONI no) ────────────

    def test_anno_pattern_matches_ANNO_DEPOSITO(self):
        """ANNO_DEPOSITO deve matchare il pattern anno (prefix)."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["ANNO_DEPOSITO", "CODICE_SEDE", "VALORE"]),
                "granularity": "non_determinato",
                "year_min": None,
                "year_max": None,
                "reachable": False,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": True,
            }
        )
        keys = json.loads(result["join_keys"]) if result["join_keys"] else {}
        assert "anno" in keys, f"expected anno in keys, got {keys}"

    def test_anno_pattern_rejects_ANNOTAZIONI(self):
        """ANNOTAZIONI non deve matchare il pattern anno."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["ANNOTAZIONI", "VALORE"]),
                "granularity": "non_determinato",
                "year_min": None,
                "year_max": None,
                "reachable": False,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": True,
            }
        )
        keys = json.loads(result["join_keys"]) if result["join_keys"] else {}
        assert "anno" not in keys, f"ANNOTAZIONI should NOT match anno, got {keys}"

    # ── Granularità da colonne profilate ─────────────────────────────────

    def test_granularity_from_columns_comune(self):
        """Colonna 'Comune' → granularità determinata come comune."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["Comune", "Anno", "Reddito"]),
                "granularity": "non_determinato",
                "year_min": 2020,
                "year_max": 2024,
                "reachable": True,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": True,
            }
        )
        assert result["granularity"] == "comune", f"expected comune, got {result['granularity']}"
        assert result["needs_review"] is False, "needs_review should become False"

    def test_granularity_from_columns_provincia(self):
        """Colonna 'Provincia' → granularità determinata come provincia."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["Provincia", "Anno", "Importo"]),
                "granularity": "non_determinato",
                "year_min": 2020,
                "year_max": 2024,
                "reachable": True,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": True,
            }
        )
        assert result["granularity"] == "provincia"

    def test_granularity_from_columns_codice_comune(self):
        """Colonna 'CODICE_COMUNE' → granularità comune."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["CODICE_COMUNE", "ANNO", "VALORE"]),
                "granularity": "non_determinato",
                "year_min": 2020,
                "year_max": 2024,
                "reachable": True,
                "resource_format": "CSV",
                "enrich_method": "csv_preview",
                "needs_review": True,
            }
        )
        assert result["granularity"] == "comune"

    def test_granularity_not_inferred_without_geo_columns(self):
        """Senza colonne geografiche, granularità resta non_determinato."""
        import json

        result = _finalize_scores(
            {
                "columns": json.dumps(["Nome", "Cognome", "Reddito"]),
                "granularity": "non_determinato",
                "year_min": None,
                "year_max": None,
                "reachable": False,
                "resource_format": "CSV",
                "enrich_method": "inventory_only",
                "needs_review": True,
            }
        )
        assert result["granularity"] == "non_determinato"

    # ── SDMX fallback join keys ──────────────────────────────────────────

    def test_sdmx_fallback_join_keys(self):
        """SDMX con granularità+anni+tags produce join_keys da metadata."""
        result = _finalize_scores(
            {
                "resource_format": "SDMX",
                "granularity": "provincia",
                "year_min": 2015,
                "year_max": 2024,
                "tags": "monthly, monthly data, short term",
                "notes": None,
                "title": "Producer price index",
                "sdmx_flow": "101_12_DF_DCSP_PREZZIAGR_2",
                "enrich_method": "sdmx_dataflow_annotations",
                "needs_review": False,
                "reachable": False,
            }
        )
        import json

        keys = json.loads(result["join_keys"]) if result["join_keys"] else {}
        assert "provincia" in keys, f"expected provincia, got {keys}"
        assert "anno" in keys, f"expected anno, got {keys}"
        assert "mese" in keys, f"expected mese from 'monthly' tag, got {keys}"
        assert result["joinability_score"] > 0

    def test_sdmx_fallback_no_false_keys(self):
        """SDMX senza metadata rilevanti → nessuna chiave falsa."""
        result = _finalize_scores(
            {
                "resource_format": "SDMX",
                "granularity": "nazionale",
                "year_min": None,
                "year_max": None,
                "tags": "structural, annual, general",
                "notes": None,
                "title": "National accounts",
                "sdmx_flow": "101_XX_DF_DCSP_XXX_1",
                "enrich_method": "sdmx_dataflow_annotations",
                "needs_review": True,
                "reachable": False,
            }
        )
        # nazionale → no territorial key
        # no years → no temporal key
        # tags "structural, annual, general" → non contengono sesso/eta/cittadinanza/mese
        assert result["join_keys"] is None, f"expected no keys, got {result['join_keys']}"


class TestFallbackInfer:
    def test_fallback_from_title_and_tags(self):
        row = pd.Series({"title": "Bilancio regionale", "tags": "finanza", "notes_excerpt": None})
        granularity, ymin, ymax = _fallback_infer(row)
        assert granularity is not None
