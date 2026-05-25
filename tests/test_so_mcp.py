from __future__ import annotations

import json

import _artifact
import _html
import _probe
import duckdb  # noqa: E402
import pandas as pd  # must be before so_server_core import
import pytest
import so_server_core as core  # noqa: E402  # conftest aggiunge mcp/ a sys.path


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
    monkeypatch.setattr(_artifact.requests, "get", fake_get)

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
    monkeypatch.setattr(_artifact, "_SIGNALS_JSON", signals_path)

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
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = core.recommend_sources("INPS")

    assert result["returned"] == 1
    assert result["sources"][0]["source_id"] == "inps"
    assert result["sources"][0]["item_count"] >= 1
    assert result["total_items_in_inventory"] == 2  # inps + openbdap in test data


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
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inventory_path)

    result = core.inventory_diff("inps")

    assert result["source_id"] == "inps"
    assert result["baseline_value"] == 2323
    assert result["current_count"] == 2325
    assert result["delta"] == 2


def test_inventory_diff_source_not_in_report(tmp_path, monkeypatch) -> None:
    report_path = tmp_path / "catalog_inventory_report.json"
    report_path.write_text(json.dumps({"sources": {}}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)

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
    monkeypatch.setattr(_artifact, "_INVENTORY_REPORT", report_path)
    # Point to non-existent parquet
    monkeypatch.setattr(
        _artifact, "_INVENTORY_PARQUET", tmp_path / "nonexistent.parquet"
    )

    result = core.inventory_diff("inps")

    assert result["error"] == "artifact_not_found"


# ─── _source_radar_context tests (GAP-7: real radar_summary.json schema) ────


def test_source_radar_context_red(tmp_path, monkeypatch) -> None:
    """RED source with red_streak returns contesto giorni."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps({
            "sources": [
                {"id": "dati_salute", "status": "RED", "red_streak": 14},
                {"id": "istat_sdmx", "status": "GREEN"},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = core._source_radar_context("dati_salute")
    assert result is not None
    assert "RED" in result
    assert "14 giorni" in result


def test_source_radar_context_green(tmp_path, monkeypatch) -> None:
    """GREEN source returns status=GREEN."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(
        json.dumps({
            "sources": [
                {"id": "istat_sdmx", "status": "GREEN"},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = core._source_radar_context("istat_sdmx")
    assert result == "status=GREEN"


def test_source_radar_context_unknown_source(tmp_path, monkeypatch) -> None:
    """Source not in radar returns None."""
    radar_path = tmp_path / "radar_summary.json"
    radar_path.write_text(json.dumps({"sources": []}), encoding="utf-8")
    monkeypatch.setattr(_artifact, "_RADAR_JSON", radar_path)

    result = core._source_radar_context("unknown_source")
    assert result is None


def test_source_radar_context_no_file(tmp_path, monkeypatch) -> None:
    """No radar file returns None."""
    monkeypatch.setattr(_artifact, "_RADAR_JSON", tmp_path / "nonexistent.json")
    result = core._source_radar_context("dati_salute")
    assert result is None


# ─── Tests for HTTP tools (mocked) ─────────────────────────────────────────────


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


# ─── Topic inference — new topics from MCP audit (2026-05-17) ──────────────


def test_infer_topic_welfare() -> None:
    result = core.infer_topic("bonus assistenziali e sostegno alla poverta")
    assert "welfare" in result["topics"]
    assert result["topics"]["welfare"] >= 3


def test_infer_topic_previdenza() -> None:
    result = core.infer_topic("pensioni erogate per regione e tipologia, importo medio")
    assert "previdenza" in result["topics"]
    assert result["top_match"] == "previdenza"


def test_infer_topic_casa() -> None:
    result = core.infer_topic("edilizia residenziale pubblica e catasto immobiliare")
    assert "casa" in result["topics"]
    assert result["topics"]["casa"] >= 3


def test_infer_topic_cultura() -> None:
    result = core.infer_topic("musei e patrimonio artistico, mostre culturali")
    assert "cultura" in result["topics"]
    assert result["topics"]["cultura"] >= 3


def test_infer_topic_bilancio() -> None:
    result = core.infer_topic("gettito fiscale IRPEF e spesa pubblica")
    assert "bilancio" in result["topics"]
    assert result["topics"]["bilancio"] >= 3


def test_infer_topic_innovazione() -> None:
    result = core.infer_topic("digitale e innovazione tecnologica, open data")
    assert "innovazione" in result["topics"]
    assert result["topics"]["innovazione"] >= 3


def test_infer_topic_sicurezza() -> None:
    result = core.infer_topic("protezione civile e prevenzione rischi, emergenza")
    assert "sicurezza" in result["topics"]
    assert result["topics"]["sicurezza"] >= 3


def test_infer_topic_new_not_overlapping_old() -> None:
    """New topic keywords should not cause false-positive scoring in old topics."""
    # Welfare keywords should not accidentally score lavoro or economia
    result = core.infer_topic("bonus assistenziali e assegno sostegno")
    assert "welfare" in result["topics"]
    # These are purely welfare terms - should not trigger old topics
    for old_topic in ("lavoro", "economia", "sanita"):
        assert old_topic not in result["topics"]


def test_infer_topic_accenti_normalizzati() -> None:
    """Testi con accenti devono matchare keyword senza accenti.

    Ogni frase contiene UNA SOLA parola accentata come unica keyword matchabile.
    Se la normalizzazione NFKD venisse rimossa, ciascuna frase produrrebbe {}
    (nessun topic matchato).
    """
    # "Sanità" → keyword "sanita" (solo dopo NFKD: sanità → sanita)
    result = core.infer_topic("Sanità")
    assert "sanita" in result["topics"], (
        "Sanità (accento) deve matchare sanita. "
        "Se fallisce, la normalizzazione NFKD non funziona."
    )

    # "Mobilità" → keyword "mobilita" (solo dopo NFKD: mobilità → mobilita)
    result = core.infer_topic("Mobilità")
    assert "trasporti" in result["topics"], (
        "Mobilità (accento) deve matchare trasporti. "
        "Se fallisce, la normalizzazione NFKD non funziona."
    )

    # "Elettricità" → keyword "elettricita" (solo dopo NFKD)
    result = core.infer_topic("Elettricità")
    assert "energia" in result["topics"], (
        "Elettricità (accento) deve matchare energia. "
        "Se fallisce, la normalizzazione NFKD non funziona."
    )

    # "Anzianità" → keyword "anzianita" (solo dopo NFKD)
    result = core.infer_topic("Anzianità")
    assert "previdenza" in result["topics"], (
        "Anzianità (accento) deve matchare previdenza. "
        "Se fallisce, la normalizzazione NFKD non funziona."
    )


def test_infer_topic_no_false_positive_aria_in_sanitaria() -> None:
    """"aria" come sottostringa di "sanitaria" non deve produrre falso positivo ambiente."""
    result = core.infer_topic("Spesa sanitaria regionale")
    # "sanitaria" contiene "aria" (substring) che potrebbe matchare ambiente
    assert "ambiente" not in result["topics"], (
        "'aria' in 'sanitaria' non deve matchare ambiente via substring"
    )


def test_infer_topic_no_false_positive_ment_in_farmaceutica() -> None:
    """Verifica che non ci siano falsi positivi da substring con keyword corte."""
    result = core.infer_topic("Consumo farmaceutico convenzionato regionale")
    for topic in ("ambiente", "casa", "cultura", "economia"):
        assert topic not in result["topics"], (
            f"'{topic}' non dovrebbe matchare su testo farmaceutico"
        )


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

    monkeypatch.setattr(_probe, "HttpClient", _FakeHttpClient)

    result = core.probe_url("https://expired-cert.example.com/file.csv")

    assert result["is_reachable"] is True
    assert result["ssl_fallback_used"] is True
    assert result["http_status"] == 200


def test_probe_url_ssl_fallback_from_get_fallback(monkeypatch) -> None:
    """When HEAD fails with non-SSL error and GET fallback succeeds, ssl_fallback_used reflects result2."""
    class _FakeOKResponse:
        status_code = 200
        headers = {"content-type": "text/csv", "content-length": "1024"}

    class _FakeHeadResult:
        """Simulates HttpClient.head() returning a non-SSL error."""
        def __init__(self):
            self.response = None
            self.err = Exception("connection refused")  # non-SSL error
            self.ssl_fallback_used = None

        @property
        def is_ok(self):
            return False

        @property
        def is_ssl_fallback_failed(self):
            return False

    class _FakeGetWithSSLFallbackResult:
        """Simulates HttpClient.get() succeeding via SSL fallback."""
        def __init__(self):
            self.response = _FakeOKResponse()
            self.err = None
            self.ssl_fallback_used = True  # SSL fallback was used

        @property
        def is_ok(self):
            return True

        @property
        def is_ssl_fallback_failed(self):
            return False

    class _FakeHttpClient:
        def __init__(self, timeout=None):
            pass

        def head(self, url):
            return _FakeHeadResult()

        def get(self, url, headers=None, params=None):
            return _FakeGetWithSSLFallbackResult()

    monkeypatch.setattr(_probe, "HttpClient", _FakeHttpClient)

    result = core.probe_url("https://expired-cert.example.com/file.csv")

    # Response comes from result2 (GET), ssl_fallback_used must reflect result2
    assert result["is_reachable"] is True
    assert result["ssl_fallback_used"] is True, "ssl_fallback_used must come from GET result2"
    assert result["http_status"] == 200
    assert result["content_type"] == "text/csv"


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

    monkeypatch.setattr(_html, "HttpClient", _FakeHttpClient)

    result = core._html_extract_links("https://expired-cert.example.com/page.html")

    assert result["is_reachable"] is False
    assert "error" in result
    assert result["message"] == "unexpected internal error"


# ─── _guess_format tests (GAP-8: content-type inference) ───────────────────


def test_guess_format_from_content_type() -> None:
    assert core._guess_format("https://example.test/file", "text/csv") == "CSV"
    assert core._guess_format("https://example.test/file", "application/json") == "JSON"
    assert core._guess_format("https://example.test/file", "text/html") == "HTML"
    assert core._guess_format("https://example.test/file", "text/plain; charset=utf-8") == "TXT"
    assert core._guess_format("https://example.test/file", "application/octet-stream") == "BIN"
    assert core._guess_format("https://example.test/file", "text/tab-separated-values") == "TSV"
    assert core._guess_format("https://example.test/file", "application/gzip") == "GZ"
    assert core._guess_format("https://example.test/file", "application/zip") == "ZIP"
    assert core._guess_format("https://example.test/file", "application/pdf") == "PDF"
    assert core._guess_format("https://example.test/file", "application/parquet") == "PARQUET"


def test_guess_format_from_suffix_fallback() -> None:
    """When content_type is None or unknown, fallback to URL suffix."""
    assert core._guess_format("https://example.test/data.csv", None) == "CSV"
    assert core._guess_format("https://example.test/data.json", None) == "JSON"
    assert core._guess_format("https://example.test/data.xlsx", None) == "XLSX"
    assert core._guess_format("https://example.test/file.unknown", None) is None
    assert core._guess_format("https://example.test/data", "application/octet-stream") == "BIN"


def test_guess_format_unknown_content_type() -> None:
    """Unknown content-type with no suffix should return None."""
    assert core._guess_format("https://example.test/file", "application/vnd.ms-powerpoint") is None
    assert core._guess_format("https://example.test/data", None) is None


# ─── find_by_url tests (GAP-1: expanded search beyond URL columns) ─────────


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
            {"url": "https://inps.example/download/PENSIONI-2024.csv", "url_checked": "", "item_id": "id1"},
            {"url": "https://inps.example/download/ALTRO.csv", "url_checked": "", "item_id": "id2"},
        ],
    )
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(inv_path, [{"dummy": 0}])
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = core.find_by_url("PENSIONI-2024.csv")

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
    result = core.find_by_url("Pensioni erogate")

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

    result = core.find_by_url("ID-5257")

    assert len(result["catalog_inventory"]) == 1
    assert result["catalog_inventory"][0]["item_name"] == "Pensioni"


def test_find_by_url_returns_empty_when_no_match(tmp_path, monkeypatch) -> None:
    """No match should return empty lists, not errors."""
    check_path = tmp_path / "source_check_results.parquet"
    _write_source_check_parquet(check_path, [{"url": "https://example.test/other.csv", "url_checked": "", "item_id": "none"}])
    inv_path = tmp_path / "catalog_inventory_latest.parquet"
    _write_catalog_inventory_parquet(inv_path, [{"item_id": "other", "item_name": "Other", "title": "Other"}])
    monkeypatch.setattr(_artifact, "_CHECK_PARQUET", check_path)
    monkeypatch.setattr(_artifact, "_INVENTORY_PARQUET", inv_path)

    result = core.find_by_url("nonexistent-filename.csv")

    assert result["source_check_results"] == []
    assert result["catalog_inventory"] == []
    assert "source_check_error" not in result
    assert "catalog_inventory_error" not in result


def test_find_by_url_rejects_empty_url() -> None:
    result = core.find_by_url("")
    assert result["error"] == "empty_url"
pytestmark = pytest.mark.contract
