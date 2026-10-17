"""Test per scripts/catalog/drift.py — referenced-item drift check."""

from __future__ import annotations

import pytest

from scripts.catalog.drift import check_referenced_items

_INV = [
    {
        "item_id": "CRIM_GEN_REG",
        "item_name": "crim-gen-reg",
        "title": "Criminality",
        "distribution_url": "https://ex.it/data/CRIM_GEN_REG",
    },
    {
        "item_id": "sentenze-roma",
        "item_name": "tar-roma-sentenze",
        "title": "Sentenze TAR Roma",
        "distribution_url": "https://ex.it/s/roma",
    },
    {
        "item_id": "cig-2024",
        "item_name": "cig-2024",
        "title": "CIG 2024",
        "distribution_url": "https://ex.it/d/cig-2024-uuid",
    },
    {
        "item_id": "fsc-2025",
        "item_name": "fsc-2025",
        "title": "FSC 2025",
        "distribution_url": "https://docs.ex.it/2025_VAR_FSC_1_2025_csv.zip",
    },
]


def _ds(slug, refs):
    return {"slug": slug, "status": "incubating", "upstream": refs}


class TestCheckReferencedItems:
    @pytest.mark.pure_unit
    def test_empty_inventory_skips(self):
        result = check_referenced_items([_ds("a", [{"kind": "dataflow", "id": "X"}])], [])
        assert result == {"checked": 0, "matched": 0, "missing": []}

    @pytest.mark.pure_unit
    def test_no_upstream(self):
        result = check_referenced_items([{"slug": "a", "status": "x"}], _INV)
        assert result == {"checked": 0, "matched": 0, "missing": []}

    @pytest.mark.pure_unit
    def test_dataflow_match(self):
        ds = [_ds("g", [{"kind": "dataflow", "id": "CRIM_GEN_REG"}])]
        result = check_referenced_items(ds, _INV)
        assert result["checked"] == 1
        assert result["matched"] == 1
        assert result["missing"] == []

    @pytest.mark.pure_unit
    def test_dataflow_missing(self):
        ds = [_ds("g", [{"kind": "dataflow", "id": "NOT_EXISTS"}])]
        result = check_referenced_items(ds, _INV)
        assert result["missing"] == [{"slug": "g", "kind": "dataflow", "id": "NOT_EXISTS"}]

    @pytest.mark.pure_unit
    def test_script_type_match(self):
        ds = [_ds("ga_sentenze", [{"kind": "script_type", "id": "sentenze"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1

    @pytest.mark.pure_unit
    def test_script_type_missing(self):
        ds = [_ds("x", [{"kind": "script_type", "id": "subappalti"}])]
        result = check_referenced_items(ds, _INV)
        assert len(result["missing"]) == 1

    @pytest.mark.pure_unit
    def test_ckan_dataset_match_with_placeholder(self):
        ds = [_ds("bandi", [{"kind": "ckan_dataset", "id": "cig-{year}"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1  # cig-2024 matcha il prefisso cig-

    @pytest.mark.pure_unit
    def test_ckan_resource_match(self):
        ds = [_ds("a", [{"kind": "ckan_resource", "id": "cig-2024-uuid"}])]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1

    @pytest.mark.pure_unit
    def test_url_match_with_placeholder(self):
        ds = [
            _ds(
                "fsc", [{"kind": "url", "id": "https://docs.ex.it/{year}_VAR_FSC_1_{year}_csv.zip"}]
            )
        ]
        result = check_referenced_items(ds, _INV)
        assert result["matched"] == 1  # prefix https://docs.ex.it/ matcha

    @pytest.mark.pure_unit
    def test_url_missing(self):
        ds = [_ds("x", [{"kind": "url", "id": "https://other.ex.it/data.csv"}])]
        result = check_referenced_items(ds, _INV)
        assert len(result["missing"]) == 1

    @pytest.mark.pure_unit
    def test_mixed_match_and_missing(self):
        ds = [
            _ds(
                "g",
                [{"kind": "dataflow", "id": "CRIM_GEN_REG"}, {"kind": "dataflow", "id": "GONE"}],
            ),
            _ds("s", [{"kind": "script_type", "id": "sentenze"}]),
        ]
        result = check_referenced_items(ds, _INV)
        assert result["checked"] == 3
        assert result["matched"] == 2
        assert len(result["missing"]) == 1
        assert result["missing"][0]["id"] == "GONE"
