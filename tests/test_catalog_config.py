"""Test per scripts/catalog/config.py — loader [tool.observatory] da pyproject."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.catalog.config import (
    ObservatoryConfigError,
    load_observatory_config,
    validate_observatory_config,
)


def _write_pyproject(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ── validate_observatory_config (dict-level) ─────────────────────────────────


class TestValidateObservatoryConfig:
    @pytest.mark.pure_unit
    def test_minimal_valid(self):
        cfg = validate_observatory_config(
            {
                "source_id": "eurostat",
                "protocol": "sdmx",
                "base_url": "https://example.test/sdmx/dataflow/ESTAT",
            }
        )
        assert cfg["source_id"] == "eurostat"
        assert cfg["protocol"] == "sdmx"
        assert cfg["observation_mode"] == "catalog-watch"
        assert cfg["source_kind"] == "catalog"

    @pytest.mark.pure_unit
    def test_missing_required_keys(self):
        with pytest.raises(ObservatoryConfigError, match="missing required keys"):
            validate_observatory_config({"source_id": "x", "protocol": "ckan"})

    @pytest.mark.pure_unit
    def test_unsupported_protocol(self):
        with pytest.raises(ObservatoryConfigError, match="unsupported protocol"):
            validate_observatory_config(
                {
                    "source_id": "x",
                    "protocol": "ftp",
                    "base_url": "ftp://example.test",
                }
            )

    @pytest.mark.pure_unit
    def test_invalid_observation_mode(self):
        with pytest.raises(ObservatoryConfigError, match="invalid observation_mode"):
            validate_observatory_config(
                {
                    "source_id": "x",
                    "protocol": "ckan",
                    "base_url": "https://example.test",
                    "observation_mode": "vibes",
                }
            )

    @pytest.mark.pure_unit
    def test_invalid_verdict(self):
        with pytest.raises(ObservatoryConfigError, match="invalid verdict"):
            validate_observatory_config(
                {
                    "source_id": "x",
                    "protocol": "ckan",
                    "base_url": "https://example.test",
                    "verdict": "maybe",
                }
            )

    @pytest.mark.pure_unit
    def test_toolkit_extends_mismatch(self):
        with pytest.raises(ObservatoryConfigError, match="does not match"):
            validate_observatory_config(
                {
                    "source_id": "eurostat",
                    "protocol": "sdmx",
                    "base_url": "https://example.test",
                },
                toolkit_source_id="altro",
            )

    @pytest.mark.pure_unit
    def test_toolkit_extends_match_ok(self):
        cfg = validate_observatory_config(
            {
                "source_id": "eurostat",
                "protocol": "sdmx",
                "base_url": "https://example.test",
            },
            toolkit_source_id="eurostat",
        )
        assert cfg["source_id"] == "eurostat"

    @pytest.mark.pure_unit
    def test_passthrough_protocol_blocks(self):
        cfg = validate_observatory_config(
            {
                "source_id": "x",
                "protocol": "sparql",
                "base_url": "https://example.test/sparql",
                "inventory": {"timeout": 60},
                "catalog_baseline": {"value": 100, "method": "count"},
                "sparql": {"query": "SELECT * WHERE {?s ?p ?o}"},
            }
        )
        assert cfg["inventory"] == {"timeout": 60}
        assert cfg["catalog_baseline"] == {"value": 100, "method": "count"}
        assert cfg["sparql"] == {"query": "SELECT * WHERE {?s ?p ?o}"}


# ── load_observatory_config (file-level) ─────────────────────────────────────


class TestLoadObservatoryConfig:
    @pytest.mark.pure_unit
    def test_load_full_section(self, tmp_path: Path):
        _write_pyproject(
            tmp_path,
            """
[project]
name = "demo"

[tool.observatory]
source_id = "demo_src"
protocol = "ckan"
base_url = "https://example.test/api/3/action/package_list"
verdict = "go"
note = "demo"

[tool.observatory.inventory]
timeout = 120
""",
        )
        cfg = load_observatory_config(tmp_path)
        assert cfg["source_id"] == "demo_src"
        assert cfg["verdict"] == "go"
        assert cfg["inventory"] == {"timeout": 120}

    @pytest.mark.pure_unit
    def test_missing_section(self, tmp_path: Path):
        _write_pyproject(tmp_path, "[project]\nname = 'demo'\n")
        with pytest.raises(ObservatoryConfigError, match="section not found"):
            load_observatory_config(tmp_path)

    @pytest.mark.pure_unit
    def test_missing_pyproject(self, tmp_path: Path):
        with pytest.raises(ObservatoryConfigError, match="not found"):
            load_observatory_config(tmp_path)

    @pytest.mark.pure_unit
    def test_cross_check_toolkit_extends(self, tmp_path: Path):
        _write_pyproject(
            tmp_path,
            """
[tool.observatory]
source_id = "eurostat"
protocol = "sdmx"
base_url = "https://example.test"

[tool.toolkit.extends]
source_id = "eurostat"
""",
        )
        cfg = load_observatory_config(tmp_path)
        assert cfg["source_id"] == "eurostat"

    @pytest.mark.pure_unit
    def test_cross_check_mismatch_raises(self, tmp_path: Path):
        _write_pyproject(
            tmp_path,
            """
[tool.observatory]
source_id = "eurostat"
protocol = "sdmx"
base_url = "https://example.test"

[tool.toolkit.extends]
source_id = "altro"
""",
        )
        with pytest.raises(ObservatoryConfigError, match="does not match"):
            load_observatory_config(tmp_path)
