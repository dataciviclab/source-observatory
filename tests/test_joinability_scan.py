"""Test scripts/joinability_scan.py — logica di joinability pura (no I/O)."""

from __future__ import annotations

import json

import pytest
from joinability_scan import (
    BRIDGE_SLUG,
    build_catalog_index,
    build_json_output,
    compute_joinability_score,
    cross_reference,
    derive_bridge_keys,
    detect_keys,
    parse_columns,
)

pytestmark = pytest.mark.pure_unit


class TestParseColumns:
    """parse_columns() gestisce vari formati della colonna `columns`."""

    def test_none(self):
        assert parse_columns(None) == []

    def test_nan_float(self):
        assert parse_columns(float("nan")) == []

    def test_not_a_string(self):
        assert parse_columns(42) == []

    def test_empty_json_list(self):
        assert parse_columns("[]") == []

    def test_list_of_strings(self):
        raw = '["Comune", "Provincia", "Anno"]'
        assert parse_columns(raw) == ["Comune", "Provincia", "Anno"]

    def test_list_of_dicts(self):
        raw = '[{"name": "Comune", "type": "string"}, {"name": "Anno"}]'
        assert parse_columns(raw) == ["Comune", "Anno"]

    def test_malformed_json(self):
        assert parse_columns("{broken") == ["{broken"]

    def test_dict_columns(self):
        raw = '{"Comune": "string", "Anno": "int"}'
        result = parse_columns(raw)
        assert "Comune" in result
        assert "Anno" in result


class TestDetectKeys:
    """detect_keys() matcha colonne contro KEY_PATTERNS."""

    def test_empty(self):
        assert detect_keys([]) == {}

    def test_istat_comune(self):
        keys = detect_keys(["codice_istat_comune", "popolazione"])
        assert "istat_comune" in keys
        assert keys["istat_comune"] == ["codice_istat_comune"]

    def test_comune_short(self):
        keys = detect_keys(["Comune"])
        assert "istat_comune" in keys

    def test_pro_com(self):
        keys = detect_keys(["pro_com", "comune"])
        # Both match istat_comune
        assert "istat_comune" in keys

    def test_anno_variants(self):
        keys = detect_keys(["anno", "Anno", "ANNOSCOLASTICO", "anno_di_imposta"])
        assert "anno" in keys
        assert len(keys["anno"]) == 4

    def test_provincia_variants(self):
        keys = detect_keys(["PROVINCIA", "sigla_provincia", "provincia"])
        assert "provincia" in keys

    def test_codice_istat_regione(self):
        keys = detect_keys(["codice_istat_regione", "codreg"])
        assert "istat_regione" in keys

    def test_codice_ente(self):
        keys = detect_keys(["id_ente", "codice_ente_ipa", "codice_ente_siope"])
        assert "codice_ente" in keys

    def test_codice_scuola(self):
        keys = detect_keys(["CODICESCUOLA", "codice_scuola"])
        assert "codice_scuola" in keys

    def test_codice_catastale(self):
        keys = detect_keys(["codice_catastale", "Codice_Catastale"])
        assert "codice_catastale" in keys

    def test_no_match(self):
        keys = detect_keys(["nome", "cognome", "indirizzo"])
        assert keys == {}

    def test_mixed(self):
        keys = detect_keys(["CODICE_COMUNE", "anno", "REDDITO"])
        assert "istat_comune" in keys
        assert "anno" in keys


class TestBuildCatalogIndex:
    """build_catalog_index() costruisce indice usabile."""

    def test_empty(self):
        assert build_catalog_index([]) == {}

    def test_basic(self):
        catalog = [
            {
                "slug": "test_ds",
                "name": "Test Dataset",
                "source": "Test Source",
                "columns": [{"name": "anno", "type": "INTEGER"}],
            }
        ]
        idx = build_catalog_index(catalog)
        assert "test_ds" in idx
        assert idx["test_ds"]["name"] == "Test Dataset"
        assert "anno" in idx["test_ds"]["col_set"]

    def test_list_of_strings_as_columns(self):
        catalog = [
            {
                "slug": "ds",
                "columns": ["Comune", "Anno"],
            }
        ]
        idx = build_catalog_index(catalog)
        assert "comune" in idx["ds"]["col_set"]

    def test_missing_slug_falls_back_to_name(self):
        catalog = [{"name": "ds_name", "columns": []}]
        idx = build_catalog_index(catalog)
        assert "ds_name" in idx


class TestDeriveBridgeKeys:
    """derive_bridge_keys() estrae chiavi semantiche dal dataset bridge."""

    def test_bridge_not_found(self):
        assert derive_bridge_keys({}) == set()

    def test_bridge_empty_columns(self):
        idx = {BRIDGE_SLUG: {"col_set": set(), "name": "Bridge", "slug": BRIDGE_SLUG}}
        assert derive_bridge_keys(idx) == set()

    def test_bridge_with_istat_keys(self):
        idx = {
            BRIDGE_SLUG: {
                "col_set": {"codice_istat_comune", "codice_regione", "sigla_provincia"},
                "name": "Bridge",
                "slug": BRIDGE_SLUG,
            }
        }
        keys = derive_bridge_keys(idx)
        assert "istat_comune" in keys
        assert "istat_regione" in keys
        assert "provincia" in keys

    def test_bridge_with_catastale(self):
        idx = {
            BRIDGE_SLUG: {
                "col_set": {"codice_catastale", "codice_ente_ipa"},
                "name": "Bridge",
                "slug": BRIDGE_SLUG,
            }
        }
        keys = derive_bridge_keys(idx)
        assert "codice_catastale" in keys
        assert "codice_ente" in keys


class TestCrossReference:
    """cross_reference() trova match diretti e via bridge."""

    CATALOG = [
        {
            "slug": "popolazione",
            "name": "Popolazione",
            "columns": [{"name": "codice_istat_comune"}, {"name": "anno"}],
        },
        {
            "slug": "irpef",
            "name": "IRPEF",
            "columns": [{"name": "codice_catastale"}, {"name": "anno"}],
        },
        {
            "slug": "scuole",
            "name": "Scuole",
            "columns": [{"name": "codice_scuola"}, {"name": "anno"}],
        },
    ]

    BRIDGE_KEYS = {"istat_comune", "codice_catastale", "codice_scuola", "provincia"}

    @pytest.fixture
    def idx(self):
        return build_catalog_index(self.CATALOG)

    def test_direct_match(self, idx):
        """Stessa colonna → match diretto."""
        keys = {"anno": ["Anno"]}
        refs = cross_reference(keys, idx, self.BRIDGE_KEYS)
        assert len(refs) == 3  # tutti hanno anno
        for r in refs:
            assert "diretto" in r["match_tags"]

    def test_via_bridge(self, idx):
        """Colonna diversa ma nella bridge → match indiretto."""
        # Candidate ha solo codice_catastale (stessa colonna di IRPEF)
        keys = {"codice_catastale": ["codice_catastale"]}
        refs = cross_reference(keys, idx, self.BRIDGE_KEYS)
        slugs = [r["slug"] for r in refs]
        # Match diretto con irpef (stessa colonna)
        assert "irpef" in slugs
        # Match via bridge con popolazione e scuole
        assert "popolazione" in slugs
        assert "scuole" in slugs
        for r in refs:
            if r["slug"] == "irpef":
                assert "diretto" in r["match_tags"]
            else:
                assert "via bridge" in r["match_tags"]

    def test_no_common_keys(self, idx):
        """Nessuna chiave in comune → lista vuota."""
        keys = {"atc": ["atc1"]}
        refs = cross_reference(keys, idx, self.BRIDGE_KEYS)
        assert refs == []

    def test_candidate_has_multiple_keys(self, idx):
        """Candidate con più chiavi matcha più dataset."""
        keys = {"codice_catastale": ["codice_catastale"], "anno": ["Anno"]}
        refs = cross_reference(keys, idx, self.BRIDGE_KEYS)
        assert len(refs) >= 3


class TestComputeJoinabilityScore:
    """compute_joinability_score() produce score 0-100."""

    def test_no_keys(self):
        assert compute_joinability_score({}, []) == 0.0

    def test_single_key_no_matches(self):
        score = compute_joinability_score({"mese": ["Mese"]}, [])
        assert score == 3.0  # solo peso mese

    def test_istat_comune_only(self):
        score = compute_joinability_score({"istat_comune": ["Comune"]}, [])
        assert score == 30.0

    def test_with_direct_matches(self):
        keys = {"istat_comune": ["Comune"], "anno": ["Anno"]}
        matches = [{"slug": "a", "match_tags": "diretto"}, {"slug": "b", "match_tags": "diretto"}]
        score = compute_joinability_score(keys, matches)
        # 30 (istat) + 15 (anno) + 5 (bonus 2 keys) + 6 (2 match * 3)
        assert score > 50
        assert score <= 100

    def test_with_bridge_matches(self):
        keys = {"istat_comune": ["Comune"]}
        matches = [
            {"slug": "a", "match_tags": "diretto"},
            {"slug": "b", "match_tags": "via bridge"},
            {"slug": "c", "match_tags": "via bridge"},
        ]
        score = compute_joinability_score(keys, matches)
        # 30 (istat) + 3 (1 diretto * 3) + 2 (2 bridge * 1)
        assert score == 35.0


class TestBuildJsonOutput:
    """build_json_output() emette campi corretti e ordina per enriched score."""

    def _make_item(self, base_score: float, enriched_score: float, n_keys: int) -> dict:
        """Helper per creare item di test."""
        return {
            "source_id": "test",
            "item_name": "item",
            "intake_score": 50,
            "joinability_score": base_score,
            "enriched_joinability_score": enriched_score,
            "col_count": 5,
            "found_keys": {f"k{i}": [f"col{i}"] for i in range(n_keys)},
            "catalog_matches": [],
        }

    def test_emits_enriched_score(self):
        """build_json_output include enriched_joinability_score nel JSON."""
        items = [self._make_item(30, 55, 2)]
        output = build_json_output(items, {}, set(), {"total": 1, "total_with_keys": 1, "catalog_size": 0})
        top = output["top_items"]
        assert len(top) == 1
        assert "enriched_joinability_score" in top[0]
        assert top[0]["enriched_joinability_score"] == 55.0
        assert top[0]["joinability_score"] == 30.0

    def test_sorts_by_enriched_score_desc(self):
        """build_json_output ordina per enriched_joinability_score decrescente."""
        items = [
            self._make_item(10, 20, 1),
            self._make_item(30, 80, 2),
            self._make_item(20, 50, 1),
        ]
        output = build_json_output(items, {}, set(), {"total": 3, "total_with_keys": 3, "catalog_size": 0})
        scores = [i["enriched_joinability_score"] for i in output["top_items"]]
        assert scores == [80, 50, 20], f"expected descending scores, got {scores}"

    def test_fallback_when_missing_enriched(self):
        """Senza enriched_joinability_score, usa joinability_score."""
        items = [{
            "source_id": "test",
            "item_name": "item",
            "intake_score": 50,
            "joinability_score": 42,
            "col_count": 5,
            "found_keys": {"k1": ["c1"]},
            "catalog_matches": [],
        }]
        output = build_json_output(items, {}, set(), {"total": 1, "total_with_keys": 1, "catalog_size": 0})
        assert output["top_items"][0]["enriched_joinability_score"] == 42.0
