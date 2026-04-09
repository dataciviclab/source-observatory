from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "build_catalog_inventory.py"
)
SPEC = importlib.util.spec_from_file_location("build_catalog_inventory", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
build_catalog_inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_catalog_inventory)


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
    monkeypatch.setattr(build_catalog_inventory.time, "sleep", lambda _seconds: None)

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

    rows, warning = build_catalog_inventory.collect_ckan_inventory(
        "inps", source_cfg, "2026-04-09T12:00:00+00:00"
    )

    assert len(rows) == 1
    assert rows[0]["item_id"] == "544"
    assert rows[0]["title"] is None
    assert warning is not None
    assert warning["type"] == "skip_current_package_list"

