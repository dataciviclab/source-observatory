from __future__ import annotations

import build_catalog_inventory
import collectors.ckan
import collectors.sparql


class FakeJsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


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

    monkeypatch.setattr(collectors.sparql.requests, "get", fake_get)

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
