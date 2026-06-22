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

from scripts.build_compliance_scores import build_scores


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
