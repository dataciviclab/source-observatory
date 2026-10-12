"""Test per scripts/catalog/upstream.py — estrazione riferimenti da dataset.yml."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.catalog.upstream import (
    extract_upstream_from_dataset_yml,
    extract_upstream_from_source,
    load_upstream_map,
)


class TestExtractFromSource:
    @pytest.mark.pure_unit
    def test_sdmx_flow(self):
        refs = extract_upstream_from_source(
            {"type": "sdmx", "args": {"agency": "ESTAT", "flow": "DEMO_R_D3DENS"}}
        )
        assert refs == [{"kind": "dataflow", "id": "DEMO_R_D3DENS", "agency": "ESTAT"}]

    @pytest.mark.pure_unit
    def test_ckan_resource_id(self):
        refs = extract_upstream_from_source(
            {"type": "ckan", "args": {"resource_id": "85c1ab95-x", "portal_url": "https://x"}}
        )
        assert refs == [{"kind": "ckan_resource", "id": "85c1ab95-x"}]

    @pytest.mark.pure_unit
    def test_http_file_url(self):
        refs = extract_upstream_from_source(
            {"type": "http_file", "args": {"url": "https://x/y.csv", "filename": "y.csv"}}
        )
        assert refs == [{"kind": "url", "id": "https://x/y.csv"}]

    @pytest.mark.pure_unit
    def test_script_type_flag(self):
        refs = extract_upstream_from_source(
            {
                "type": "script",
                "args": {"command": "python ../../prefetch.py raw_input.csv --type sentenze"},
            }
        )
        assert refs == [{"kind": "script_type", "id": "sentenze"}]

    @pytest.mark.pure_unit
    def test_script_without_type(self):
        refs = extract_upstream_from_source({"type": "script", "args": {"command": "python x.py"}})
        assert refs == []

    @pytest.mark.pure_unit
    def test_unknown_type_ignored(self):
        assert extract_upstream_from_source({"type": "local_file", "args": {}}) == []


class TestExtractFromDatasetYml:
    @pytest.mark.pure_unit
    def test_aggregates_and_dedups(self):
        text = """
dataset:
  name: demo
raw:
  sources:
  - name: a
    type: sdmx
    args: {agency: ESTAT, flow: F1}
  - name: b
    type: sdmx
    args: {agency: ESTAT, flow: F1}
  - name: c
    type: script
    args: {command: "python p.py --type sentenze"}
"""
        refs = extract_upstream_from_dataset_yml(text)
        assert refs == [
            {"kind": "dataflow", "id": "F1", "agency": "ESTAT"},
            {"kind": "script_type", "id": "sentenze"},
        ]

    @pytest.mark.pure_unit
    def test_invalid_yaml_returns_empty(self):
        assert extract_upstream_from_dataset_yml("{{{ not yaml") == []


class TestLoadUpstreamMap:
    @pytest.mark.pure_unit
    def test_scans_dataset_dirs_by_name(self, tmp_path: Path):
        ds_dir = tmp_path / "datasets" / "ga-sentenze"
        ds_dir.mkdir(parents=True)
        (ds_dir / "dataset.yml").write_text(
            """
dataset:
  name: ga_sentenze
raw:
  sources:
  - name: openga
    type: script
    args: {command: "python prefetch.py x.csv --type sentenze"}
""",
            encoding="utf-8",
        )
        m = load_upstream_map(tmp_path)
        assert m == {"ga_sentenze": [{"kind": "script_type", "id": "sentenze"}]}

    @pytest.mark.pure_unit
    def test_missing_dirs_ok(self, tmp_path: Path):
        assert load_upstream_map(tmp_path) == {}
