from __future__ import annotations

import json

import duckdb  # noqa: E402
import pandas as pd  # must be before duckdb
import pytest

from so_mcp import _artifact
from so_mcp._find_url import find_by_url
from so_mcp._inventory_search import inventory_search
from so_mcp._source_check import (
    inventory_diff,
    inventory_status,
    query_inventory,
)

pytestmark = pytest.mark.contract


def _write_parquet(path, rows: list[dict]) -> None:
    con = duckdb.connect()
    try:
        con.register("rows_df", pd.DataFrame(rows))
        con.execute(f"COPY rows_df TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_query_inventory_filters_and_orders(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "low", "readiness_score": 2},
            {"source_id": "a", "item_id": "high", "readiness_score": 5},
            {"source_id": "b", "item_id": "other", "readiness_score": 9},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)

    result = query_inventory(source_id="a", min_score=4, limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "high"
    assert result["filters"]["source_id"] == "a"
    assert result["filters"]["min_score"] == 4
    assert result["filters"]["limit"] == 10
    assert result["cache"]["source"] == "local_cache"
    assert result["cache"]["stale"] is False


def test_query_inventory_falls_back_to_local_when_remote_unreachable(tmp_path, monkeypatch) -> None:
    """Parquet con auto backend, S3 non raggiungibile → fallback a locale."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [{"source_id": "local_src", "item_id": "cached", "readiness_score": 8}],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)

    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "auto")
    monkeypatch.setenv("CATALOG_INVENTORY_GCS_PREFIX", "gs://any-bucket")
    monkeypatch.setattr(_artifact, "_probe_s3_parquet", lambda _: False)

    result = query_inventory(source_id="local_src", limit=10)

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "cached"
    assert result["cache"]["source"] == "local_cache"


def test_resolved_parquet_gcs_direct_no_download(tmp_path, monkeypatch) -> None:
    """Parquet artifact con GCS backend → S3 URI diretto, nessun download."""
    validated_path = tmp_path / "validated.parquet"
    validated_path.write_text("dummy")
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", validated_path)
    monkeypatch.setenv("SO_ARTIFACT_BACKEND", "gcs")
    monkeypatch.setenv("CATALOG_INVENTORY_GCS_PREFIX", "gs://test-bucket")

    artifact = _artifact._source_check_parquet()
    with _artifact._resolved_parquet(artifact) as (path, cache):
        assert cache["source"] == "gcs_direct"
        assert str(path) == "s3://test-bucket/pipeline/validated.parquet"
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


def test_inventory_status_summarizes_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-04-30T00:00:00+00:00",
                "sources": [
                    {"source_id": "a", "status": "ok", "protocol": "ckan", "total": 10},
                    {"source_id": "b", "status": "error", "protocol": "sdmx", "error": "HTTP 500"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    summary = inventory_status()
    filtered = inventory_status(source_id="b")

    assert len(summary["sources"]) == 2
    assert summary["captured_at"] == "2026-04-30T00:00:00+00:00"
    assert len(filtered["sources"]) == 1
    assert filtered["sources"][0]["error"] == "HTTP 500"


def test_inventory_search_filters_rows(tmp_path, monkeypatch) -> None:
    """Search mode per testo e source_id."""
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
                "topic": "",
                "theme": "",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = inventory_search(query="dipendenti", source_id="openbdap")

    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "a"


# ─── Tests for new tools (MCP v2) ───────────────────────────────────────────────


def test_inventory_search_recommend_mode(tmp_path, monkeypatch) -> None:
    """Recommend mode con keyword raggruppa per fonte."""
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
                "topic": "",
                "theme": "",
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = inventory_search(keyword="INPS")

    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "inps"
    assert result["sources"][0]["item_count"] >= 1
    assert result["total_items_in_inventory"] == 2


def test_inventory_search_empty_keyword() -> None:
    """keyword vuoto restituisce errore."""
    result = inventory_search(keyword="")
    assert result["error"] == "no_params"


def test_inventory_search_empty_query() -> None:
    """query vuota restituisce errore."""
    result = inventory_search(query="")
    assert result["error"] == "no_params"


def test_inventory_search_no_params() -> None:
    """Nessun parametro → errore."""
    result = inventory_search()
    assert result["error"] == "no_params"


def test_inventory_diff(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-04-30T00:00:00+00:00",
                "sources": [
                    {
                        "source_id": "inps",
                        "status": "ok",
                        "protocol": "ckan",
                        "total": 2323,
                        "since_last": 2,
                        "method": "package_list",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    result = inventory_diff("inps")

    assert result["source_id"] == "inps"
    assert result["inventory_total"] == 2323
    assert result["delta_since_last"] == 2


def test_inventory_diff_source_not_in_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(json.dumps({"sources": []}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    result = inventory_diff("unknown_source")

    assert result["error"] == "Source 'unknown_source' non trovato"


def test_inventory_diff_report_not_found(tmp_path, monkeypatch) -> None:
    """Report JSON non trovato → errore propagato da inventory_status."""
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", tmp_path / "nonexistent.json")

    result = inventory_diff("inps")

    assert result["error"] == "catalog_inventory_report.json non trovato"


# ─── _source_radar_context tests (GAP-7: real radar_summary.json schema) ────


# ─── Tests for HTTP tools (mocked) ─────────────────────────────────────────────


def _write_source_check_parquet(path, rows: list[dict]) -> None:
    """Write minimal columns matching validated_groups schema."""
    _write_parquet(path, rows)


def _write_catalog_inventory_parquet(path, rows: list[dict]) -> None:
    """Write minimal columns matching catalog_inventory schema."""
    _write_parquet(path, rows)


def test_find_by_url_finds_by_url_in_source_check(tmp_path, monkeypatch) -> None:
    """Search by download URL in validated_groups."""
    check_path = tmp_path / "validated_groups.parquet"
    _write_source_check_parquet(
        check_path,
        [
            {
                "url": "https://inps.example/download/PENSIONI-2024.csv",
                "item_id": "id1",
            },
            {"url": "https://inps.example/download/ALTRO.csv", "item_id": "id2"},
        ],
    )
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(inv_path, [{"dummy": 0}])
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = find_by_url("PENSIONI-2024.csv")

    assert result["query_url"] == "PENSIONI-2024.csv"
    assert len(result["validated_groups"]) == 1
    assert result["validated_groups"][0]["item_id"] == "id1"


def test_find_by_url_finds_by_item_name_in_inventory(tmp_path, monkeypatch) -> None:
    """Search by item_name should match in catalog_inventory expanded columns."""
    check_path = tmp_path / "validated_groups.parquet"
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
    check_path = tmp_path / "validated_groups.parquet"
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
    check_path = tmp_path / "validated_groups.parquet"
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

    assert result["validated_groups"] == []
    assert result["catalog_inventory"] == []
    assert "validated_error" not in result
    assert "catalog_inventory_error" not in result


def test_find_by_url_rejects_empty_url() -> None:
    result = find_by_url("")
    assert result["error"] == "empty_url"


# ---------------------------------------------------------------------------
# Radar edge cases: radar_history
# ---------------------------------------------------------------------------


def test_inventory_status_report_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", tmp_path / "nonexistent_report.json")
    result = inventory_status(source_id="test")
    assert "error" in result


def test_inventory_status_sources_not_a_list(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "inventory_report.json"
    report_path.write_text(json.dumps({"sources": "not_a_list"}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    result = inventory_status()
    assert result["sources"] == "not_a_list"


def test_inventory_status_source_items_mixed_types(tmp_path, monkeypatch) -> None:
    """Item in sources che non e' dict non rompe il loop."""
    report_path = tmp_path / "inventory_report.json"
    report_path.write_text(
        json.dumps(
            {
                "sources": [
                    "not_a_dict",
                    {"source_id": "s2", "status": "ok", "total": 100},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    result = inventory_status()
    assert len(result["sources"]) == 2


def test_query_inventory_has_results_true(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "reachable": True, "readiness_score": 5},
            {"source_id": "a", "item_id": "x2", "reachable": False, "readiness_score": 5},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    result = query_inventory(source_id="a", has_results=True)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x1"


def test_query_inventory_has_results_false(tmp_path, monkeypatch) -> None:
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "reachable": True, "readiness_score": 5},
            {"source_id": "a", "item_id": "x2", "reachable": False, "readiness_score": 5},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    result = query_inventory(source_id="a", has_results=False)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x2"


def test_query_inventory_grouped_when_dataset_group_missing(tmp_path, monkeypatch) -> None:
    """grouped=True senza colonna dataset_group → warning."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "readiness_score": 4},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(grouped=True)
    assert result["results"] == []
    assert "warning" in result
    assert "dataset_group" in result["warning"]


def test_query_inventory_grouped_aggregates(tmp_path, monkeypatch) -> None:
    """grouped=True con colonna dataset_group → aggregazione per gruppo."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {
                "source_id": "s1",
                "item_id": "a",
                "readiness_score": 6,
                "dataset_group": "s1/gruppo-a",
                "item_count": 2,
            },
            {
                "source_id": "s1",
                "item_id": "b",
                "readiness_score": 8,
                "dataset_group": "s1/gruppo-a",
                "item_count": 2,
            },
            {
                "source_id": "s1",
                "item_id": "c",
                "readiness_score": 5,
                "dataset_group": "s1/gruppo-b",
                "item_count": 1,
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="s1", grouped=True)
    assert result["returned"] == 2  # 2 gruppi
    results = sorted(result["results"], key=lambda r: r["dataset_group"])
    assert results[0]["dataset_group"] == "s1/gruppo-a"
    assert results[0]["item_count"] == 2
    assert results[0]["best_score"] == 8
    assert results[1]["dataset_group"] == "s1/gruppo-b"
    assert results[1]["item_count"] == 1
    assert results[1]["best_score"] == 5


# ─── PAQA: min_paqa_score ─────────────────────────────────────────────────────


def test_query_inventory_min_score_filters(tmp_path, monkeypatch) -> None:
    """min_score filtra quando readiness_score esiste."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "readiness_score": 8},
            {"source_id": "a", "item_id": "x2", "readiness_score": 5},
            {"source_id": "a", "item_id": "x3", "readiness_score": None},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="a", min_score=7)
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "x1"


def test_query_inventory_min_score_low_threshold(tmp_path, monkeypatch) -> None:
    """min_score=0 (soglia minima) restituisce tutti i risultati."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {"source_id": "a", "item_id": "x1", "readiness_score": 1},
            {"source_id": "a", "item_id": "x2", "readiness_score": 5},
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="a", min_score=0)
    assert result["returned"] == 2


def test_query_inventory_min_score_grouped(tmp_path, monkeypatch) -> None:
    """min_score in grouped mode esclude gruppi sotto soglia."""
    parquet_path = tmp_path / "validated_groups.parquet"
    _write_parquet(
        parquet_path,
        [
            {
                "source_id": "s1",
                "item_id": "a",
                "readiness_score": 9,
                "dataset_group": "s1/g1",
                "item_count": 1,
            },
            {
                "source_id": "s1",
                "item_id": "b",
                "readiness_score": 6,
                "dataset_group": "s1/g2",
                "item_count": 1,
            },
        ],
    )
    monkeypatch.setattr(_artifact, "_VALIDATED_PARQUET", parquet_path)
    monkeypatch.setattr(_artifact, "_artifact_backend", lambda: "local")
    result = query_inventory(source_id="s1", grouped=True, min_score=8)
    assert result["returned"] == 1  # solo g1 (score=9) supera 8
    assert result["results"][0]["dataset_group"] == "s1/g1"


# ─── Inventory Search: list mode (per source_id) ──────────────────────────────


def test_inventory_search_list_mode(tmp_path, monkeypatch) -> None:
    """List mode con source_id restituisce solo gli item di quella fonte."""
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

    result = inventory_search(source_id="inps")

    assert result["source_id"] == "inps"
    assert result["returned"] == 2
    assert result["total_count"] == 2
    assert result["has_more"] is False
    assert result["filters"]["limit"] == 25  # default
    assert result["filters"]["offset"] == 0
    assert all(r["source_id"] == "inps" for r in result["results"])
    item_ids = {r["item_id"] for r in result["results"]}
    assert item_ids == {"544", "999"}


def test_inventory_search_list_pagination(tmp_path, monkeypatch) -> None:
    """limit e offset controllano la paginazione in list mode."""
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

    page1 = inventory_search(source_id="inps", limit=3, offset=0)
    assert page1["returned"] == 3
    assert page1["has_more"] is True
    assert page1["total_count"] == 10

    page2 = inventory_search(source_id="inps", limit=3, offset=3)
    assert page2["returned"] == 3
    assert page2["has_more"] is True
    assert page2["results"][0]["item_id"] != page1["results"][0]["item_id"]

    page3 = inventory_search(source_id="inps", limit=5, offset=6)
    assert page3["returned"] == 4
    assert page3["has_more"] is False


def test_inventory_search_search_within_source(tmp_path, monkeypatch) -> None:
    """query + source_id cerca full-text filtrato per fonte."""
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

    result = inventory_search(query="pensioni", source_id="inps")
    assert result["returned"] == 1
    assert result["results"][0]["item_id"] == "pens-2024"

    result2 = inventory_search(query="contributi", source_id="inps")
    assert result2["returned"] == 1
    assert result2["results"][0]["item_id"] == "contr-2024"

    result3 = inventory_search(query="inesistente", source_id="inps")
    assert result3["returned"] == 0


def test_inventory_search_list_empty_source_id() -> None:
    """source_id vuoto in list mode restituisce errore."""
    result = inventory_search(source_id="")
    assert result["error"] == "no_params"


def test_inventory_search_unknown_source(tmp_path, monkeypatch) -> None:
    """source_id non presente restituisce 0 risultati."""
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
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(
        json.dumps({"sources": {"unknown_source": {"status": "error", "error": "HTTP 500"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

    result = inventory_search(source_id="unknown_source")
    assert result["returned"] == 0
    assert result["total_count"] == 0
    assert result["source_status"] is not None
    assert "note" in result


def test_inventory_search_parquet_not_found(tmp_path, monkeypatch) -> None:
    """Parquet non trovato restituisce artifact_not_found."""
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", tmp_path / "nonexistent.parquet")
    result = inventory_search(source_id="inps")
    assert result["error"] == "artifact_not_found"


# ---------------------------------------------------------------------------
# Contract: so_radar_summary include_history
# ---------------------------------------------------------------------------
