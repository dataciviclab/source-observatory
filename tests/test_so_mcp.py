from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

import pandas as pd  # must be before so_server_core import

# Force-load local so_server_core bypassing pip-installed mcp package
SO_MCP_PATH = Path(__file__).resolve().parents[1] / "mcp" / "so_server_core.py"
_spec = importlib.util.spec_from_file_location("mcp.so_server_core", SO_MCP_PATH)
assert _spec and _spec.loader
_so_server_core = importlib.util.module_from_spec(_spec)
sys.modules["mcp.so_server_core"] = _so_server_core
_spec.loader.exec_module(_so_server_core)
core = _so_server_core

import duckdb  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _use_local_artifacts(monkeypatch) -> None:
    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "local")


def _write_parquet(path, rows: list[dict]) -> None:
    con = duckdb.connect()
    try:
        con.register("rows_df", pd.DataFrame(rows))
        con.execute(f"COPY rows_df TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_query_inventory_filters_and_orders(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "low", "intake_score": 20},
            {"source_id": "a", "item_id": "high", "intake_score": 55},
            {"source_id": "b", "item_id": "other", "intake_score": 90},
        ],
    )
    monkeypatch.setattr(core, "_CHECK_PARQUET", parquet_path)

    result = core.query_inventory(source_id="a", min_score=40, limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "high"
    assert result["filters"]["source_id"] == "a"
    assert result["filters"]["min_score"] == 40
    assert result["filters"]["limit"] == 10
    assert result["cache"]["source"] == "local_cache"
    assert result["cache"]["source_of_truth"] == "GitHub Actions artifact or configured GCS prefix"
    assert result["cache"]["stale"] is False


def test_query_inventory_reads_gcs_when_configured(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [{"source_id": "gcs_src", "item_id": "remote", "intake_score": 80}],
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size):
            yield parquet_path.read_bytes()

    def fake_get(url, **kwargs):
        assert url == "https://storage.googleapis.com/bucket/source-check/source_check_results.parquet"
        return FakeResponse()

    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "gcs")
    monkeypatch.setenv("CATALOG_INVENTORY_GCS_PREFIX", "gs://bucket")
    monkeypatch.setattr(core.requests, "get", fake_get)

    result = core.query_inventory(source_id="gcs_src", limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "remote"
    assert result["cache"]["source"] == "gcs"
    assert result["cache"]["uri"] == "gs://bucket/source-check/source_check_results.parquet"
    assert result["cache"]["stale"] is False


def test_query_signals_filters_and_limits(tmp_path, monkeypatch) -> None:
    signals_path = tmp_path / "catalog_signals.json"
    signals_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-04-30T00:00:00+00:00",
                "signals": [
                    {"source": "a", "signal_type": "one"},
                    {"source": "b", "signal_type": "two"},
                    {"source": "a", "signal_type": "three"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "_SIGNALS_JSON", signals_path)

    result = core.query_signals(source_id="a", limit=1)

    assert result["captured_at"] == "2026-04-30T00:00:00+00:00"
    assert result["returned"] == 1
    assert result["signals"][0]["signal_type"] == "three"


def test_radar_summary_filters_source(tmp_path, monkeypatch) -> None:
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-30T00:00:00+00:00",
                "probe_date": "2026-04-30",
                "sources_total": 2,
                "status_counts": {"GREEN": 1, "RED": 1},
                "sources": [
                    {"id": "a", "status": "GREEN"},
                    {"id": "b", "status": "RED"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "_RADAR_JSON", radar_path)

    result = core.radar_summary(source_id="b")

    assert result["status_counts"] == {"GREEN": 1, "RED": 1}
    assert result["returned"] == 1
    assert result["sources"][0]["status"] == "RED"


def test_inventory_status_summarizes_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-04-30T00:00:00+00:00",
                "registry_path": "data/radar/sources_registry.yaml",
                "sources": {
                    "a": {"status": "ok", "protocol": "ckan", "rows": 10},
                    "b": {"status": "error", "protocol": "sdmx", "error": "HTTP 500"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "_INVENTORY_REPORT", report_path)

    summary = core.inventory_status()
    filtered = core.inventory_status(source_id="b")

    assert summary["status_counts"] == {"ok": 1, "error": 1}
    assert summary["rows_total"] == 10
    assert filtered["source"]["error"] == "HTTP 500"


def test_catalog_inventory_search_filters_rows(tmp_path, monkeypatch) -> None:
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "openbdap",
                "protocol": "ckan",
                "item_id": "a",
                "item_name": "dipendenti",
                "title": "Dipendenti pubblici",
                "organization": "MEF",
                "tags": "personale",
                "notes_excerpt": "",
                "landing_page": "https://example.test/a",
                "distribution_url": "",
                "format": "CSV",
                "source_status": "",
                "inventory_method": "package_search",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
                "civic_priority": "high",
                "topic": "",
                "theme": "",
            },
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "b",
                "item_name": "pensioni",
                "title": "Pensioni",
                "organization": "INPS",
                "tags": "",
                "notes_excerpt": "",
                "landing_page": "",
                "distribution_url": "",
                "format": "",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
                "civic_priority": "",
                "topic": "",
                "theme": "",
            },
        ],
    )
    monkeypatch.setattr(core, "_INVENTORY_PARQUET", inventory_path)

    result = core.catalog_inventory_search("dipendenti", source_id="openbdap")

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "a"


def test_portal_candidates_filters_protocol(tmp_path, monkeypatch) -> None:
    """portal_candidates rimosso dal core MCP — test mantenuto per riferimento."""
    pass


def test_probe_url_rejects_invalid_url() -> None:
    result = core.probe_url("not-a-url")

    assert result["is_reachable"] is False
    assert result["error"] == "invalid_url"


def test_discover_sdmx_reads_inventory(tmp_path, monkeypatch) -> None:
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "istat_sdmx",
                "item_id": "DF_PREZZI",
                "item_name": "DF_PREZZI",
                "title": "Indice dei prezzi agricoli",
                "tags": "prezzi, agricoltura",
                "api_base_url": "https://example.test/rest",
                "source_url": "https://example.test/rest/dataflow/IT1",
            },
            {
                "source_id": "openbdap",
                "item_id": "other",
                "item_name": "other",
                "title": "Other",
                "tags": "",
                "api_base_url": "https://example.test/api",
                "source_url": "https://example.test/api/3/action/package_search",
            },
        ],
    )
    monkeypatch.setattr(core, "_INVENTORY_PARQUET", inventory_path)

    result = core.discover_sdmx(["prezzi"], limit=5)

    assert result["artifact"].endswith("catalog_inventory_latest.parquet")
    assert result["returned"] == 1
    assert result["dataflows"][0]["item_id"] == "DF_PREZZI"
    assert result["dataflows"][0]["relevance_score"] > 0


def test_discover_sdmx_reports_missing_source_from_inventory_report(tmp_path, monkeypatch) -> None:
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    report_path = tmp_path / "catalog_inventory_report.json"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "openbdap",
                "item_id": "other",
                "item_name": "other",
                "title": "Other",
                "tags": "",
                "api_base_url": "https://example.test/api",
                "source_url": "https://example.test/api/3/action/package_search",
            },
        ],
    )
    report_path.write_text(
        json.dumps(
            {
                "sources": {
                    "istat_sdmx": {
                        "status": "error",
                        "protocol": "sdmx",
                        "error": "HTTP 500",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "_INVENTORY_PARQUET", inventory_path)
    monkeypatch.setattr(core, "_INVENTORY_REPORT", report_path)

    result = core.discover_sdmx(["prezzi"], limit=5)

    assert result["error"] == "source_unavailable"
    assert result["source_status"]["error"] == "HTTP 500"
    assert result["dataflows"] == []
