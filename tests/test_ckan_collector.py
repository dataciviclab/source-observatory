from __future__ import annotations

import pytest
from collectors.ckan import (
    _ckan_api_base,
    _ckan_search_params,
    _has_datastore_active,
    _resource_count,
    _resource_format,
    ckan_action_endpoint,
    collect_ckan_inventory_via_package_show_sample,
    collect_ckan_inventory_via_search,
    extract_ckan_inventory_row,
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

    def test_package_show_sample_enriches_rows(self, monkeypatch):
        from collectors import ckan as ckan_module

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
        from collectors import ckan as ckan_module

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
        from collectors import ckan as ckan_module

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

        monkeypatch.setattr("collectors.ckan.ckan_get_json", fake_ckan_get_json)

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

        monkeypatch.setattr("collectors.ckan.ckan_get_json", fake_ckan_get_json)

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


pytestmark = pytest.mark.pure_unit
