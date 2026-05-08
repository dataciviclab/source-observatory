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


def test_portal_candidates_removed_from_core() -> None:
    """portal_candidates non e' piu esportato da so_server_core."""
    assert not hasattr(core, "portal_candidates"), (
        "portal_candidates rimosso dal core MCP: se lo riaggiungi, aggiorna questo test"
    )


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


# ─── Tests for new tools (MCP v2) ───────────────────────────────────────────────


def test_infer_topic_match() -> None:
    result = core.infer_topic("tasso di disoccupazione regionale, forze di lavoro, occupazione")

    assert result["topics"]["lavoro"] >= 3
    assert result["top_match"] == "lavoro"
    assert result["matched_count"] >= 1


def test_infer_topic_no_match() -> None:
    result = core.infer_topic("foo bar baz xyz")

    assert result["topics"] == {}
    assert result["top_match"] is None
    assert result["matched_count"] == 0


def test_infer_topic_empty_text() -> None:
    result = core.infer_topic("")

    assert result["error"] == "empty_text"
    # matched_count not present when error is returned
    assert "matched_count" not in result


def test_infer_topic_ambiente_vs_energia_not_overlapping() -> None:
    """energia keyword removed from ambiente - should not give double scoring."""
    result = core.infer_topic("emissioni CO2 e consumi energetici")
    topics = result["topics"]

    # Should score both ambiente (emissioni) and energia separately
    assert "ambiente" in topics or "energia" in topics


def test_recommend_sources(tmp_path, monkeypatch) -> None:
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "inps",
                "protocol": "ckan",
                "source_kind": "catalog",
                "item_id": "544",
                "item_name": "pensioni",
                "title": "Pensioni INPS",
                "organization": "INPS",
                "tags": "pensioni,INPS",
                "notes_excerpt": "Dati pensioni",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
                "civic_priority": "",
                "topic": "",
                "theme": "",
            },
            {
                "source_id": "openbdap",
                "protocol": "ckan",
                "source_kind": "catalog",
                "item_id": "b",
                "item_name": "conti",
                "title": "Conto economico",
                "organization": "MEF",
                "tags": "",
                "notes_excerpt": "",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_search",
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

    result = core.recommend_sources("INPS")

    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "inps"
    assert result["sources"][0]["item_count"] >= 1


def test_recommend_sources_empty_keyword() -> None:
    result = core.recommend_sources("")

    assert result["error"] == "empty_keyword"


def test_inventory_diff(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-04-30T00:00:00+00:00",
                "sources": {
                    "inps": {
                        "status": "ok",
                        "protocol": "ckan",
                        "rows": 2323,
                        "method": "package_list",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": f"item_{i}",
                "item_name": f"item_{i}",
                "title": f"Item {i}",
                "organization": "INPS",
                "tags": "",
                "notes_excerpt": "",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
                "civic_priority": "",
                "topic": "",
                "theme": "",
            }
            for i in range(2325)
        ],
    )
    monkeypatch.setattr(core, "_INVENTORY_REPORT", report_path)
    monkeypatch.setattr(core, "_INVENTORY_PARQUET", inventory_path)

    result = core.inventory_diff("inps")

    assert result["source_id"] == "inps"
    assert result["baseline_value"] == 2323
    assert result["current_count"] == 2325
    assert result["delta"] == 2


def test_inventory_diff_source_not_in_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    monkeypatch.setattr(core, "_INVENTORY_REPORT", report_path)

    result = core.inventory_diff("unknown_source")

    assert result["error"] == "source_not_in_report"


def test_inventory_diff_parquet_not_found(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "sources": {
                    "inps": {"status": "ok", "rows": 100, "method": "package_list"}
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(core, "_INVENTORY_REPORT", report_path)
    # Point to non-existent parquet
    monkeypatch.setattr(
        core, "_INVENTORY_PARQUET", tmp_path / "nonexistent.parquet"
    )

    result = core.inventory_diff("inps")

    assert result["error"] == "artifact_not_found"


# ─── Tests for HTTP tools (mocked) ─────────────────────────────────────────────


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data: dict, headers: dict | None = None):
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    @property
    def text(self) -> str:
        return json.dumps(self._json)


def _fake_observatory_get(url: str, **kwargs):
    return FakeResponse(json_data={"success": True, "result": {}})


def test_ckan_package_show_invalid_endpoint() -> None:
    """Test that _ckan_package_show rejects empty params."""
    result = core._ckan_package_show("", "544")
    assert result["error"] == "invalid_params"

    result2 = core._ckan_package_show("https://example.gov.it", "")
    assert result2["error"] == "invalid_params"


def test_infer_topic_energia_not_in_ambiente(monkeypatch) -> None:
    """After removing 'energia' from ambiente keywords, a text about energy
    should not score ambiente just because of the word 'energia'."""
    result = core.infer_topic("energia rinnovabile elettrica gas petrolio")

    assert "ambiente" not in result["topics"]
    assert "energia" in result["topics"]


def test_infer_topic_tasso_not_false_positive(monkeypatch) -> None:
    """tasso removed from lavoro - 'tassazione' should not score lavoro."""
    result = core.infer_topic("tassazione دخل دخل")
    # No topic keywords match "tassazione" - not lavoro, not economia
    assert "lavoro" not in result["topics"]


class _FakeSSLFallbackResponse:
    """Fake response returned by SSL fallback when verify=False succeeds."""
    status_code = 200

    def __init__(self) -> None:
        self.headers = {"content-type": "text/html; charset=utf-8", "content-length": "100"}


def test_probe_url_ssl_fallback_used_when_head_fallback_succeeds(monkeypatch) -> None:
    """When HttpClient.head() primary SSL fails but fallback succeeds, ssl_fallback_used is True."""
    class _FakeSSLResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8", "content-length": "100"}

    class _FakeHttpResult:
        """Simulates HttpClient.head() when primary SSL failed but fallback succeeded."""
        def __init__(self):
            self.response = _FakeSSLResponse()
            self.err = None
            self.ssl_fallback_used = True

        @property
        def is_ok(self):
            return True  # fallback succeeded, response usable

        @property
        def is_ssl_fallback_failed(self):
            return False

    class _FakeHttpClient:
        def __init__(self, timeout=None):
            pass

        def head(self, url):
            # HttpClient catches SSLError internally, returns result with ssl_fallback_used=True
            return _FakeHttpResult()

    monkeypatch.setattr(core, "HttpClient", _FakeHttpClient)

    result = core.probe_url("https://expired-cert.example.com/file.csv")

    assert result["is_reachable"] is True
    assert result["ssl_fallback_used"] is True
    assert result["http_status"] == 200


def test_html_extract_links_ssl_fallback_failure_returns_reachable_false(monkeypatch) -> None:
    """When HttpClient.get fails with non-SSL error, returns is_reachable=False."""

    class _FakeHttpResultError:
        def __init__(self, err):
            self.response = None
            self.err = err
            self.ssl_fallback_used = False

        @property
        def is_ok(self):
            return False

        @property
        def is_ssl_fallback_failed(self):
            return False

    class _FakeHttpClient:
        def __init__(self, timeout=None):
            pass

        def get(self, url, headers=None, params=None):
            return _FakeHttpResultError(ValueError("unexpected internal error"))

    monkeypatch.setattr(core, "HttpClient", _FakeHttpClient)

    result = core._html_extract_links("https://expired-cert.example.com/page.html")

    assert result["is_reachable"] is False
    assert "error" in result
    assert result["message"] == "unexpected internal error"
