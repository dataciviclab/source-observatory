"""Catalog engine per-repo: config, layout, build, CLI (so-catalog).

Pubblico:
    load_observatory_config(repo_root)  → dict fonte da [tool.observatory]
    resolve_layout(repo_root)           → RepoLayout
    build_catalog(repo_root, ...)       → dict catalog (+ scrittura opzionale)
    validate_catalog(catalog)           → jsonschema sul catalog.schema.json
"""

from scripts.catalog.build import (
    build_catalog,
    load_catalog_schema,
    validate_catalog,
)
from scripts.catalog.config import (
    ObservatoryConfigError,
    load_observatory_config,
    validate_observatory_config,
)
from scripts.catalog.layout import RepoLayout, resolve_layout

__all__ = [
    "ObservatoryConfigError",
    "RepoLayout",
    "build_catalog",
    "load_catalog_schema",
    "load_observatory_config",
    "resolve_layout",
    "validate_catalog",
    "validate_observatory_config",
]
