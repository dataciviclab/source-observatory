"""Smoke test per build_compliance_scores.py.

Verifica che lo script produca output valido con dati reali.
Non e' un test unitario — e' un test di integrazione minimo
che protegge il contratto verso data-advocacy.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from _constants import CATALOG_SIGNALS_PATH, RADAR_SUMMARY_PATH, REGISTRY_PATH

from scripts.build_compliance_scores import (
    _build_inventory_stats,
    _build_license_stats,
    _build_source_check_stats,
    _datigovit_score,
    _flag_urgenza,
    _formato_score,
    _hvd_score,
    _licenza_score,
    _load_source_check_stats,
    _raggiungibilita_score,
    build_scores,
)


class TestBuildComplianceScores:
    """Smoke: lo script produce output valido con dati reali."""

    @pytest.mark.contract
    def test_build_scores_produce_output_valido(self):
        registry = self._load_yaml(REGISTRY_PATH)
        radar = self._load_json(RADAR_SUMMARY_PATH)
        signals = self._load_json(CATALOG_SIGNALS_PATH)

        radar_sources = radar.get("sources", []) if isinstance(radar, dict) else []
        result = build_scores(registry, radar_sources, signals)

        assert "captured_at" in result
        assert "sources_scored" in result
        assert "distribuzione" in result
        assert "scores" in result
        assert result["sources_scored"] > 0

        # Verifica struttura di ogni score
        for entry in result["scores"]:
            assert "source_id" in entry
            assert "totale" in entry
            assert "livello" in entry
            assert "azione_raccomandata" in entry
            assert "assi" in entry
            assert 0 <= entry["totale"] <= 100

            assi = entry["assi"]
            assert "formato_aperto" in assi
            assert "raggiungibilita" in assi
            assert "licenza_aperta" in assi
            assert "presenza_datigovit" in assi
            assert "hvd_compliance" in assi
            assert "accessibilita_foia" in assi

            for k, v in assi.items():
                assert "score" in v
                assert "fonte" in v
                assert v["fonte"] in ("computed", "estimated", "missing")
                assert 0 <= v["score"] <= 100

        # Verifica distribuzione
        dist = result["distribuzione"]
        assert "buono" in dist
        assert "medio" in dist
        assert "debole" in dist
        assert "carente" in dist

    @pytest.mark.contract
    def test_formato_score_da_inventory(self):
        """Asse A: inventory stats con case misto e formati reali."""
        inv = {
            "test_fonte": {
                "total": 10,
                "con_formato": 10,
                "aperti": 7,
                "perc_aperto": 70.0,
                "copertura": 100.0,
            }
        }
        score, fonte = _formato_score("ckan", [], inv, "test_fonte")
        assert score == 55.0
        assert fonte == "computed"
        # 100% aperti
        inv2 = {
            "test_fonte2": {
                "total": 5,
                "con_formato": 5,
                "aperti": 5,
                "perc_aperto": 100.0,
                "copertura": 100.0,
            }
        }
        s2, f2 = _formato_score("ckan", [], inv2, "test_fonte2")
        assert s2 == 90.0
        assert f2 == "computed"

    @pytest.mark.contract
    def test_formato_score_copertura_parziale(self):
        """Asse A: copertura < 50% → parziale, non computed."""
        inv = {
            "openbdap": {
                "total": 3825,
                "con_formato": 940,
                "aperti": 900,
                "perc_aperto": 95.7,
                "copertura": 24.6,
            }
        }
        score, fonte = _formato_score("ckan", [], inv, "openbdap")
        assert score == 90.0
        assert fonte == "parziale"  # non "computed" perche' copertura < 50%

    @pytest.mark.contract
    def test_formato_score_senza_inventory(self):
        """Asse A: senza inventory, usa fallback protocol (pessimista)."""
        score, fonte = _formato_score("ckan", [], None, "ignota")
        assert score == 30.0  # fallback CKAN pessimistico
        assert fonte == "estimated"
        score2, fonte2 = _formato_score("html", [], None, "ignota")
        assert score2 == 35.0  # fallback HTML pessimistico
        assert fonte2 == "estimated"
        # SDMX resta affidabile (sempre XML)
        score3, fonte3 = _formato_score("sdmx", [], None, "ignota")
        assert score3 == 70.0
        assert fonte3 == "estimated"

    @pytest.mark.contract
    def test_formato_score_da_source_check(self):
        """Asse A: source_check primario — formato reale dai probe."""
        # 100% formati aperti, 100% raggiungibili
        sc = {"fonte_aperta": {"perc_aperto": 100.0, "perc_reachable": 100.0}}
        score, fonte = _formato_score("ckan", [], None, "fonte_aperta", sc)
        assert score == 90.0
        assert fonte == "computed"

        # 0% formati aperti (tutto XLSX), 100% raggiungibili
        sc = {"fonte_chiusa": {"perc_aperto": 0.0, "perc_reachable": 100.0}}
        score, fonte = _formato_score("ckan", [], None, "fonte_chiusa", sc)
        assert score == 5.0
        assert fonte == "computed"

        # <30% raggiungibili → penalità forte
        sc = {"fonte_morta": {"perc_aperto": 80.0, "perc_reachable": 20.0}}
        score, fonte = _formato_score("ckan", [], None, "fonte_morta", sc)
        assert score == 10.0  # penalizzato per irraggiungibilità
        assert fonte == "computed"

    @pytest.mark.contract
    def test_raggiungibilita_score_da_source_check(self):
        """Asse B: source_check ha priorita sul radar per file-level reachability."""
        # <20% raggiungibili → score 5
        s, f = _raggiungibilita_score(
            {"status": "GREEN", "http_code": "200"},
            {"f1": {"perc_reachable": 15.0}},
            "f1",
        )
        assert s == 5.0 and f == "computed"
        # <40% → 15
        s, f = _raggiungibilita_score(None, {"f1": {"perc_reachable": 30.0}}, "f1")
        assert s == 15.0 and f == "computed"
        # >=80% → radar normale
        s, f = _raggiungibilita_score(
            {"status": "GREEN", "http_code": "200"},
            {"f1": {"perc_reachable": 90.0}},
            "f1",
        )
        assert s == 70.0 and f == "computed"

    @pytest.mark.contract
    def test_flag_urgenza(self):
        """Flag da source_check e radar."""
        sc = {"mit": {"total": 10, "circuit_open": 7, "formato_aperto": 0, "formato_chiuso": 10}}
        flags = _flag_urgenza("mit", sc, {"red_streak": 5})
        assert "circuit_open_massivo" in flags
        assert "formato_chiuso_completo" in flags
        assert "portale_irraggiungibile" in flags
        # Nessun flag se tutto ok
        sc2 = {"ok": {"total": 10, "circuit_open": 1, "formato_aperto": 8, "formato_chiuso": 2}}
        flags2 = _flag_urgenza("ok", sc2, {"red_streak": 0})
        assert flags2 == []

    @pytest.mark.contract
    def test_build_scores_min_axis(self):
        """Il livello deriva dal minimo degli assi computed, non dalla media."""
        registry = {"fonte_test": {"protocol": "ckan"}}
        # fonte con formato_aperto=5 (carente) ma altri assi OK
        sc = {
            "fonte_test": {
                "total": 10,
                "reachable": 10,
                "circuit_open": 0,
                "formato_aperto": 0,
                "formato_chiuso": 10,
                "formato_ignoto": 0,
                "perc_reachable": 100.0,
                "perc_aperto": 0.0,
            }
        }
        result = build_scores(registry, [], None, {}, {}, sc)
        entry = result["scores"][0]
        # formato_aperto e' 5.0 (computed, carente) → livello deve essere carente
        assert entry["livello"] == "carente", f"livello={entry['livello']}, atteso carente"
        assert "FOIA" in entry["azione_raccomandata"]

    @pytest.mark.contract
    def test_build_scores_estimated_non_tira_giu(self):
        """Assi estimated non possono portare il livello sotto 'medio'."""
        registry = {"fonte_test": {"protocol": "html"}}
        result = build_scores(registry, [], None, {}, {}, {})
        entry = result["scores"][0]
        # Presenza_datigovit e' 50 estimated (soglia debole), ma non deve tirare giu
        # Il livello dovrebbe essere almeno medio perche' estimated e' cap a medio
        assert entry["livello"] in ("medio",), f"livello={entry['livello']}, atteso medio"

    @pytest.mark.contract
    def test_licenza_score_da_inventory(self):
        """Asse C: licenze aperte, other-open, nessuna licenza."""
        # CC-BY
        inv = {
            "f1": {
                "total": 10,
                "licenze_aperte": 10,
                "perc_licenza_aperta": 100.0,
                "has_hvd": False,
            }
        }
        s, f = _licenza_score("ckan", inv, "f1")
        assert s == 85.0 and f == "computed"
        # other-open (deve essere riconosciuto come aperto)
        inv2 = {
            "f2": {"total": 5, "licenze_aperte": 5, "perc_licenza_aperta": 100.0, "has_hvd": False}
        }
        s2, f2 = _licenza_score("ckan", inv2, "f2")
        assert s2 == 85.0 and f2 == "computed"
        # 0 licenze (nessun dato)
        inv3 = {
            "f3": {"total": 10, "licenze_aperte": 0, "perc_licenza_aperta": 0.0, "has_hvd": False}
        }
        s3, f3 = _licenza_score("ckan", inv3, "f3")
        assert s3 == 50.0 and f3 == "estimated"

    @pytest.mark.contract
    def test_hvd_score_da_inventory(self):
        """Asse E: HVD presente, assente, colonna mancante."""
        # HVD presente
        inv = {
            "f1": {"total": 10, "licenze_aperte": 10, "perc_licenza_aperta": 100.0, "has_hvd": True}
        }
        s, f = _hvd_score(inv, "f1")
        assert s == 80.0 and f == "computed"
        # Colonna presente ma nessun HVD
        inv2 = {
            "f2": {"total": 10, "licenze_aperte": 0, "perc_licenza_aperta": 0.0, "has_hvd": False}
        }
        s2, f2 = _hvd_score(inv2, "f2")
        assert s2 == 50.0 and f2 == "computed"
        # Colonna mancante (license_stats=None)
        s3, f3 = _hvd_score(None, "f3")
        assert s3 == 50.0 and f3 == "missing"

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _load_json(path: Path) -> dict | None:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None


class TestBuilderFunctions:
    """Test delle funzioni che aggregano dati in-memory (usate da run_source.py)."""

    # ── _build_source_check_stats ──────────────────────────────────────

    @pytest.mark.pure_unit
    def test_source_check_stats_misto(self):
        """Formati aperti e chiusi, alcuni irraggiungibili."""
        results = [
            {"reachable": True, "resource_format": "CSV", "check_notes": None},
            {"reachable": True, "resource_format": "JSON", "check_notes": None},
            {"reachable": False, "resource_format": "XLSX", "check_notes": "timeout"},
            {"reachable": False, "resource_format": "", "check_notes": "circuit_open"},
        ]
        stats = _build_source_check_stats("fonte", results)
        assert "fonte" in stats
        s = stats["fonte"]
        assert s["total"] == 4
        assert s["reachable"] == 2
        assert s["circuit_open"] == 1
        assert s["formato_aperto"] == 2  # CSV + JSON
        assert s["formato_chiuso"] == 1  # XLSX
        assert s["formato_ignoto"] == 1  # vuoto
        assert s["perc_reachable"] == 50.0
        assert s["perc_aperto"] == 50.0

    @pytest.mark.pure_unit
    def test_source_check_stats_tutti_raggiungibili(self):
        """100% raggiungibili, tutti formati aperti."""
        results = [
            {"reachable": True, "resource_format": "CSV", "check_notes": None},
            {"reachable": True, "resource_format": "JSON", "check_notes": None},
        ]
        stats = _build_source_check_stats("ok", results)
        s = stats["ok"]
        assert s["total"] == s["reachable"] == 2
        assert s["circuit_open"] == 0
        assert s["perc_reachable"] == 100.0
        assert s["perc_aperto"] == 100.0

    @pytest.mark.pure_unit
    def test_source_check_stats_vuoto(self):
        """Lista vuota → total 0, nessun errore."""
        stats = _build_source_check_stats("vuota", [])
        s = stats["vuota"]
        assert s["total"] == 0
        assert s["reachable"] == 0
        assert s["perc_reachable"] == 0.0
        assert s["perc_aperto"] == 0.0

    # ── _build_inventory_stats ─────────────────────────────────────────

    @pytest.mark.pure_unit
    def test_inventory_stats_ckan_only(self):
        """Solo row CKAN contano."""
        rows = [
            {"protocol": "ckan", "format": "CSV"},
            {"protocol": "ckan", "format": "JSON"},
            {"protocol": "sparql", "format": "?"},
            {"protocol": "ckan", "format": "XLSX"},
            {"protocol": "ckan", "format": ""},
        ]
        stats = _build_inventory_stats("fonte", rows)
        assert "fonte" in stats
        s = stats["fonte"]
        assert s["total"] == 4  # solo CKAN
        assert s["con_formato"] == 3  # CSV, JSON, XLSX
        assert s["aperti"] == 2  # CSV, JSON
        assert s["perc_aperto"] == 50.0
        assert s["copertura"] == 75.0

    @pytest.mark.pure_unit
    def test_inventory_stats_vuoto(self):
        """Nessuna row → stats vuoto."""
        stats = _build_inventory_stats("vuota", [])
        assert stats == {}

    # ── _build_license_stats ───────────────────────────────────────────

    @pytest.mark.pure_unit
    def test_license_stats_misto(self):
        """Licenze aperte, HVD, misto."""
        rows = [
            {
                "protocol": "ckan",
                "license_id": "cc-by-4.0",
                "license_title": "Creative Commons",
                "hvd_category": "http://data.europa.eu/bna/c_ac64a52d",
            },
            {
                "protocol": "ckan",
                "license_id": "cc-zero",
                "license_title": "CC0",
                "hvd_category": "",
            },
            {
                "protocol": "ckan",
                "license_id": "other-open",
                "license_title": "Other Open",
                "hvd_category": "",
            },
            {"protocol": "ckan", "license_id": "", "license_title": "", "hvd_category": ""},
            {"protocol": "sparql", "license_id": "", "license_title": "", "hvd_category": ""},
        ]
        stats = _build_license_stats("fonte", rows)
        assert "fonte" in stats
        s = stats["fonte"]
        assert s["total"] == 4  # solo CKAN
        assert s["licenze_aperte"] == 3  # cc-by, cc-zero, other-open
        assert s["perc_licenza_aperta"] == 75.0
        assert s["has_hvd"] is True  # almeno una row con HVD

    @pytest.mark.pure_unit
    def test_license_stats_nessuna_licenza(self):
        """Nessuna licenza aperta, nessun HVD."""
        rows = [
            {"protocol": "ckan", "license_id": "", "license_title": "", "hvd_category": ""},
        ]
        stats = _build_license_stats("fonte", rows)
        s = stats["fonte"]
        assert s["licenze_aperte"] == 0
        assert s["perc_licenza_aperta"] == 0.0
        assert s["has_hvd"] is False

    @pytest.mark.pure_unit
    def test_license_stats_vuoto(self):
        """Nessuna row → stats vuoto."""
        stats = _build_license_stats("vuota", [])
        assert stats == {}

    # ── _datigovit_score ───────────────────────────────────────────────

    @pytest.mark.contract
    def test_datigovit_dati_gov_it(self):
        """Fonte su dati.gov.it → computed."""
        score, fonte = _datigovit_score({"base_url": "https://dati.gov.it/opendata/api/3/action/"})
        assert score == 80.0
        assert fonte == "computed"

    @pytest.mark.contract
    def test_datigovit_api_action(self):
        """Fonte con /api/3/action/ (aggregatore CKAN) → computed."""
        score, fonte = _datigovit_score(
            {"base_url": "https://portalecomune.it/api/3/action/package_list"}
        )
        assert score == 80.0
        assert fonte == "computed"

    @pytest.mark.contract
    def test_datigovit_odapi(self):
        """Fonte con /odapi/ (INPS) → computed."""
        score, fonte = _datigovit_score(
            {"base_url": "https://serviziweb2.inps.it/odapi/package_list"}
        )
        assert score == 80.0
        assert fonte == "computed"

    @pytest.mark.contract
    def test_datigovit_portale_diretto(self):
        """Fonte su portale dedicato → estimated."""
        score, fonte = _datigovit_score({"base_url": "https://dati.terna.it/"})
        assert score == 50.0
        assert fonte == "estimated"

    @pytest.mark.contract
    def test_datigovit_sparql(self):
        """Endpoint SPARQL → estimated."""
        score, fonte = _datigovit_score({"base_url": "https://dati.camera.it/sparql"})
        assert score == 50.0
        assert fonte == "estimated"


class TestLoadSourceCheckStats:
    """Test _load_source_check_stats() con parquet misto (backward compat probe_applicable)."""

    @pytest.mark.pure_unit
    def test_load_source_check_stats_misto(self):
        """NULL legacy trattato come probeabile, False escluso, True incluso."""
        df = pd.DataFrame(
            {
                "source_id": ["fonte"] * 4,
                "reachable": [True, True, True, True],
                "resource_format": ["CSV", "CSV", "JSON", "JSON"],
                "check_notes": [None, None, "probe_skipped", None],
                "probe_applicable": [True, None, False, True],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=True) as tmp:
            df.to_parquet(tmp.name, index=False)
            stats = _load_source_check_stats(Path(tmp.name))
        s = stats["fonte"]
        # Row 0: True → incluso
        # Row 1: NULL → COALESCE True → incluso (legacy)
        # Row 2: False → escluso
        # Row 3: True → incluso
        assert s["total"] == 3, f"atteso 3, ottenuto {s['total']}"
        assert s["reachable"] == 3
        assert s["formato_aperto"] == 3
        assert s["perc_aperto"] == 100.0

    @pytest.mark.pure_unit
    def test_load_source_check_stats_senza_colonna(self):
        """Parquet senza probe_applicable → backward compat: tutti inclusi."""
        df = pd.DataFrame(
            {
                "source_id": ["fonte"] * 2,
                "reachable": [True, True],
                "resource_format": ["CSV", "XLSX"],
                "check_notes": [None, None],
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=True) as tmp:
            df.to_parquet(tmp.name, index=False)
            stats = _load_source_check_stats(Path(tmp.name))
        s = stats["fonte"]
        assert s["total"] == 2
        assert s["reachable"] == 2
        assert s["formato_aperto"] == 1
        assert s["formato_chiuso"] == 1
