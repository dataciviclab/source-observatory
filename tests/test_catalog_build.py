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
from scripts.engine.probe import ProbeResult

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
        "item_id": "DEMO_R_D3DENS",
        "item_name": "demo-r-d3dens",
        "format": "SDMX",
        "distribution_url": "https://example.test/data/DEMO_R_D3DENS/ALL/",
        "organization": "ESTAT",
    },
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
    ds_dir = repo / "datasets" / "demo-published"
    ds_dir.mkdir(parents=True)
    (ds_dir / "dataset.yml").write_text(
        """
dataset:
  name: demo_published
raw:
  sources:
  - name: a
    type: sdmx
    args: {agency: ESTAT, flow: DEMO_R_D3DENS}
""",
        encoding="utf-8",
    )
    return repo


def _make_repo_with_missing_ref(tmp_path: Path) -> Path:
    """Repo demo con un dataset il cui upstream NON è nell'inventario."""
    repo = _make_repo(tmp_path)
    registry = dict(_REGISTRY)
    registry["datasets"] = list(_REGISTRY["datasets"]) + [
        {"slug": "demo_missing", "source_id": "demo_src", "stage": "published"}
    ]
    (repo / "registry" / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    ds_dir = repo / "datasets" / "demo-missing"
    ds_dir.mkdir(parents=True)
    (ds_dir / "dataset.yml").write_text(
        "dataset:\n"
        "  name: demo_missing\n"
        "raw:\n"
        "  sources:\n"
        "  - name: a\n"
        "    type: sdmx\n"
        "    args: {agency: ESTAT, flow: FLOW_ASSENTE}\n",
        encoding="utf-8",
    )
    return repo


def _patch_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralizza HTTP: probe/dispatch/validate restituiscono fixture."""

    def fake_probe(base_url: str, user_agent: str | None = None) -> ProbeResult:
        return ProbeResult(status="GREEN", http_code="200", note=None, final_url=base_url)

    def fake_dispatch(source_id, source_cfg, captured_at) -> CollectorResult:
        return CollectorResult(rows=[dict(r) for r in _INVENTORY_ROWS])

    def fake_merge(df, dry_run: bool = False):
        df = df.copy()
        df["dataset_group"] = df["item_name"].map(lambda n: f"demo_src/{n}")
        return df

    def fake_validate(df, max_groups=None, workers: int = 1, user_agent=None):
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
        assert catalog["inventory"]["total_items"] == 3
        assert catalog["source_check"]["total_scored"] == 2
        assert catalog["source_check"]["reachable"] == 2
        assert catalog["datasets_in_use"] == [
            {
                "slug": "demo_published",
                "status": "published",
                "upstream": [{"kind": "dataflow", "id": "DEMO_R_D3DENS", "agency": "ESTAT"}],
            },
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
        assert catalog["inventory"]["total_items"] == 3

    @pytest.mark.contract
    def test_radar_only_skips_inventory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)
        # Se il config e' radar-only, dispatch NON deve essere chiamato.
        monkeypatch.setattr(
            "scripts.catalog.build.dispatch",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("dispatch must not run")),
        )
        text = (repo / "pyproject.toml").read_text()
        (repo / "pyproject.toml").write_text(
            text.replace('verdict = "go"', 'verdict = "go"\nobservation_mode = "radar-only"')
        )

        catalog = build_catalog(repo, write=False)
        assert catalog["inventory"]["total_items"] == 0
        assert catalog["source_check"]["total_scored"] == 0
        assert catalog["health"]["radar_status"] == "GREEN"

    @pytest.mark.contract
    def test_pattern_probes_and_new_content_trigger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)
        # Aggiungi pattern_probes al config
        text = (repo / "pyproject.toml").read_text()
        (repo / "pyproject.toml").write_text(
            text
            + "\n[[tool.observatory.pattern_probes]]\n"
            + 'name = "sentinel-2026"\n'
            + 'url = "https://example.test/2026.zip"\n'
        )
        monkeypatch.setattr(
            "scripts.catalog.build.run_pattern_probes",
            lambda cfg: [
                {
                    "name": "sentinel-2026",
                    "url": "https://example.test/2026.zip",
                    "available": True,
                    "http_code": "200",
                }
            ],
        )

        catalog = build_catalog(repo, write=False)
        assert "pattern_probes" in catalog
        assert catalog["pattern_probes"][0]["available"] is True
        # Primo run + available → new_content trigger
        assert "new_content_available" in catalog["operational_verdict"]["triggers"]
        assert catalog["operational_verdict"]["label"] == "NEW_CONTENT"

    @pytest.mark.contract
    def test_no_pattern_probes_no_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)
        catalog = build_catalog(repo, write=False)
        assert "pattern_probes" not in catalog

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


# ── referenced-item drift: wiring nel catalog e nel verdict ──────────────────


class TestReferencedItemsIntegration:
    @pytest.mark.contract
    def test_end_to_end_records_referenced_items(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Il catalog espone il cross-check; nessun ref missing → verdict intatto."""
        repo = _make_repo(tmp_path)
        _patch_engine(monkeypatch)

        catalog = build_catalog(repo, write=False)

        assert catalog["referenced_items"] == {
            "checked": 1,
            "matched": 1,
            "missing": [],
            "unknown": [],
        }
        assert "referenced_item_missing" not in catalog["operational_verdict"]["triggers"]
        assert catalog["operational_verdict"]["label"] != "REFERENCED_MISSING"

    @pytest.mark.contract
    def test_missing_upstream_sets_trigger_and_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Ref assente dall'inventario → trigger + label + score + next_action."""
        repo = _make_repo_with_missing_ref(tmp_path)
        _patch_engine(monkeypatch)

        catalog = build_catalog(repo, write=False)

        drift = catalog["referenced_items"]
        assert drift["checked"] == 2
        assert drift["matched"] == 1
        assert drift["missing"] == [
            {"slug": "demo_missing", "kind": "dataflow", "id": "FLOW_ASSENTE"}
        ]

        verdict = catalog["operational_verdict"]
        assert "referenced_item_missing" in verdict["triggers"]
        assert verdict["label"] == "REFERENCED_MISSING"
        assert verdict["score"] == "referenced_missing"
        assert verdict["next_action"] == "review missing upstream items"

    @pytest.mark.contract
    def test_label_not_overwritten_when_not_stable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Il drift aggiunge il trigger ma non riscrive una label già impostata."""
        import scripts.catalog.build as build_mod
        from scripts.engine.report import build_report as real_build_report

        def report_with_partial(*args, **kwargs):
            catalog = real_build_report(*args, **kwargs)
            catalog["operational_verdict"] = {
                "label": "PARTIALLY_SCOPED",
                "score": "partial",
                "triggers": ["source_check_partial"],
                "next_action": "complete source-check",
            }
            return catalog

        repo = _make_repo_with_missing_ref(tmp_path)
        _patch_engine(monkeypatch)
        monkeypatch.setattr(build_mod, "build_report", report_with_partial)

        catalog = build_catalog(repo, write=False)

        verdict = catalog["operational_verdict"]
        assert verdict["label"] == "PARTIALLY_SCOPED"
        assert "source_check_partial" in verdict["triggers"]
        assert "referenced_item_missing" in verdict["triggers"]

    @pytest.mark.contract
    def test_drift_and_new_content_coexist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Drift + nuovo contenuto: entrambi i trigger; la label è del drift.

        Il blocco drift gira prima di quello dei pattern probes e ognuno
        promuove la label solo da STABLE: con entrambi i segnali vince
        REFERENCED_MISSING e `new_content_available` resta tra i trigger.
        """
        repo = _make_repo_with_missing_ref(tmp_path)
        _patch_engine(monkeypatch)
        text = (repo / "pyproject.toml").read_text()
        (repo / "pyproject.toml").write_text(
            text
            + "\n[[tool.observatory.pattern_probes]]\n"
            + 'name = "sentinel-2026"\n'
            + 'url = "https://example.test/2026.zip"\n'
        )
        monkeypatch.setattr(
            "scripts.catalog.build.run_pattern_probes",
            lambda cfg: [
                {
                    "name": "sentinel-2026",
                    "url": "https://example.test/2026.zip",
                    "available": True,
                    "http_code": "200",
                }
            ],
        )

        catalog = build_catalog(repo, write=False)

        verdict = catalog["operational_verdict"]
        assert verdict["label"] == "REFERENCED_MISSING"
        assert "referenced_item_missing" in verdict["triggers"]
        assert "new_content_available" in verdict["triggers"]
