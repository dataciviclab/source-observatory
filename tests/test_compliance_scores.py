"""Smoke test per build_compliance_scores.py.

Verifica che lo script produca output valido con dati reali.
Non e' un test unitario — e' un test di integrazione minimo
che protegge il contratto verso data-advocacy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _constants import CATALOG_SIGNALS_PATH, RADAR_SUMMARY_PATH, REGISTRY_PATH

from scripts.build_compliance_scores import (
    _formato_score,
    _hvd_score,
    _licenza_score,
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
        inv = {"test_fonte": {"total": 10, "aperti": 7, "perc_aperto": 70.0}}
        score, fonte = _formato_score("ckan", [], inv, "test_fonte")
        assert score == 55.0
        assert fonte == "computed"
        # 100% aperti
        inv2 = {"test_fonte2": {"total": 5, "aperti": 5, "perc_aperto": 100.0}}
        s2, f2 = _formato_score("ckan", [], inv2, "test_fonte2")
        assert s2 == 90.0
        assert f2 == "computed"

    @pytest.mark.contract
    def test_formato_score_senza_inventory(self):
        """Asse A: senza inventory, usa fallback protocol."""
        score, fonte = _formato_score("ckan", [], None, "ignota")
        assert score == 75.0  # fallback CKAN
        assert fonte == "computed"
        score2, fonte2 = _formato_score("html", [], None, "ignota")
        assert score2 == 50.0  # fallback HTML

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
