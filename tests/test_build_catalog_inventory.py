from __future__ import annotations

import build_catalog_inventory
import collectors.ckan
import collectors.html as html_collector
import collectors.sparql
from lab_connectors.http import HttpResult


class FakeJsonResponse:
    def __init__(
        self,
        payload: dict | None,
        *,
        status_code: int = 200,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class _FakeClient:
    def __init__(self, result_fn):
        self._result_fn = result_fn

    def get(self, url, **kwargs):
        return self._result_fn(url, **kwargs)


def test_collect_ckan_inventory_merges_current_list_metadata(monkeypatch) -> None:
    source_cfg = {
        "base_url": "https://example.test/api/3/action/package_search",
        "source_kind": "catalog",
        "protocol": "ckan",
        "catalog_baseline": {"method": "package_list"},
    }

    def fake_search(*_args, **_kwargs):
        raise ValueError("package_search rotto")

    def fake_package_list(source_id, source_cfg, captured_at):
        return [
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "item_id": "1",
                "item_name": "1",
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": "https://example.test/api/3/action/package_list",
                "ordinal": 1,
            },
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "item_id": "2",
                "item_name": "2",
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": "https://example.test/api/3/action/package_list",
                "ordinal": 2,
            },
        ]

    def fake_current_list(source_id, source_cfg, captured_at):
        return (
            [
                {
                    "captured_at": captured_at,
                    "source_id": source_id,
                    "source_kind": source_cfg.get("source_kind"),
                    "protocol": source_cfg.get("protocol"),
                    "inventory_method": "current_package_list_with_resources",
                    "item_kind": "dataset",
                    "item_id": "1",
                    "item_name": "pkg-one",
                    "title": "Package One",
                    "organization": "Demo Org",
                    "tags": "alpha, beta",
                    "notes_excerpt": "note",
                    "source_url": "https://example.test/api/3/action/current_package_list_with_resources",
                    "ordinal": 99,
                }
            ],
            None,
        )

    monkeypatch.setattr(
        build_catalog_inventory, "collect_ckan_inventory_via_search", fake_search
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_package_list",
        fake_package_list,
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_current_list",
        fake_current_list,
    )
    monkeypatch.setattr(collectors.ckan.time, "sleep", lambda _seconds: None)

    rows, warning = build_catalog_inventory.collect_ckan_inventory(
        "demo", source_cfg, "2026-04-09T12:00:00+00:00"
    )

    assert [row["ordinal"] for row in rows] == [1, 2]
    assert rows[0]["item_id"] == "1"
    assert rows[0]["title"] == "Package One"
    assert rows[0]["organization"] == "Demo Org"
    assert rows[1]["item_id"] == "2"
    assert rows[1]["title"] is None

    assert warning is not None
    assert warning["type"] == "fallback_current_package_list_with_resources"
    assert warning["rows_enriched"] == 1
    assert warning["rows_missing_metadata"] == 1


def test_collect_ckan_inventory_skips_current_list_for_inps(monkeypatch) -> None:
    source_cfg = {
        "base_url": "https://www.inps.it/odapi/api/3/action/package_search",
        "source_kind": "catalog",
        "protocol": "ckan",
        "catalog_baseline": {"method": "package_list"},
        "inventory": {"skip_current_list": True, "package_show_sample": True, "sample_size": 25},
    }

    def fake_search(*_args, **_kwargs):
        raise ValueError("package_search rotto")

    def fake_package_list(source_id, source_cfg, captured_at):
        return [
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "item_id": "544",
                "item_name": "544",
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": "https://www.inps.it/odapi/api/3/action/package_list",
                "ordinal": 1,
            }
        ]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("current list non dovrebbe essere chiamato per INPS")

    def fake_package_show_sample(*_args, **_kwargs):
        return ([], None)

    monkeypatch.setattr(
        build_catalog_inventory, "collect_ckan_inventory_via_search", fake_search
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_package_list",
        fake_package_list,
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_current_list",
        fail_if_called,
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_package_show_sample",
        fake_package_show_sample,
    )

    rows, warning = build_catalog_inventory.collect_ckan_inventory(
        "inps", source_cfg, "2026-04-09T12:00:00+00:00"
    )

    assert len(rows) == 1
    assert rows[0]["item_id"] == "544"
    assert rows[0]["title"] is None
    assert warning is not None
    assert warning["type"] == "skip_current_package_list_with_package_show_sample"
    assert warning["rows_enriched"] == 0


def test_collect_ckan_inventory_inps_enriches_with_package_show_sample(monkeypatch) -> None:
    source_cfg = {
        "base_url": "https://www.inps.it/odapi/api/3/action/package_search",
        "source_kind": "catalog",
        "protocol": "ckan",
        "catalog_baseline": {"method": "package_list"},
        "inventory": {"skip_current_list": True, "package_show_sample": True, "sample_size": 25},
    }

    def fake_search(*_args, **_kwargs):
        raise ValueError("package_search rotto")

    def fake_package_list(source_id, source_cfg, captured_at):
        return [
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "item_id": "544",
                "item_name": "544",
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": "https://www.inps.it/odapi/api/3/action/package_list",
                "ordinal": 1,
            },
            {
                "captured_at": captured_at,
                "source_id": source_id,
                "source_kind": source_cfg.get("source_kind"),
                "protocol": source_cfg.get("protocol"),
                "inventory_method": "package_list",
                "item_kind": "dataset",
                "item_id": "545",
                "item_name": "545",
                "title": None,
                "organization": None,
                "tags": None,
                "notes_excerpt": None,
                "source_url": "https://www.inps.it/odapi/api/3/action/package_list",
                "ordinal": 2,
            },
        ]

    def fake_package_show_sample(*_args, **_kwargs):
        return (
            [
                {
                    "item_id": "544",
                    "item_name": "rdc-statistiche",
                    "title": "Reddito di cittadinanza - statistiche",
                    "organization": "INPS",
                    "tags": "welfare",
                    "notes_excerpt": "descrizione",
                    "source_url": "https://www.inps.it/odapi/api/3/action/package_show",
                    "inventory_method": "package_show_sample",
                    "ordinal": 99,
                }
            ],
            None,
        )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("current list non dovrebbe essere chiamato per INPS")

    monkeypatch.setattr(
        build_catalog_inventory, "collect_ckan_inventory_via_search", fake_search
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_package_list",
        fake_package_list,
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_package_show_sample",
        fake_package_show_sample,
    )
    monkeypatch.setattr(
        build_catalog_inventory,
        "collect_ckan_inventory_via_current_list",
        fail_if_called,
    )

    rows, warning = build_catalog_inventory.collect_ckan_inventory(
        "inps", source_cfg, "2026-04-09T12:00:00+00:00"
    )

    assert len(rows) == 2
    assert rows[0]["item_id"] == "544"
    assert rows[0]["title"] == "Reddito di cittadinanza - statistiche"
    assert rows[1]["item_id"] == "545"
    assert rows[1]["title"] is None
    assert warning is not None
    assert warning["type"] == "skip_current_package_list_with_package_show_sample"
    assert warning["rows_enriched"] == 1
    assert warning["rows_missing_metadata"] == 1


def test_ckan_get_json_reports_non_json_response(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs):
        return FakeJsonResponse(
            None,
            text="<html>Request Rejected</html>",
            headers={"content-type": "text/html"},
        )

    monkeypatch.setattr(collectors.ckan, "observatory_get", fake_get)

    try:
        collectors.ckan.ckan_get_json("https://example.test/api/3/action/package_list")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected non-JSON CKAN response to raise ValueError")

    assert "non-JSON" in message
    assert "Request Rejected" in message


def test_collect_sparql_inventory_groups_distribution_bindings(monkeypatch) -> None:
    source_cfg = {
        "base_url": "https://example.test/sparql",
        "source_kind": "catalog",
        "protocol": "sparql",
        "catalog_baseline": {
            "method": "sparql_query",
            "query_name": "dcat_datasets",
        },
        "sparql": {
            "endpoint_url": "https://example.test/sparql",
            "query_name": "dcat_datasets",
            "limit": 10,
        },
    }
    payload = {
        "results": {
            "bindings": [
                {
                    "dataset": {
                        "type": "uri",
                        "value": "https://example.test/dataset/alpha",
                    },
                    "title": {"type": "literal", "value": "Dataset Alpha"},
                    "description": {
                        "type": "literal",
                        "value": "Descrizione dataset alpha",
                    },
                    "publisherName": {
                        "type": "literal",
                        "value": "Ente demo",
                    },
                    "modified": {"type": "literal", "value": "2026-04-10"},
                    "downloadURL": {
                        "type": "uri",
                        "value": "https://example.test/download/alpha.csv",
                    },
                    "format": {"type": "uri", "value": "CSV"},
                    "theme": {"type": "uri", "value": "ENVI"},
                },
                {
                    "dataset": {
                        "type": "uri",
                        "value": "https://example.test/dataset/alpha",
                    },
                    "downloadURL": {
                        "type": "uri",
                        "value": "https://example.test/download/alpha.ttl",
                    },
                    "format": {"type": "uri", "value": "RDF_TURTLE"},
                    "theme": {"type": "uri", "value": "ENVI"},
                },
                {
                    "dataset": {
                        "type": "uri",
                        "value": "https://example.test/dataset/beta",
                    },
                    "title": {"type": "literal", "value": "Dataset Beta"},
                },
            ]
        }
    }

    def fake_get(url, **kwargs):
        assert url == "https://example.test/sparql"
        assert kwargs["headers"]["Accept"] == "application/sparql-results+json"
        assert kwargs["params"]["format"] == "application/sparql-results+json"
        assert "LIMIT 10" in kwargs["params"]["query"]
        return FakeJsonResponse(payload)

    monkeypatch.setattr(collectors.sparql, "observatory_get", fake_get)

    rows, warning = build_catalog_inventory.collect_sparql_inventory(
        "demo_sparql", source_cfg, "2026-04-11T12:00:00+00:00"
    )

    assert len(rows) == 2
    assert rows[0]["item_id"] == "https://example.test/dataset/alpha"
    assert rows[0]["item_name"] == "alpha"
    assert rows[0]["title"] == "Dataset Alpha"
    assert rows[0]["organization"] == "Ente demo"
    assert rows[0]["modified"] == "2026-04-10"
    assert rows[0]["distribution_url"] == "https://example.test/download/alpha.csv"
    assert rows[0]["distribution_count"] == 2
    assert rows[0]["format"] == "CSV, RDF_TURTLE"
    assert rows[0]["tags"] is None
    assert rows[0]["theme"] == "ENVI"
    assert rows[1]["item_name"] == "beta"

    assert warning is not None
    assert warning["type"] == "sparql_query_template"
    assert warning["query_name"] == "dcat_datasets"
    assert warning["bindings"] == 3
    assert warning["datasets"] == 2


class TestResourceUrlExtraction:
    """Tests for _resource_first_url, _landing_page, _distribution_url helpers."""

    def test_resource_first_url_returns_first_valid(self):
        item = {
            "resources": [
                {"url": None, "format": "xls"},
                {"url": "  http://example.com/file1.csv  ", "format": "csv"},
                {"url": "http://example.com/file2.pdf", "format": "pdf"},
            ]
        }
        assert collectors.ckan._resource_first_url(item) == "http://example.com/file1.csv"

    def test_resource_first_url_skips_empty_and_none(self):
        item = {"resources": [{"url": ""}, {"url": None}, {"url": "  "}, {"url": "http://valid.it/file.xls"}]}
        assert collectors.ckan._resource_first_url(item) == "http://valid.it/file.xls"

    def test_resource_first_url_returns_none_when_no_resources(self):
        assert collectors.ckan._resource_first_url({}) is None
        assert collectors.ckan._resource_first_url({"resources": []}) is None

    def test_landing_page_prefers_item_url_over_resource(self):
        item = {
            "url": "https://dati.it/dataset/123",
            "resources": [{"url": "http://download.it/file.csv"}],
        }
        assert collectors.ckan._landing_page(item) == "https://dati.it/dataset/123"

    def test_landing_page_falls_back_to_first_resource_url(self):
        item = {"resources": [{"url": "http://download.it/file.csv", "format": "csv"}]}
        assert collectors.ckan._landing_page(item) == "http://download.it/file.csv"

    def test_landing_page_returns_none_when_no_url_anywhere(self):
        assert collectors.ckan._landing_page({}) is None
        assert collectors.ckan._landing_page({"resources": []}) is None

    def test_distribution_url_returns_first_resource_url(self):
        item = {
            "url": "https://dati.it/dataset/123",
            "resources": [
                {"url": "http://download.it/file1.xls", "format": "xls"},
                {"url": "http://download.it/file2.csv", "format": "csv"},
            ],
        }
        assert collectors.ckan._distribution_url(item) == "http://download.it/file1.xls"

    def test_distribution_url_returns_none_when_no_resources(self):
        assert collectors.ckan._distribution_url({}) is None
        assert collectors.ckan._distribution_url({"resources": []}) is None


def test_extract_ckan_inventory_row_includes_landing_page_and_distribution_url():
    """extract_ckan_inventory_row should populate landing_page and distribution_url from resources."""
    item = {
        "id": "pkg-1",
        "name": "pkg-one",
        "title": "Test Dataset",
        "organization": {"title": "Test Org"},
        "tags": [{"name": "test"}],
        "notes": "Description",
        "url": "https://example.it/dataset/pkg-one",
        "resources": [
            {"url": "http://example.it/data.csv", "format": "csv"},
            {"url": "http://example.it/data.json", "format": "json"},
        ],
    }
    source_cfg = {"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.it/api"}
    row = collectors.ckan.extract_ckan_inventory_row(
        source_id="test_src",
        source_cfg=source_cfg,
        captured_at="2026-04-25T12:00:00+00:00",
        item=item,
        endpoint="https://example.it/api/package_show",
        ordinal=1,
        inventory_method="package_search",
    )
    assert row["landing_page"] == "https://example.it/dataset/pkg-one"
    assert row["distribution_url"] == "http://example.it/data.csv"
    assert row["format"] == "csv,json"


def test_extract_ckan_inventory_row_phantom_item_has_none_for_urls():
    """A phantom item (from package_list without enrichment) should have None for landing_page and distribution_url."""
    item = {"id": "123", "name": "123"}  # no title, no resources
    source_cfg = {"source_kind": "catalog", "protocol": "ckan", "base_url": "https://example.it/api"}
    row = collectors.ckan.extract_ckan_inventory_row(
        source_id="test_src",
        source_cfg=source_cfg,
        captured_at="2026-04-25T12:00:00+00:00",
        item=item,
        endpoint="https://example.it/api/package_list",
        ordinal=1,
        inventory_method="package_list",
    )
    assert row["landing_page"] is None
    assert row["distribution_url"] is None
    assert row["title"] is None


class TestErrorToStaleReason:
    """Unit tests per _error_to_stale_reason — funzione pura di mapping exception → tag."""

    @staticmethod
    def _call(exc: Exception) -> str:
        return build_catalog_inventory._error_to_stale_reason(exc)

    def test_500_internal_error(self):
        exc = Exception("HTTP 500 Internal Server Error at /api/dataflow")
        assert self._call(exc) == "source_500"

    def test_500_just_code(self):
        exc = Exception("500 Server Error")
        assert self._call(exc) == "source_500"

    def test_503_unavailable(self):
        exc = Exception("HTTP 503 Service Unavailable")
        assert self._call(exc) == "source_503"

    def test_timeout_connect(self):
        exc = Exception("ConnectTimeoutError: Connection timed out after 30s")
        assert self._call(exc) == "timeout"

    def test_timeout_read(self):
        exc = Exception("ReadTimeout: Connection timed out")
        assert self._call(exc) == "timeout"

    def test_ssl_error(self):
        exc = Exception("SSLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]")
        assert self._call(exc) == "ssl_error"

    def test_ssl_tls_error(self):
        exc = Exception("TLS negotiation failed")
        assert self._call(exc) == "ssl_error"

    def test_connection_error(self):
        exc = Exception("ConnectionError: Failed to establish connection")
        assert self._call(exc) == "connection_error"

    def test_dns_resolution_error(self):
        exc = Exception("Name or service not known: dati.example.gov.it")
        assert self._call(exc) == "dns_error"

    def test_dns_resolution(self):
        exc = Exception("ResolutionError: Could not resolve host")
        assert self._call(exc) == "dns_error"

    def test_unknown_fallback(self):
        exc = Exception("Something completely unexpected")
        assert self._call(exc) == "unknown"


class TestScanAreaPagesPagination:
    """Tests for _scan_area_pages with page_url_template (pagination)."""

    def test_page_url_template_stops_on_empty_page(self, monkeypatch):
        """Collector stops when a page has no links at all (empty HTML, no <a> tags)."""
        import collectors.html as html_collector

        call_count = [0]

        def fake_ssl_get(url, **kwargs):
            call_count[0] += 1
            page = call_count[0]
            if page == 1:
                html = '<a href="https://docs.example.com/file1.csv">file1.csv</a>'
            elif page == 2:
                html = '<a href="https://docs.example.com/file2.csv">file2.csv</a>'
            else:
                html = "<html><body><p>No results</p></body></html>"
            response = FakeJsonResponse(payload=None, text=html, headers={"content-type": "text/html"})
            return HttpResult(response=response, err=None, ssl_fallback_used=None)

        monkeypatch.setattr(html_collector, "HttpClient", lambda **kw: _FakeClient(fake_ssl_get))

        summary, rows = html_collector._scan_area_pages(
            area_pages=[],
            topic_hint=None,
            source_id="test_source",
            base_url="https://example.com",
            page_delay=0,
            page_url_template="https://example.com/data?page={page}",
            page_start=0,
            page_max=10,
            page_stop_on_empty=True,
        )

        # page 0 (links) + page 1 (links) + page 2 (empty, stop) = 3 pages scanned
        assert summary["area_pages_scanned"] == 3
        assert summary["method"] == "csv_magnet_area_pages_paginated"
        assert summary["total_links_exact"] == 2
        assert len(rows) == 2
        urls = {r["url"] for r in rows}
        assert urls == {"https://docs.example.com/file1.csv", "https://docs.example.com/file2.csv"}

    def test_page_url_template_continues_when_all_links_are_duplicates(self, monkeypatch):
        """Collector continues past pages where all links are duplicates of previous pages."""
        call_count = [0]

        def fake_ssl_get(url, **kwargs):
            call_count[0] += 1
            page = call_count[0]
            if page == 1:
                html = '<a href="https://docs.example.com/file1.csv">file1.csv</a>'
            elif page == 2:
                html = '<a href="https://docs.example.com/file1.csv">file1.csv</a>'
            elif page == 3:
                html = '<a href="https://docs.example.com/file2.csv">file2.csv</a>'
            else:
                html = "<html><body></body></html>"
            response = FakeJsonResponse(payload=None, text=html, headers={"content-type": "text/html"})
            return HttpResult(response=response, err=None, ssl_fallback_used=None)

        monkeypatch.setattr(html_collector, "HttpClient", lambda **kw: _FakeClient(fake_ssl_get))

        summary, rows = html_collector._scan_area_pages(
            area_pages=[],
            topic_hint=None,
            source_id="test_source",
            base_url="https://example.com",
            page_delay=0,
            page_url_template="https://example.com/data?page={page}",
            page_start=0,
            page_max=10,
            page_stop_on_empty=True,
        )

        # page 0 (links) + page 1 (duplicates, continue) + page 2 (new links) + page 3 (empty, stop) = 4
        assert summary["area_pages_scanned"] == 4
        assert summary["total_links_exact"] == 2
        assert len(rows) == 2

    def test_page_url_template_respects_page_max(self, monkeypatch):
        """Collector stops at page_max even if pages still have links."""
        call_count = [0]

        def fake_ssl_get(url, **kwargs):
            call_count[0] += 1
            html = f'<a href="https://docs.example.com/file{call_count[0]}.csv">file.csv</a>'
            response = FakeJsonResponse(payload=None, text=html, headers={"content-type": "text/html"})
            return HttpResult(response=response, err=None, ssl_fallback_used=None)

        monkeypatch.setattr(html_collector, "HttpClient", lambda **kw: _FakeClient(fake_ssl_get))

        summary, rows = html_collector._scan_area_pages(
            area_pages=[],
            topic_hint=None,
            source_id="test_source",
            base_url="https://example.com",
            page_delay=0,
            page_url_template="https://example.com/data?page={page}",
            page_start=0,
            page_max=3,
            page_stop_on_empty=True,
        )

        # Should have scanned exactly page_max pages
        assert summary["area_pages_scanned"] == 3
        assert len(rows) == 3


class TestContentTypeProbe:
    """Test che Content-Type probe ricalcoli by_format nella summary."""

    def test_probe_updates_by_format_in_summary(self, monkeypatch):
        """Dopo il probe, by_format deve riflettere i formati aggiornati, non quelli pre-probe."""
        # Un link ZIP -> probe dice CSV -> by_format deve contenere CSV non ZIP
        html_page = '<a href="https://example.test/data.zip">data</a>'

        def fake_ssl_get(url, **kwargs):
            return HttpResult(
                response=FakeJsonResponse(payload=None, text=html_page, headers={"content-type": "text/html"}),
                err=None, ssl_fallback_used=None,
            )

        monkeypatch.setattr(html_collector, "HttpClient", lambda **kw: _FakeClient(fake_ssl_get))

        # Monkeypatch _probe_content_type per simulare che data.zip sia in realtà CSV
        original_probe = html_collector._probe_content_type

        def fake_probe(url, timeout=5):
            if url == "https://example.test/data.zip":
                return "CSV"
            return original_probe(url, timeout=timeout)

        monkeypatch.setattr(html_collector, "_probe_content_type", fake_probe)

        source_cfg = {
            "source_kind": "catalog",
            "protocol": "html",
            "base_url": "https://example.test",
            "html_portal": {
                "probe_content_type": True,
                "delay_seconds": 0,
            },
        }

        result = html_collector.collect("test_probe", source_cfg, "2026-05-17T12:00:00+00:00")

        # La riga deve avere format=CSV (aggiornato dal probe)
        row_formats = {r.get("format") for r in result.rows}
        assert "CSV" in row_formats, f"Formato non aggiornato dal probe: {row_formats}"

        # by_format nella summary deve riflettere il formato aggiornato
        bf = result.summary.get("by_format", {})
        assert "CSV" in bf, f"by_format non contiene CSV dopo probe: {bf}"
        assert "ZIP" not in bf, f"by_format contiene ancora ZIP pre-probe: {bf}"
