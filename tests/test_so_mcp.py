from __future__ import annotations

import json

import duckdb  # noqa: E402
import pandas as pd  # must be before duckdb
import pytest

from so_mcp import _artifact
from so_mcp._discovery import list_source_items
from so_mcp._find_url import find_by_url
from so_mcp._inventory import (
    _source_radar_context,
    catalog_inventory_search,
    inventory_diff,
    inventory_status,
    query_inventory,
)
from so_mcp._radar import radar_history, radar_summary
from so_mcp._recommend import recommend_sources
from so_mcp._registry import registry_query
from so_mcp._signals import query_signals

pytestmark = pytest.mark.contract


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
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)

    result = query_inventory(source_id="a", min_score=40, limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "high"
    assert result["filters"]["source_id"] == "a"
    assert result["filters"]["min_score"] == 40
    assert result["filters"]["limit"] == 10
    assert result["cache"]["source"] == "local_cache"
    assert result["cache"]["source_of_truth"] == "GitHub Actions artifact or configured GCS prefix"
    assert result["cache"]["stale"] is False


def test_query_inventory_falls_back_to_local_when_remote_unreachable(tmp_path, monkeypatch) -> None:
    """Parquet con auto backend, S3 non raggiungibile → fallback a locale."""
    parquet_path = _artifact._CHECK_PARQUET
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet(
        parquet_path,
        [{"source_id": "local_src", "item_id": "cached", "intake_score": 80}],
    )

    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "auto")
    monkeypatch.setenv("CATALOG_INVENTORY_GCS_PREFIX", "gs://any-bucket")
    # Simula S3 non raggiungibile
    monkeypatch.setattr(_artifact, "_probe_s3_parquet", lambda _: False)

    result = query_inventory(source_id="local_src", limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "cached"
    assert result["cache"]["source"] == "local_cache"


def test_resolved_parquet_gcs_direct_no_download(monkeypatch) -> None:
    """Parquet artifact con GCS backend → S3 URI diretto, nessun download."""
    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "gcs")
    monkeypatch.setenv("CATALOG_INVENTORY_GCS_PREFIX", "gs://test-bucket")

    artifact = _artifact._source_check_parquet()
    with _artifact._resolved_parquet(artifact) as (path, cache):
        assert cache["source"] == "gcs_direct"
        assert str(path) == "s3://test-bucket/source-check/source_check_results.parquet"
        assert "S3" in cache["note"]


def test_gs_to_s3_conversion() -> None:
    """_gs_to_s3 converte correttamente URI."""
    assert _artifact._gs_to_s3("gs://bucket/key.parquet") == "s3://bucket/key.parquet"
    assert (
        _artifact._gs_to_s3("gs://dataciviclab-clean/source-check/check.parquet")
        == "s3://dataciviclab-clean/source-check/check.parquet"
    )


def test_direct_cache_info() -> None:
    """_direct_cache_info restituisce source gcs_direct con URI."""
    info = _artifact._direct_cache_info("s3://bucket/test.parquet")
    assert info["source"] == "gcs_direct"
    assert info["uri"] == "s3://bucket/test.parquet"
    assert "S3" in info["note"]


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
    monkeypatch.setattr(_artifact, "_SIGNALS_JSON", signals_path)

    result = query_signals(source_id="a", limit=1)

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
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = radar_summary(source_id="b")

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
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    summary = inventory_status()
    filtered = inventory_status(source_id="b")

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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = catalog_inventory_search("dipendenti", source_id="openbdap")

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "a"


# ─── Tests for new tools (MCP v2) ───────────────────────────────────────────────


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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = recommend_sources("INPS")

    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "inps"
    assert result["sources"][0]["item_count"] >= 1
    assert result["total_items_in_inventory"] == 2  # inps + openbdap in test data


def test_recommend_sources_empty_keyword() -> None:
    result = recommend_sources("")

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
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = inventory_diff("inps")

    assert result["source_id"] == "inps"
    assert result["baseline_value"] == 2323
    assert result["current_count"] == 2325
    assert result["delta"] == 2


def test_inventory_diff_source_not_in_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    result = inventory_diff("unknown_source")

    assert result["error"] == "source_not_in_report"


def test_inventory_diff_parquet_not_found(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps({"sources": {"inps": {"status": "ok", "rows": 100, "method": "package_list"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    # Point to non-existent parquet
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", tmp_path / "nonexistent.parquet")

    result = inventory_diff("inps")

    assert result["error"] == "artifact_not_found"


# ─── _source_radar_context tests (GAP-7: real radar_summary.json schema) ────


def test_source_radar_context_red(tmp_path, monkeypatch) -> None:
    """RED source with red_streak returns contesto giorni."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"id": "dati_salute", "status": "RED", "red_streak": 14},
                    {"id": "istat_sdmx", "status": "GREEN"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = _source_radar_context("dati_salute")
    assert result is not None
    assert "RED" in result
    assert "14 giorni" in result


def test_source_radar_context_green(tmp_path, monkeypatch) -> None:
    """GREEN source returns status=GREEN."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"id": "istat_sdmx", "status": "GREEN"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = _source_radar_context("istat_sdmx")
    assert result == "status=GREEN"


def test_source_radar_context_unknown_source(tmp_path, monkeypatch) -> None:
    """Source not in radar returns None."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(json.dumps({"sources": []}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = _source_radar_context("unknown_source")
    assert result is None


def test_source_radar_context_no_file(tmp_path, monkeypatch) -> None:
    """No radar file returns None."""
    monkeypatch.setattr(_artifact, "_RADAR_JSON", tmp_path / "nonexistent.json")
    result = _source_radar_context("dati_salute")
    assert result is None


# ─── Tests for HTTP tools (mocked) ─────────────────────────────────────────────


def _write_source_check_parquet(path, rows: list[dict]) -> None:
    """Write minimal columns matching source_check_results schema."""
    _write_parquet(path, rows)


def _write_catalog_inventory_parquet(path, rows: list[dict]) -> None:
    """Write minimal columns matching catalog_inventory schema."""
    _write_parquet(path, rows)


def test_find_by_url_finds_by_url_in_source_check(tmp_path, monkeypatch) -> None:
    """Search by download URL in source_check_results."""
    check_path = tmp_path / "source_check_results.parquet"
    _write_source_check_parquet(
        check_path,
        [
            {
                "url": "https://inps.example/download/PENSIONI-2024.csv",
                "url_checked": "",
                "item_id": "id1",
            },
            {"url": "https://inps.example/download/ALTRO.csv", "url_checked": "", "item_id": "id2"},
        ],
    )
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(inv_path, [{"dummy": 0}])
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = find_by_url("PENSIONI-2024.csv")

    assert result["query_url"] == "PENSIONI-2024.csv"
    assert len(result["source_check_results"]) == 1
    assert result["source_check_results"][0]["item_id"] == "id1"


def test_find_by_url_finds_by_item_name_in_inventory(tmp_path, monkeypatch) -> None:
    """Search by item_name should match in catalog_inventory expanded columns."""
    check_path = tmp_path / "source_check_results.parquet"
    _write_source_check_parquet(check_path, [{"url": "", "url_checked": "", "item_id": "none"}])
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(
        inv_path,
        [
            {
                "source_id": "inps",
                "item_id": "ID-5257",
                "item_name": "Pensioni erogate 2024",
                "title": "Pensioni INPS per regione",
                "landing_page": "https://inps.example/dataset/5257",
                "distribution_url": "",
                "source_url": "",
                "notes_excerpt": "Dati sulle pensioni erogate",
                "tags": "",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    # Search by item_name substring
    result = find_by_url("Pensioni erogate")

    assert len(result["catalog_inventory"]) == 1
    assert result["catalog_inventory"][0]["item_id"] == "ID-5257"


def test_find_by_url_finds_by_item_id_in_inventory(tmp_path, monkeypatch) -> None:
    """Search by item_id should match in catalog_inventory expanded columns."""
    check_path = tmp_path / "source_check_results.parquet"
    _write_source_check_parquet(check_path, [{"url": "", "url_checked": "", "item_id": "none"}])
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(
        inv_path,
        [
            {
                "source_id": "inps",
                "item_id": "ID-5257",
                "item_name": "Pensioni",
                "title": "Pensioni INPS",
                "landing_page": "",
                "distribution_url": "",
                "source_url": "",
                "notes_excerpt": "",
                "tags": "",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = find_by_url("ID-5257")

    assert len(result["catalog_inventory"]) == 1
    assert result["catalog_inventory"][0]["item_name"] == "Pensioni"


def test_find_by_url_returns_empty_when_no_match(tmp_path, monkeypatch) -> None:
    """No match should return empty lists, not errors."""
    check_path = tmp_path / "source_check_results.parquet"
    _write_source_check_parquet(
        check_path,
        [{"url": "https://example.test/other.csv", "url_checked": "", "item_id": "none"}],
    )
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(
        inv_path, [{"item_id": "other", "item_name": "Other", "title": "Other"}]
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = find_by_url("nonexistent-filename.csv")

    assert result["source_check_results"] == []
    assert result["catalog_inventory"] == []
    assert "source_check_error" not in result
    assert "catalog_inventory_error" not in result


def test_find_by_url_rejects_empty_url() -> None:
    result = find_by_url("")
    assert result["error"] == "empty_url"


# ---------------------------------------------------------------------------
# Radar edge cases: radar_history
# ---------------------------------------------------------------------------


def test_radar_history_file_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", tmp_path / "radar_history.json")
    result = radar_history(source_id="test", limit=5)
    assert result["error"] == "artifact_not_found"


def test_radar_history_probes_not_a_list(tmp_path, monkeypatch) -> None:
    path = tmp_path / "radar_history.json"
    path.write_text(json.dumps({"probes": "not_a_list"}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", path)
    result = radar_history()
    assert result["returned"] == 0
    assert result["probes_in_window"] == 0


def test_radar_history_limit_clamping(tmp_path, monkeypatch) -> None:
    path = tmp_path / "radar_history.json"
    probes = [
        {"probe_date": f"2024-01-{d:02d}", "sources": [{"id": "s1", "status": "GREEN"}]}
        for d in range(1, 31)
    ]
    path.write_text(json.dumps({"probes": probes}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", path)
    # Over-limit: clamped to 20
    result = radar_history(limit=100)
    assert result["probes_in_window"] == 20
    # Under-limit: negative → clamped to 1
    result2 = radar_history(limit=-3)
    assert result2["probes_in_window"] == 1


def test_radar_history_filter_by_source(tmp_path, monkeypatch) -> None:
    path = tmp_path / "radar_history.json"
    probes = [
        {
            "probe_date": "2024-01-01",
            "sources": [{"id": "s1", "status": "GREEN"}, {"id": "s2", "status": "RED"}],
        },
        {
            "probe_date": "2024-01-08",
            "sources": [{"id": "s1", "status": "RED"}, {"id": "s2", "status": "GREEN"}],
        },
    ]
    path.write_text(json.dumps({"probes": probes}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", path)
    result = radar_history(source_id="s1", limit=10)
    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "s1"
    assert result["sources"][0]["recent_red_count"] == 1


# ---------------------------------------------------------------------------
# Registry edge cases
# ---------------------------------------------------------------------------


def test_registry_query_file_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_artifact, "_REGISTRY_YAML", tmp_path / "sources_registry.yaml")
    result = registry_query()
    assert result["error"] == "artifact_not_found"


def test_registry_query_not_a_dict(tmp_path, monkeypatch) -> None:
    path = tmp_path / "sources_registry.yaml"
    path.write_text("[not a dict]", encoding="utf-8")
    monkeypatch.setattr(_artifact, "_REGISTRY_YAML", path)
    result = registry_query()
    assert result["error"] == "invalid_registry"


def test_registry_query_filters(tmp_path, monkeypatch) -> None:
    path = tmp_path / "sources_registry.yaml"
    path.write_text(
        "istat_sdmx:\n"
        "  source_kind: sdmx\n"
        "  protocol: sdmx\n"
        "  observation_mode: full\n"
        "  base_url: https://esploradati.istat.it/\n"
        "  verdict: intake\n"
        "dati_salute:\n"
        "  source_kind: ckan\n"
        "  protocol: ckan\n"
        "  observation_mode: catalog-watch\n"
        "  base_url: https://dati.salute.gov.it/\n"
        "  verdict: admitted\n"
        "  datasets_in_use: [salute-1]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_REGISTRY_YAML", path)

    # No filters
    all_res = registry_query()
    assert all_res["returned"] == 2

    # Filter by source_id
    sdmx_res = registry_query(source_id="istat_sdmx")
    assert sdmx_res["returned"] == 1
    assert sdmx_res["results"][0]["source_id"] == "istat_sdmx"

    # Filter by protocol
    ckan_res = registry_query(protocol="ckan")
    assert ckan_res["returned"] == 1
    assert ckan_res["results"][0]["source_id"] == "dati_salute"

    # Filter by source_kind
    sdmx_kind = registry_query(source_kind="sdmx")
    assert sdmx_kind["returned"] == 1

    # Filter by observation_mode
    catalog = registry_query(observation_mode="catalog-watch")
    assert catalog["returned"] == 1

    # No match
    empty = registry_query(protocol="sparql")
    assert empty["returned"] == 0


# ---------------------------------------------------------------------------
# Inventory edge cases
# ---------------------------------------------------------------------------


def test_inventory_status_report_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", tmp_path / "nonexistent_report.json")
    result = inventory_status(source_id="test")
    assert "error" in result


def test_inventory_status_sources_not_a_dict(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "inventory_report.json"
    report_path.write_text(json.dumps({"sources": "not_a_dict"}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    result = inventory_status()
    assert result["returned"] == 0


def test_inventory_status_source_info_not_a_dict(tmp_path, monkeypatch) -> None:
    """Un item in sources che non e' dict (es. lista) non rompe il loop."""
    report_path = tmp_path / "inventory_report.json"
    report_path.write_text(
        json.dumps({"sources": {"s1": "not_a_dict", "s2": {"status": "ok", "rows": 100}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    result = inventory_status()
    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "s2"


def test_query_inventory_has_results_true(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "intake_score": 45},
            {"source_id": "a", "item_id": "x2", "intake_score": None},
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    result = query_inventory(source_id="a", has_results=True)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x1"


def test_query_inventory_has_results_false(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "intake_score": 45},
            {"source_id": "a", "item_id": "x2", "intake_score": None},
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    result = query_inventory(source_id="a", has_results=False)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x2"


def test_query_inventory_grouped_when_dataset_group_missing(tmp_path, monkeypatch) -> None:
    """grouped=True senza colonna dataset_group → warning."""
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "intake_score": 45},
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    # Forza backend locale per evitare GCS
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(grouped=True)
    assert result["returned"] == 0
    assert "warning" in result
    assert "dataset_group" in result["warning"]


def test_query_inventory_grouped_aggregates(tmp_path, monkeypatch) -> None:
    """grouped=True con colonna dataset_group → aggregazione per gruppo."""
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {
                "source_id": "s1",
                "item_id": "a",
                "intake_score": 60,
                "dataset_group": "s1/gruppo-a",
                "dataset_group_size": 2,
                "dataset_group_year_min": 2020,
                "dataset_group_year_max": 2024,
            },
            {
                "source_id": "s1",
                "item_id": "b",
                "intake_score": 80,
                "dataset_group": "s1/gruppo-a",
                "dataset_group_size": 2,
                "dataset_group_year_min": 2020,
                "dataset_group_year_max": 2024,
            },
            {
                "source_id": "s1",
                "item_id": "c",
                "intake_score": 50,
                "dataset_group": "s1/gruppo-b",
                "dataset_group_size": 1,
                "dataset_group_year_min": 2022,
                "dataset_group_year_max": 2022,
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="s1", grouped=True)
    assert result["returned"] == 2  # 2 gruppi
    assert result["grouped"] is True
    results = sorted(result["results"], key=lambda r: r["dataset_group"])
    assert results[0]["dataset_group"] == "s1/gruppo-a"
    assert results[0]["item_count"] == 2
    assert results[0]["best_score"] == 80
    assert results[1]["dataset_group"] == "s1/gruppo-b"
    assert results[1]["item_count"] == 1
    assert results[1]["best_score"] == 50


# ─── PAQA: min_paqa_score ─────────────────────────────────────────────────────


def test_query_inventory_min_paqa_score_filters(tmp_path, monkeypatch) -> None:
    """min_paqa_score filtra quando paqa_score esiste."""
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "intake_score": 50, "paqa_score": 80},
            {"source_id": "a", "item_id": "x2", "intake_score": 50, "paqa_score": 60},
            {"source_id": "a", "item_id": "x3", "intake_score": 50, "paqa_score": None},
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="a", min_paqa_score=70)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x1"


def test_query_inventory_min_paqa_score_no_column(tmp_path, monkeypatch) -> None:
    """min_paqa_score su artifact senza paqa_score → zero risultati."""
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "intake_score": 50},
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="a", min_paqa_score=70)
    assert result["returned"] == 0  # colonna mancante → nessun risultato


def test_query_inventory_min_paqa_score_grouped(tmp_path, monkeypatch) -> None:
    """min_paqa_score in grouped mode esclude gruppi sotto soglia."""
    parquet_path = tmp_path / "source_check_results.parquet"
    _write_parquet(
        parquet_path,
        [
            {
                "source_id": "s1",
                "item_id": "a",
                "intake_score": 50,
                "paqa_score": 90,
                "dataset_group": "s1/g1",
                "dataset_group_size": 1,
                "dataset_group_year_min": 2020,
                "dataset_group_year_max": 2024,
            },
            {
                "source_id": "s1",
                "item_id": "b",
                "intake_score": 50,
                "paqa_score": 60,
                "dataset_group": "s1/g2",
                "dataset_group_size": 1,
                "dataset_group_year_min": 2020,
                "dataset_group_year_max": 2024,
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="s1", grouped=True, min_paqa_score=80)
    assert result["returned"] == 1  # solo g1 (paqa_score=90) supera 80
    assert result["results"][0]["dataset_group"] == "s1/g1"


# ─── Discovery: list_source_items ───────────────────────────────────────────────


def test_list_source_items_filters_by_source(tmp_path, monkeypatch) -> None:
    """list_source_items con source_id restituisce solo gli item di quella fonte."""
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "544",
                "item_name": "pensioni",
                "title": "Pensioni INPS",
                "organization": "INPS",
                "tags": "pensioni",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
            {
                "source_id": "openbdap",
                "protocol": "ckan",
                "item_id": "b",
                "item_name": "conti",
                "title": "Conto economico",
                "organization": "MEF",
                "tags": "",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_search",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "999",
                "item_name": "contributi",
                "title": "Contributi INPS",
                "organization": "INPS",
                "tags": "contributi",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = list_source_items("inps")

    assert result["source_id"] == "inps"
    assert result["returned"] == 2
    assert result["total_count"] == 2
    assert result["has_more"] is False
    assert result["filters"]["limit"] == 50
    assert result["filters"]["offset"] == 0
    assert all(r["source_id"] == "inps" for r in result["results"])
    item_ids = {r["item_id"] for r in result["results"]}
    assert item_ids == {"544", "999"}


def test_list_source_items_respects_limit_and_offset(tmp_path, monkeypatch) -> None:
    """limit e offset controllano la paginazione."""
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    rows = [
        {
            "source_id": "inps",
            "protocol": "ckan",
            "item_id": f"item_{i}",
            "item_name": f"item_{i}",
            "title": f"Item {i:03d}",
            "organization": "INPS",
            "tags": "",
            "landing_page": "",
            "distribution_url": "",
            "format": "csv",
            "source_status": "",
            "inventory_method": "package_list",
            "item_kind": "dataset",
            "api_base_url": "https://example.test/api",
            "captured_at": "2026-04-30",
        }
        for i in range(10)
    ]
    _write_parquet(inventory_path, rows)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    # Prima pagina: 3 item
    page1 = list_source_items("inps", limit=3, offset=0)
    assert page1["returned"] == 3
    assert page1["has_more"] is True
    assert page1["total_count"] == 10

    # Seconda pagina: altri 3
    page2 = list_source_items("inps", limit=3, offset=3)
    assert page2["returned"] == 3
    assert page2["has_more"] is True
    assert page2["results"][0]["item_id"] != page1["results"][0]["item_id"]

    # Ultima pagina: 4 item rimasti
    page3 = list_source_items("inps", limit=5, offset=6)
    assert page3["returned"] == 4
    assert page3["has_more"] is False


def test_list_source_items_text_query_filter(tmp_path, monkeypatch) -> None:
    """query testuale filtra per item_id, item_name, title, tags, organization."""
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "pens-2024",
                "item_name": "pensioni-2024",
                "title": "Pensioni erogate nel 2024",
                "organization": "INPS",
                "tags": "pensioni,previdenza",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "contr-2024",
                "item_name": "contributi-2024",
                "title": "Contributi versati",
                "organization": "INPS",
                "tags": "contributi",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    # Match su title
    result = list_source_items("inps", query="pensioni")
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "pens-2024"

    # Match su tags
    result2 = list_source_items("inps", query="contributi")
    assert result2["returned"] == 1
    assert result2["results"][0]["item_id"] == "contr-2024"

    # Match su item_name
    result3 = list_source_items("inps", query="pensioni-2024")
    assert result3["returned"] == 1

    # Nessun match
    result4 = list_source_items("inps", query="inesistente")
    assert result4["returned"] == 0
    assert result4["total_count"] == 0


def test_list_source_items_empty_source_id() -> None:
    """source_id vuoto restituisce errore."""
    result = list_source_items("")
    assert result["error"] == "invalid_params"


def test_list_source_items_unknown_source(tmp_path, monkeypatch) -> None:
    """source_id non presente nell'inventory restituisce 0 risultati."""
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "inps",
                "protocol": "ckan",
                "item_id": "1",
                "item_name": "test",
                "title": "Test",
                "organization": "",
                "tags": "",
                "landing_page": "",
                "distribution_url": "",
                "format": "csv",
                "source_status": "",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "api_base_url": "https://example.test/api",
                "captured_at": "2026-04-30",
            },
        ],
    )
    # Write a report so source_status works
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps({"sources": {"unknown_source": {"status": "error", "error": "HTTP 500"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    result = list_source_items("unknown_source")
    assert result["returned"] == 0
    assert result["total_count"] == 0
    assert result["source_status"] is not None
    assert "note" in result


def test_list_source_items_parquet_not_found(tmp_path, monkeypatch) -> None:
    """Parquet non trovato restituisce artifact_not_found."""
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", tmp_path / "nonexistent.parquet")
    result = list_source_items("inps")
    assert result["error"] == "artifact_not_found"


# ---------------------------------------------------------------------------
# Contract: so_radar_summary include_history
# ---------------------------------------------------------------------------


def test_radar_summary_include_history_passes_params(tmp_path, monkeypatch) -> None:
    """so_radar_summary(include_history=True) include history nel risultato
    e passa source_id/limit a radar_history."""
    from so_mcp.so_server import so_radar_summary

    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:00:00+00:00",
                "probe_date": "2026-06-01",
                "sources_total": 1,
                "status_counts": {"GREEN": 1},
                "sources": [{"id": "s1", "status": "GREEN"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    history_path = tmp_path / "radar_history.json"
    history_path.write_text(
        json.dumps(
            {
                "probes": [
                    {
                        "probe_date": "2026-05-25",
                        "sources": [{"id": "s1", "status": "GREEN"}],
                    },
                    {
                        "probe_date": "2026-05-18",
                        "sources": [{"id": "s1", "status": "RED"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", history_path)

    # Default: include_history=False → nessun history
    result_no = so_radar_summary(source_id="s1")
    assert "history" not in result_no

    # Con include_history=True → history presente
    result_yes = so_radar_summary(source_id="s1", include_history=True)
    assert "history" in result_yes
    assert result_yes["history"]["returned"] == 1
    assert result_yes["history"]["sources"][0]["source_id"] == "s1"
    assert result_yes["history"]["sources"][0]["recent_red_count"] == 1


def test_radar_summary_include_history_default_is_false(tmp_path, monkeypatch) -> None:
    """include_history=False di default — history non presente senza flag esplicito."""
    from so_mcp.so_server import so_radar_summary

    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:00:00+00:00",
                "probe_date": "2026-06-01",
                "sources_total": 1,
                "status_counts": {"GREEN": 1},
                "sources": [{"id": "s1", "status": "GREEN"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)
    monkeypatch.setattr(_artifact, "_RADAR_HISTORY_JSON", tmp_path / "unused.json")

    result = so_radar_summary(source_id="s1")
    assert "history" not in result


# ---------------------------------------------------------------------------
# Contract: so_source_overview include registry
# ---------------------------------------------------------------------------


def test_source_overview_includes_registry(tmp_path, monkeypatch) -> None:
    """so_source_overview include registry nel risultato."""
    # Radar
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-01T00:00:00+00:00",
                "probe_date": "2026-06-01",
                "sources_total": 1,
                "status_counts": {"GREEN": 1},
                "sources": [{"id": "s1", "status": "GREEN"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    # Inventory report
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-06-01T00:00:00+00:00",
                "sources": {"s1": {"status": "ok", "protocol": "ckan", "rows": 100}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    # Inventory parquet (per inventory_diff)
    inventory_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_parquet(
        inventory_path,
        [
            {
                "source_id": "s1",
                "protocol": "ckan",
                "item_id": "item_1",
                "item_name": "item_1",
                "organization": "Org",
                "format": "csv",
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "captured_at": "2026-06-01",
                "title": "",
                "tags": "",
                "notes_excerpt": "",
                "landing_page": "",
                "distribution_url": "",
                "source_status": "",
                "api_base_url": "",
                "civic_priority": "",
                "topic": "",
                "theme": "",
            }
            for _ in range(100)
        ],
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    # Signals
    signals_path = tmp_path / "catalog_signals.json"
    signals_path.write_text(json.dumps({"signals": []}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_SIGNALS_JSON", signals_path)

    # Registry
    registry_path = tmp_path / "sources_registry.yaml"
    registry_path.write_text(
        "s1:\n"
        "  source_kind: ckan\n"
        "  protocol: ckan\n"
        "  observation_mode: catalog-watch\n"
        "  base_url: https://example.test/\n"
        "  verdict: intake\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_REGISTRY_YAML", registry_path)

    from so_mcp.so_server import so_source_overview

    result = so_source_overview(source_id="s1")

    assert "registry" in result, "so_source_overview deve includere 'registry'"
    assert result["registry"]["returned"] == 1
    assert result["registry"]["results"][0]["source_id"] == "s1"
    assert result["registry"]["results"][0]["source_kind"] == "ckan"
    assert result["source_id"] == "s1"
    assert "radar" in result
    assert "inventory_status" in result
    assert "inventory_diff" in result
    assert "signals" in result
