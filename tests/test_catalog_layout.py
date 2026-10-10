"""Test per scripts/catalog/layout.py — per-repo paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.catalog.layout import RepoLayout, resolve_layout


class TestRepoLayout:
    @pytest.mark.pure_unit
    def test_paths(self, tmp_path: Path):
        layout = RepoLayout(repo_root=tmp_path)
        assert layout.pyproject == tmp_path / "pyproject.toml"
        assert layout.catalog_path == tmp_path / "registry" / "catalog.json"
        assert layout.toolkit_registry_path == tmp_path / "registry" / "registry.json"
        assert layout.out_dir == tmp_path / "out" / "so"
        assert layout.inventory_parquet == tmp_path / "out" / "so" / "inventory.parquet"
        assert layout.validated_parquet == tmp_path / "out" / "so" / "validated.parquet"

    @pytest.mark.pure_unit
    def test_resolve_default_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        layout = resolve_layout()
        assert layout.repo_root == tmp_path.resolve()

    @pytest.mark.pure_unit
    def test_resolve_explicit_root(self, tmp_path: Path):
        layout = resolve_layout(tmp_path)
        assert layout.repo_root == tmp_path.resolve()
        assert isinstance(layout, RepoLayout)
