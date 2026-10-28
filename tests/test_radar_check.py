"""Test per radar_check.py."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import scripts.radar_check as radar_check

pytestmark = pytest.mark.contract

_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text(encoding="utf-8"))


class TestBuildReport:
    def test_build_status_report_basic(self) -> None:
        registry = {
            "demo_ckan": {
                "base_url": "https://demo.test/api/3/action/package_list",
                "source_kind": "catalog",
                "protocol": "ckan",
                "observation_mode": "catalog-watch",
            },
            "istat_sdmx": {
                "base_url": "https://sdmx.istat.it/rest/",
                "source_kind": "catalog",
                "protocol": "sdmx",
                "observation_mode": "radar-only",
            },
        }
        results = {
            "demo_ckan": radar_check.ProbeResult(
                status="GREEN", http_code="200", content_type="application/json"
            ),
            "istat_sdmx": radar_check.ProbeResult(
                status="YELLOW", http_code="503", note="SDMX retry esaurito"
            ),
        }
        report = radar_check.build_status_report(registry, results, "2026-04-11")
        assert "# Stato Radar" in report
        assert "Ultimo run: 2026-04-11" in report
        assert "Fonti controllate: 2" in report
        assert "GREEN: 1" in report
        assert "YELLOW: 1" in report
        assert "RED: 0" in report
        assert "| demo_ckan |" in report
        assert "| istat_sdmx |" in report
        assert "## Note" in report
        assert "istat_sdmx" in report

    def test_build_radar_summary_schema(self) -> None:
        registry = {
            "demo_ckan": {
                "base_url": "https://demo.test/api/3/action/package_list",
                "source_kind": "catalog",
                "protocol": "ckan",
                "observation_mode": "catalog-watch",
                "datasets_in_use": ["dataset1", "dataset2"],
            },
            "istat_sdmx": {
                "base_url": "https://sdmx.istat.it/rest/",
                "source_kind": "catalog",
                "protocol": "sdmx",
                "observation_mode": "radar-only",
                "datasets_in_use": [],
            },
            "ssl_fonte": {
                "base_url": "https://ssl-broken.test/",
                "source_kind": "source",
                "protocol": "html",
                "observation_mode": "radar-only",
            },
        }
        results = {
            "demo_ckan": radar_check.ProbeResult(
                status="GREEN", http_code="200", content_type="application/json"
            ),
            "istat_sdmx": radar_check.ProbeResult(status="YELLOW", http_code="-", note="Timeout"),
            "ssl_fonte": radar_check.ProbeResult(
                status="GREEN",
                http_code="200",
                note="SSL verify failed; fallback verify=False used (SSLError)",
                ssl_fallback_used=True,
            ),
        }
        summary, sources_list = radar_check.build_radar_summary(registry, results, "2026-04-18")
        schema = _load_schema("radar_summary.schema.json")
        jsonschema.validate(instance=summary, schema=schema)
        # Verify sources_list mirrors summary.sources
        assert len(sources_list) == summary["sources_total"]
        # Verify SSL issue is captured
        ssl_src = next(s for s in summary["sources"] if s["id"] == "ssl_fonte")
        assert ssl_src.get("ssl_issue") is True
        assert ssl_src.get("ssl_fallback_used") is True
        # Verify non-SSL source does NOT have ssl_issue
        clean_src = next(s for s in summary["sources"] if s["id"] == "demo_ckan")
        assert clean_src.get("ssl_issue") is None or clean_src.get("ssl_issue") is False
        assert clean_src.get("ssl_fallback_used") is False

    def test_build_radar_summary_ssl_streak(self) -> None:
        """SSL streak counts consecutive probes with ssl_fallback_used."""
        registry = {
            "ssl_fonte": {
                "base_url": "https://ssl-broken.test/",
                "source_kind": "source",
                "protocol": "html",
                "observation_mode": "radar-only",
            },
        }
        # History: last 3 probes all had SSL issue
        history = {
            "probes": [
                {
                    "probe_date": "2026-04-15",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": True}],
                },
                {
                    "probe_date": "2026-04-16",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": True}],
                },
                {
                    "probe_date": "2026-04-17",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": True}],
                },
            ]
        }
        results = {
            "ssl_fonte": radar_check.ProbeResult(
                status="GREEN",
                http_code="200",
                note="SSL verify failed; fallback verify=False used (SSLError)",
                ssl_fallback_used=True,
            ),
        }
        summary, sources_list = radar_check.build_radar_summary(
            registry, results, "2026-04-18", history
        )
        ssl_src = next(s for s in summary["sources"] if s["id"] == "ssl_fonte")
        # 3 history consecutive SSL probe (current non contato in streak, ma segnalato da ssl_issue)
        assert ssl_src.get("ssl_streak") == 3
        assert ssl_src.get("ssl_issue") is True

    def test_build_radar_summary_ssl_streak_break(self) -> None:
        """SSL streak resets after a probe without SSL issue."""
        registry = {
            "ssl_fonte": {
                "base_url": "https://ssl-ok-now.test/",
                "source_kind": "source",
                "protocol": "html",
                "observation_mode": "radar-only",
            },
        }
        # History: first 2 had SSL, probe 3 did NOT → streak should reset
        history = {
            "probes": [
                {
                    "probe_date": "2026-04-15",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": True}],
                },
                {
                    "probe_date": "2026-04-16",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": True}],
                },
                {
                    "probe_date": "2026-04-17",
                    "sources": [{"id": "ssl_fonte", "ssl_fallback_used": False}],
                },
            ]
        }
        results = {
            "ssl_fonte": radar_check.ProbeResult(
                status="GREEN",
                http_code="200",
                ssl_fallback_used=False,
            ),
        }
        summary, sources_list = radar_check.build_radar_summary(
            registry, results, "2026-04-18", history
        )
        ssl_src = next(s for s in summary["sources"] if s["id"] == "ssl_fonte")
        # Current has no SSL → streak = 0 → no ssl_streak field
        assert ssl_src.get("ssl_streak") is None
        assert ssl_src.get("ssl_issue") is None or ssl_src.get("ssl_issue") is False
