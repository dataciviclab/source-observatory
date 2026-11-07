from __future__ import annotations

import pytest

from scripts.collectors.ckan import (
    _ckan_api_base,
    _ckan_search_params,
    _has_datastore_active,
    _resource_count,
    _resource_format,
    ckan_action_endpoint,
    collect_ckan_inventory_via_package_show_sample,
    collect_ckan_inventory_via_search,
    extract_ckan_inventory_row,
    force_https,
)

pytestmark = pytest.mark.pure_unit


class TestResourceHelpers:
    def test_resource_format_multiple(self):
        item = {
            "resources": [
                {"format": "CSV", "datastore_active": True},
                {"format": "CSV", "datastore_active": False},
                {"format": "XLSX"},
            ]
        }
        assert _resource_format(item) == "csv,xlsx"

    def test_resource_format_deduplicates(self):
        item = {"resources": [{"format": "CSV"}, {"format": "CSV"}, {"format": "JSON"}]}
        assert _resource_format(item) == "csv,json"

    def test_resource_format_empty_or_missing(self):
        assert _resource_format({}) is None
        assert _resource_format({"resources": []}) is None

    def test_resource_format_empty_string(self):
        item = {"resources": [{"format": ""}, {"format": "  "}, {"format": "CSV"}]}
        assert _resource_format(item) == "csv"

    def test_has_datastore_active_true(self):
        item = {
            "resources": [
                {"format": "CSV", "datastore_active": True},
                {"format": "XLSX", "datastore_active": False},
            ]
        }
        assert _has_datastore_active(item) is True

    def test_has_datastore_active_false(self):
        item = {"resources": [{"datastore_active": False}, {"datastore_active": False}]}
        assert _has_datastore_active(item) is False

    def test_has_datastore_active_no_resources(self):
        assert _has_datastore_active({}) is False
        assert _has_datastore_active({"resources": []}) is False

    def test_resource_count(self):
        assert _resource_count({"resources": [1, 2, 3]}) == 3
        assert _resource_count({}) == 0
        assert _resource_count({"resources": []}) == 0


class TestCkanApiHelpers:
    def test_ckan_api_base_standard(self):
        assert (
            _ckan_api_base("https://ckan.example.org/api/3/action/package_list")
            == "https://ckan.example.org/api/3/action"
        )

    def test_ckan_api_base_non_standard(self):
        assert (
            _ckan_api_base("https://ckan.example.org/odapi/package_list")
            == "https://ckan.example.org/odapi"
        )

    def test_ckan_action_endpoint_standard(self):
        url = ckan_action_endpoint(
            "https://ckan.example.org/api/3/action/package_list", "package_show"
        )
        assert url == "https://ckan.example.org/api/3/action/package_show"

    def test_ckan_action_endpoint_non_standard(self):
        url = ckan_action_endpoint("https://ckan.example.org/odapi", "package_show")
        assert "/package_show" in url


class TestExtractInventoryRow:
    def _make_item(self, **overrides):
        base = {
            "id": "ds-123",
            "name": "test-dataset",
            "title": "Test Dataset",
            "organization": {"title": "Test Org"},
            "tags": [{"name": "tag1"}, {"display_name": "tag2"}],
            "notes": "Description of dataset.",
            "resources": [
                {"id": "r1", "format": "CSV", "datastore_active": True, "url": "http://a.csv"},
                {"id": "r2", "format": "XLSX", "datastore_active": False, "url": "http://b.xlsx"},
            ],
        }
        base.update(overrides)
        return base

    def test_new_fields_present(self):
        item = self._make_item()
        row = extract_ckan_inventory_row(
            source_id="test-ckan",
            source_cfg={"source_kind": "ckan", "protocol": "CKAN"},
            captured_at="2026-04-22",
            item=item,
            endpoint="http://api/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["format"] == "csv,xlsx"
        assert row["datastore_active"] is True
        assert row["resource_count"] == 2
        assert row["title"] == "Test Dataset"
        assert row["tags"] == "tag1, tag2"

    def test_datastore_active_false_when_no_resources(self):
        item = self._make_item(resources=[])
        row = extract_ckan_inventory_row(
            source_id="test-ckan",
            source_cfg={"source_kind": "ckan", "protocol": "CKAN"},
            captured_at="2026-04-22",
            item=item,
            endpoint="http://api/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["datastore_active"] is False
        assert row["resource_count"] == 0
        assert row["format"] is None

    def test_extract_without_organization(self):
        item = self._make_item()
        item.pop("organization")
        item["author"] = "Test Author"
        row = extract_ckan_inventory_row(
            source_id="test-ckan",
            source_cfg={"source_kind": "ckan", "protocol": "CKAN"},
            captured_at="2026-04-22",
            item=item,
            endpoint="http://api/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["organization"] == "Test Author"

    def test_extract_without_tags(self):
        item = self._make_item()
        item["tags"] = []
        row = extract_ckan_inventory_row(
            source_id="test-ckan",
            source_cfg={"source_kind": "ckan", "protocol": "CKAN"},
            captured_at="2026-04-22",
            item=item,
            endpoint="http://api/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["tags"] is None


class TestPackageShowSample:
    def _make_rows(self, n):
        return [{"item_id": f"pkg-{i}", "ordinal": i + 1} for i in range(n)]

    def test_package_show_timeout_forwarded(self, monkeypatch):
        """package_show_timeout dal registry arriva a ckan_get_json."""
        from scripts.collectors import ckan as ckan_module

        captured_timeouts: list[int] = []

        original = ckan_module.ckan_get_json

        def fake_ckan_get_json(url, **kw):
            captured_timeouts.append(kw.get("timeout", -1))
            return {
                "success": True,
                "result": {
                    "id": "x",
                    "name": "x",
                    "title": "x",
                    "organization": {},
                    "tags": [],
                    "notes": "",
                    "resources": [],
                },
            }

        try:
            monkeypatch.setattr(ckan_module, "ckan_get_json", fake_ckan_get_json)
            rows = self._make_rows(3)
            enriched, _ = collect_ckan_inventory_via_package_show_sample(
                source_id="test",
                source_cfg={"inventory": {"package_show_timeout": 5}, "base_url": "http://api"},
                captured_at="2026-06-14",
                package_list_rows=rows,
                sample_size=3,
            )
            assert len(enriched) == 3
            assert all(t == 5 for t in captured_timeouts), (
                f"timeout non inoltrato: {captured_timeouts}"
            )
        finally:
            monkeypatch.setattr(ckan_module, "ckan_get_json", original)

    def test_package_show_sample_enriches_rows(self, monkeypatch):
        from scripts.collectors import ckan as ckan_module

        original = ckan_module.ckan_get_json

        def fake_ckan_get_json(url, **kw):
            params = kw.get("params", {})
            pkg_id = params.get("id", "")
            return {
                "success": True,
                "result": {
                    "id": pkg_id,
                    "name": pkg_id,
                    "title": f"Title {pkg_id}",
                    "organization": {"title": "Sample Org"},
                    "tags": [],
                    "notes": "Sample description.",
                    "resources": [
                        {"id": f"{pkg_id}-r1", "format": "CSV", "datastore_active": True},
                    ],
                },
            }

        try:
            monkeypatch.setattr(ckan_module, "ckan_get_json", fake_ckan_get_json)
            rows = self._make_rows(5)
            enriched, warning = collect_ckan_inventory_via_package_show_sample(
                source_id="test",
                source_cfg={"source_kind": "ckan", "protocol": "CKAN", "base_url": "http://api"},
                captured_at="2026-04-22",
                package_list_rows=rows,
                sample_size=5,
            )
            assert len(enriched) == 5
            assert all(row.get("datastore_active") is True for row in enriched)
            assert all(row.get("format") == "csv" for row in enriched)
        finally:
            monkeypatch.setattr(ckan_module, "ckan_get_json", original)

    def test_package_show_sample_partial_warning(self, monkeypatch):
        from scripts.collectors import ckan as ckan_module

        original = ckan_module.ckan_get_json

        def fake_ckan_get_json(url, **kw):
            params = kw.get("params", {})
            pkg_id = params.get("id", "")
            try:
                idx = int(pkg_id.split("-")[1])
                if idx % 2 == 0:
                    raise Exception("simulated error")
            except (ValueError, IndexError):
                pass
            return {
                "success": True,
                "result": {
                    "id": pkg_id,
                    "name": pkg_id,
                    "title": f"Title {pkg_id}",
                    "organization": {},
                    "tags": [],
                    "notes": "Desc.",
                    "resources": [],
                },
            }

        try:
            monkeypatch.setattr(ckan_module, "ckan_get_json", fake_ckan_get_json)
            rows = self._make_rows(4)
            enriched, warning = collect_ckan_inventory_via_package_show_sample(
                source_id="test",
                source_cfg={"source_kind": "ckan", "protocol": "CKAN", "base_url": "http://api"},
                captured_at="2026-04-22",
                package_list_rows=rows,
                sample_size=4,
            )
            assert len(enriched) == 2
            assert warning is not None
            assert warning["type"] == "package_show_sample_partial"
            assert warning["rows_enriched"] == 2
            assert warning["sample_size"] == 4
        finally:
            monkeypatch.setattr(ckan_module, "ckan_get_json", original)

    def test_package_show_sample_empty_list(self, monkeypatch):
        from scripts.collectors import ckan as ckan_module

        original = ckan_module.ckan_get_json

        try:
            monkeypatch.setattr(
                ckan_module, "ckan_get_json", lambda *a, **k: {"success": True, "result": {}}
            )
            enriched, warning = collect_ckan_inventory_via_package_show_sample(
                source_id="test",
                source_cfg={"source_kind": "ckan", "protocol": "CKAN", "base_url": "http://api"},
                captured_at="2026-04-22",
                package_list_rows=[],
                sample_size=10,
            )
            assert enriched == []
            assert warning is None
        finally:
            monkeypatch.setattr(ckan_module, "ckan_get_json", original)


class TestCkanSearchParams:
    """Test per _ckan_search_params — costruzione params con/senza fq."""

    def test_without_fq(self):
        params = _ckan_search_params({"inventory": {}}, page_size=100, start=0)
        assert params == {"rows": 100, "start": 0}

    def test_with_fq(self):
        params = _ckan_search_params(
            {"inventory": {"fq": "organization:anac"}},
            page_size=100,
            start=0,
        )
        assert params == {"rows": 100, "start": 0, "fq": "organization:anac"}

    def test_with_fq_no_inventory_key(self):
        """Se inventory non esiste, non crasha."""
        params = _ckan_search_params({}, page_size=50, start=25)
        assert params == {"rows": 50, "start": 25}

    def test_with_fq_inventory_is_none(self):
        params = _ckan_search_params({"inventory": None}, page_size=10, start=5)
        assert params == {"rows": 10, "start": 5}

    def test_fq_with_spaces_and_special_chars(self):
        """Verifica che fq con caratteri speciali venga passato così com'è
        (la codifica URL è gestita da requests.get(params=...))."""
        fq_val = 'organization:"ministero-delle-imprese-e-del-made-in-italy"'
        params = _ckan_search_params(
            {"inventory": {"fq": fq_val}},
            page_size=100,
            start=0,
        )
        assert params["fq"] == fq_val


class TestSearchWithFqPropagation:
    """Test che fq venga propagato da source_cfg a ckan_get_json."""

    def test_via_search_passes_fq_to_ckan_get_json(self, monkeypatch):
        captured_params: dict | None = None

        def fake_ckan_get_json(endpoint, **kwargs):
            nonlocal captured_params
            captured_params = kwargs.get("params")
            return {"success": True, "result": {"results": [], "count": 0}}

        monkeypatch.setattr("scripts.collectors.ckan.ckan_get_json", fake_ckan_get_json)

        source_cfg = {
            "base_url": "https://dati.gov.it/opendata/api/3/action/package_list?limit=1",
            "inventory": {"fq": "organization:anac"},
        }
        try:
            collect_ckan_inventory_via_search(
                source_id="test-fq", source_cfg=source_cfg, captured_at="2026-05-24"
            )
        except Exception:
            pass  # può sollevare ValueError per results vuoti

        assert captured_params is not None, "ckan_get_json non è stata chiamata"
        assert captured_params.get("fq") == "organization:anac", (
            f"expected fq='organization:anac', got {captured_params}"
        )

    def test_via_search_without_fq(self, monkeypatch):
        captured_params: dict | None = None

        def fake_ckan_get_json(endpoint, **kwargs):
            nonlocal captured_params
            captured_params = kwargs.get("params")
            return {"success": True, "result": {"results": [], "count": 0}}

        monkeypatch.setattr("scripts.collectors.ckan.ckan_get_json", fake_ckan_get_json)

        source_cfg = {
            "base_url": "https://dati.gov.it/opendata/api/3/action/package_list?limit=1",
            "inventory": {},
        }
        try:
            collect_ckan_inventory_via_search(
                source_id="test-no-fq", source_cfg=source_cfg, captured_at="2026-05-24"
            )
        except Exception:
            pass

        assert captured_params is not None, "ckan_get_json non è stata chiamata"
        assert "fq" not in captured_params, (
            f"fq non dovrebbe essere presente, ma c'è: {captured_params}"
        )


class TestBestResourceUrl:
    def test_prefers_datastore_dump_over_pdf_labeled_csv(self):
        """OpenBDAP: due resource "csv", il primo punta a un PDF."""
        row = extract_ckan_inventory_row(
            source_id="openbdap",
            source_cfg={"inventory": {}},
            captured_at="2026-11-07",
            item={
                "id": "x",
                "name": "x",
                "title": "x",
                "resources": [
                    {
                        "format": "CSV",
                        "url": "https://x.test//sites/default/files/report/1_dati.pdf",
                    },
                    {
                        "format": "csv",
                        "url": "https://x.test/SpodCkanApi/api/3/datastore/dump/uuid.csv",
                    },
                    {"format": "XML", "url": "https://x.test/ODataProxy/MdData('y')/DataRows"},
                ],
            },
            endpoint="https://x.test/api/3/action/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert "/datastore/dump/" in row["distribution_url"]

    def test_pdf_only_resource_still_returned(self):
        row = extract_ckan_inventory_row(
            source_id="test",
            source_cfg={"inventory": {}},
            captured_at="2026-11-07",
            item={
                "id": "x",
                "name": "x",
                "title": "x",
                "resources": [{"format": "PDF", "url": "https://x.test/a.pdf"}],
            },
            endpoint="https://x.test/api/3/action/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["distribution_url"] == "https://x.test/a.pdf"


class TestResourceSize:
    def test_sums_declared_sizes(self):
        item = {
            "resources": [
                {"format": "CSV", "size": "1000"},
                {"format": "XML", "size": "250"},
                {"format": "CSV", "size": ""},
            ]
        }
        row = extract_ckan_inventory_row(
            source_id="test",
            source_cfg={"inventory": {}},
            captured_at="2026-11-07",
            item=item,
            endpoint="https://x.test/api/3/action/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["download_size_bytes"] == 1250

    def test_none_when_size_not_declared(self):
        item = {"resources": [{"format": "CSV"}, {"format": "CSV", "size": "n/a"}]}
        row = extract_ckan_inventory_row(
            source_id="test",
            source_cfg={"inventory": {}},
            captured_at="2026-11-07",
            item=item,
            endpoint="https://x.test/api/3/action/package_search",
            ordinal=1,
            inventory_method="package_search",
        )
        assert row["download_size_bytes"] is None


class TestForceHttps:
    """Upgrade opt-in degli URL http:// (OpenBDAP: http morto, https ok)."""

    def test_upgrades_http(self):
        assert force_https("http://x.test/a.csv") == "https://x.test/a.csv"

    def test_idempotent_on_https(self):
        assert force_https("https://x.test/a.csv") == "https://x.test/a.csv"

    def test_preserves_empty(self):
        assert force_https(None) is None
        assert force_https("") == ""

    def test_opt_in_in_extract_row(self):
        item = {
            "id": "ds-1",
            "name": "ds-1",
            "title": "T",
            "resources": [{"format": "CSV", "url": "http://x.test/a.csv"}],
        }
        common = {
            "source_id": "test",
            "captured_at": "2026-11-07",
            "item": item,
            "endpoint": "https://x.test/api/3/action/package_search",
            "ordinal": 1,
            "inventory_method": "package_search",
        }
        plain = extract_ckan_inventory_row(source_cfg={"inventory": {}}, **common)
        forced = extract_ckan_inventory_row(
            source_cfg={"inventory": {"force_https": True}}, **common
        )
        assert plain["distribution_url"] == "http://x.test/a.csv"
        assert forced["distribution_url"] == "https://x.test/a.csv"


class TestSearchPaginationConfig:
    """La paginazione non deve fidarsi di count e deve essere configurabile."""

    def _fake_pages(self, pages: dict[tuple[int, int], list[dict]], captured: list[dict]):
        def fake_ckan_get_json(endpoint, **kwargs):
            params = kwargs.get("params", {})
            captured.append(params)
            key = (params.get("start"), params.get("rows"))
            items = pages.get(key, [])
            return {"success": True, "result": {"results": items, "count": len(items)}}

        return fake_ckan_get_json

    def _item(self, i: int) -> dict:
        return {
            "id": f"pkg-{i}",
            "name": f"pkg-{i}",
            "title": f"Title {i}",
            "tags": [],
            "resources": [],
        }

    def test_page_size_from_config(self, monkeypatch):
        captured: list[dict] = []
        pages = {(0, 25): [self._item(i) for i in range(25)], (25, 25): []}
        monkeypatch.setattr(
            "scripts.collectors.ckan.ckan_get_json", self._fake_pages(pages, captured)
        )
        rows = collect_ckan_inventory_via_search(
            source_id="test",
            source_cfg={
                "base_url": "https://x.test/api/3/action/package_list",
                "inventory": {"package_search_page_size": 25},
            },
            captured_at="2026-11-07",
        )
        assert len(rows) == 25
        assert [p["rows"] for p in captured] == [25, 25]
        assert [p["start"] for p in captured] == [0, 25]

    def test_timeout_forwarded(self, monkeypatch):
        captured_timeouts: list[int] = []

        def fake(endpoint, **kwargs):
            captured_timeouts.append(kwargs.get("timeout", -1))
            return {"success": True, "result": {"results": [], "count": 0}}

        monkeypatch.setattr("scripts.collectors.ckan.ckan_get_json", fake)
        with pytest.raises(ValueError):
            collect_ckan_inventory_via_search(
                source_id="test",
                source_cfg={
                    "base_url": "https://x.test/api/3/action/package_list",
                    "inventory": {"package_search_timeout": 42, "package_search_retries": 1},
                },
                captured_at="2026-11-07",
            )
        assert captured_timeouts and all(t == 42 for t in captured_timeouts)

    def test_retry_halves_page_size_then_recovers(self, monkeypatch):
        """Una pagina che va in timeout non uccide il run: si dimezza e si ritenta."""
        attempts: list[tuple[int, int]] = []
        pages = {(0, 25): [self._item(i) for i in range(25)], (25, 25): []}

        def fake(endpoint, **kwargs):
            params = kwargs.get("params", {})
            key = (params.get("start"), params.get("rows"))
            attempts.append(key)
            if key not in pages:
                raise TimeoutError("simulated timeout")
            items = pages.get(key, [])
            return {"success": True, "result": {"results": items, "count": len(items)}}

        monkeypatch.setattr("scripts.collectors.ckan.ckan_get_json", fake)
        rows = collect_ckan_inventory_via_search(
            source_id="test",
            source_cfg={
                "base_url": "https://x.test/api/3/action/package_list",
                "inventory": {
                    "package_search_page_size": 100,
                    "package_search_retries": 2,
                    "package_search_min_page_size": 25,
                },
            },
            captured_at="2026-11-07",
        )
        assert len(rows) == 25
        # 100 -> timeout -> 50 -> timeout -> 25 -> ok, poi start=25 con rows=25
        assert (0, 100) in attempts and (0, 50) in attempts and (0, 25) in attempts
        assert (25, 25) in attempts

    def test_raises_when_page_always_fails(self, monkeypatch):
        def fake(endpoint, **kwargs):
            raise TimeoutError("always")

        monkeypatch.setattr("scripts.collectors.ckan.ckan_get_json", fake)
        with pytest.raises(TimeoutError):
            collect_ckan_inventory_via_search(
                source_id="test",
                source_cfg={
                    "base_url": "https://x.test/api/3/action/package_list",
                    "inventory": {
                        "package_search_page_size": 20,
                        "package_search_retries": 1,
                        "package_search_min_page_size": 20,
                    },
                },
                captured_at="2026-11-07",
            )


pytestmark = pytest.mark.pure_unit
