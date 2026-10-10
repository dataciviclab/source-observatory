"""Per-repo filesystem layout for the decentralized catalog engine.

Il repo SO centrale usa ``so_mcp._paths`` (layout ``data/`` del proprio repo).
Questo modulo define il layout di un **repo dati** che genera il proprio
``registry/catalog.json`` con l'engine condiviso::

    <repo_root>/
      pyproject.toml              # [tool.observatory] — config fonte
      registry/registry.json      # catalogo dataset pubblicati (toolkit)
      registry/catalog.json       # catalogo salute/inventario fonte (so-catalog)
      out/so/                     # stato operativo locale (gitignored)
        inventory.parquet
        validated.parquet
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

OUT_DIR_NAME = "out/so"
REGISTRY_DIR_NAME = "registry"
CATALOG_FILENAME = "catalog.json"
TOOLKIT_REGISTRY_FILENAME = "registry.json"


@dataclass(frozen=True)
class RepoLayout:
    """Paths assoluti di un repo dati per il catalog engine."""

    repo_root: Path

    @property
    def pyproject(self) -> Path:
        return self.repo_root / "pyproject.toml"

    @property
    def registry_dir(self) -> Path:
        return self.repo_root / REGISTRY_DIR_NAME

    @property
    def catalog_path(self) -> Path:
        """Artifact committato: registry/catalog.json."""
        return self.registry_dir / CATALOG_FILENAME

    @property
    def toolkit_registry_path(self) -> Path:
        """registry/registry.json — fonte datasets_in_use locale."""
        return self.registry_dir / TOOLKIT_REGISTRY_FILENAME

    @property
    def out_dir(self) -> Path:
        """Stato operativo locale (gitignored): out/so/."""
        return self.repo_root / OUT_DIR_NAME

    @property
    def inventory_parquet(self) -> Path:
        return self.out_dir / "inventory.parquet"

    @property
    def validated_parquet(self) -> Path:
        return self.out_dir / "validated.parquet"


def resolve_layout(repo_root: Path | str | None = None) -> RepoLayout:
    """Risolvi il layout. Default: CWD come repo_root."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return RepoLayout(repo_root=root.resolve())
