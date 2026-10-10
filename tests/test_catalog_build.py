"""Test per scripts/catalog/build.py — build_catalog end-to-end (no HTTP)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.catalog.build import (
    build_catalog,
    compute_streak,
    load_catalog_schema,
    load_local_datasets_in_use,
    load_previous_catalog,
    validate_catalog,
)
from scripts.catalog.layout import resolve_layout
from scripts.collectors.base import CollectorResult
from scripts.radar_check import ProbeResult

_PYPROJECT = """
[project]
name = "demo-repo"

[tool.observatory]
source_id = "demo_src"
protocol = "ckan"
base_url = "https://example.test/api/3/action/package_list"
verdict = "go"

[tool.toolkit.extends]
source_id = "demo_src"
"""

_REGISTRY = {
    "schema_version": 1,
    "repo": "demo-repo",
    "datasets": [
        {"slug": "demo_published", "source_id": "demo_src", "stage": "published"},
        {"slug": "demo_incubating", "source_id": "demo_src", "stage": "incubating"},
        {"slug": "other_src_ds", "source_id": "altro", "stage": "published"},
    ],
}

_INVENTORY_ROWS = [
    {
        "item_id": "a",
        "item_name": "alpha",
        "format": "CSV",
        "distribution_url": "https://example.test/alpha.csv",
        "organization": "Demo Org",
    },
    {
        "item_id": "b",
        "item_name": "beta",
        "format": "JSON",
        "distribution_url": "https://example.test/beta.json",
        "organization": "Demo Org",
    },
]

_VALIDATED = [
    {
        "dataset_group": "demo_src/alpha",
        "source_id": "demo_src",
        "reachable": True,
        "readiness_score": 3,
        "format": "csv",
        "num_columns": 8,
        "dataset_group_year_min": 2020,
        "dataset_group_year_max": 2024,
        "url": "https://example.test/alpha.csv",
    },
    {
        "dataset_group": "demo_src/beta",
        "source_id": "demo_src",
        "reachable": True,
        "readiness_score": 2,
        "format": "json",
        "num_columns": 0,
        "dataset_group_year_min": None,
        "dataset_group_year_max": None,
        "url": "https://example.test/beta.json",
    },
]


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo-repo"
    (repo / "registry").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (repo / "registry" / "registry.json").write_text(json.dumps(_REGISTRY), encoding="utf-8")
    return repo


def _patch_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralizza HTTP: probe/dispatch/validate restituiscono fixture."""

    def fake_probe(base_url: str) -> ProbeResult:
        return ProbeResult(status="GREEN", http_code="200", note=None, final_url=base_url)

    def fake_dispatch(source_id, source_cfg, captured_at) -> CollectorResult:
        return CollectorResult(rows=[dict(r) for r in _INVENTORY_ROWS])

    def fake_merge(df, dry_run: bool = False):
        df = df.copy()
        df["dataset_group"] = df["item_name"].map(lambda n: f"demo_src/{n}")
        return df

    def fake_validate(df, max_groups=None, workers: int = 1):
        return [dict(r) for r in _VALIDATED]

    monkeypatch.setattr("scripts.catalog.build.probe_url", fake_probe)
    monkeypatch.setattr("scripts.catalog.build.dispatch", fake_dispatch)
    monkeypatch.setattr("scripts.catalog.build.run_merge", fake_merge)
    monkeypatch.setattr("scripts.catalog.build.run_validate", fake_validate)


# ── schema ───────────────────────────────────────────────────────────────────


class TestCatalogSchema:
    @pytest.mark.contract
    def test_schema_loads_and_is_valid_draft(self):
        import jsonschema

        schema = load_catalog_schema()
        # Validare lo schema contro se stesso e' sufficiente come smoke.
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert "source_id" in schema["required"]


# ── compute_streak ───────────────────────────────────────────────────────────


class TestComputeStreak:
    @pytest.mark.pure_unit
    def test_first_run(self):
        assert compute_streak({"radar_status": "GREEN"}, None) == 1

    @pytest.mark.pure_unit
    def test_same_status_increments(self):
        prev = {"health": {"radar_status": "GREEN", "streak": 3}}
        assert compute_streak({"radar_status": "GREEN"}, prev) == 4

    @pytest.mark.pure_unit
    def test_status_change_resets(self):
        prev = {"health": {"radar_status": "GREEN", "streak": 7}}
        assert compute_streak({"radar_status": "RED"}, prev) == 1

    @pytest.mark.pure_unit
    def test_missing_streak_defaults(self):
        prev = {"health": {"radar_status": "GREEN"}}
        assert compute_streak({"radar_status": "GREEN"}, prev) == 2


# ── load_local_datasets_in_use ───────────────────────────────────────────────


class TestLoadLocalDatasetsInUse:
    @pytest.mark.pure_unit
    def test_filters_by_source_id_and_stage(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        layout = resolve_layout(repo)
        ds = load_local_datasets_in_use(layout, "demo_src")
        assert ds == [
            {"slug": "demo_published", "status": "published"},
            {"slug": "demo_incubating", "status": "incubating"},
        ]

    @pytest.mark.pure_unit
    def test_missing_registry_returns_empty(self, tmp_path: Path):
        layout = resolve_layout(tmp_path)
        assert load_local_datasets_in_use(layout, "x") == []


# ── build_catalog end-to-end ─────────────────────────────────────────────────


class TestBuildCatalog:
    @pytest.mark.contract
    def test_end_to_end(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)

        catalog = build_catalog(repo, write=True)

        # Struttura
        assert catalog["source_id"] == "demo_src"
        assert catalog["repo"] == "demo-repo"
        assert catalog["catalog_schema_version"] == 1
        assert catalog["health"]["radar_status"] == "GREEN"
        assert catalog["health"]["streak"] == 1
        assert catalog["inventory"]["total_items"] == 2
        assert catalog["source_check"]["total_scored"] == 2
        assert catalog["source_check"]["reachable"] == 2
        assert catalog["datasets_in_use"] == [
            {"slug": "demo_published", "status": "published"},
            {"slug": "demo_incubating", "status": "incubating"},
        ]
        assert catalog["operational_verdict"]["label"] in {
            "STABLE",
            "INVENTORY_CHANGED",
            "PARTIALLY_SCOPED",
        }

        # Artifact scritti
        layout = resolve_layout(repo)
        assert layout.catalog_path.exists()
        assert layout.inventory_parquet.exists()
        assert layout.validated_parquet.exists()

        # catalog.json sul disco == dict ritornato + valid vs schema
        on_disk = json.loads(layout.catalog_path.read_text(encoding="utf-8"))
        validate_catalog(on_disk)
        assert on_disk["source_id"] == "demo_src"

    @pytest.mark.contract
    def test_streak_from_previous_catalog(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)

        build_catalog(repo, write=True)
        catalog2 = build_catalog(repo, write=True)
        assert catalog2["health"]["streak"] == 2

    @pytest.mark.contract
    def test_skip_validate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)

        catalog = build_catalog(repo, skip_validate=True, write=False)
        assert catalog["source_check"]["total_scored"] == 0
        assert catalog["inventory"]["total_items"] == 2

    @pytest.mark.contract
    def test_dry_run_does_not_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)

        catalog = build_catalog(repo, write=False)
        layout = resolve_layout(repo)
        assert not layout.catalog_path.exists()
        assert catalog["source_id"] == "demo_src"

    @pytest.mark.contract
    def test_invalid_config_raises(self, tmp_path: Path):
        repo = tmp_path / "broken"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(
            "[tool.observatory]\nsource_id = 'x'\n", encoding="utf-8"
        )
        from scripts.catalog.config import ObservatoryConfigError

        with pytest.raises(ObservatoryConfigError):
            build_catalog(repo, write=False)


# ── load_previous_catalog ────────────────────────────────────────────────────


class TestLoadPreviousCatalog:
    @pytest.mark.pure_unit
    def test_missing_returns_none(self, tmp_path: Path):
        assert load_previous_catalog(resolve_layout(tmp_path)) is None

    @pytest.mark.pure_unit
    def test_corrupt_returns_none(self, tmp_path: Path):
        layout = resolve_layout(tmp_path)
        layout.catalog_path.parent.mkdir(parents=True)
        layout.catalog_path.write_text("{not json", encoding="utf-8")
        assert load_previous_catalog(layout) is None

    @pytest.mark.pure_unit
    def test_reads_previous(self, tmp_path: Path):
        layout = resolve_layout(tmp_path)
        layout.catalog_path.parent.mkdir(parents=True)
        payload = {"health": {"radar_status": "GREEN", "streak": 5}}
        layout.catalog_path.write_text(json.dumps(payload), encoding="utf-8")
        assert load_previous_catalog(layout) == payload
