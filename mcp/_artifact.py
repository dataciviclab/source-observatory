"""
Shared artifact infrastructure for SO MCP modules.

Path constants, artifact resolution (local/GCS), env loading, format maps,
and helper utilities used by all other ``mcp/_*.py`` modules.

This module intentionally has no ``__init__.py`` in ``mcp/`` — sibling modules
import via ``import _artifact``, relying on ``mcp/`` being in ``sys.path``
(added automatically when running ``python mcp/so_server.py``, or via conftest
for tests).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import requests
from lab_connectors.gcs.paths import CLEAN_BUCKET

# ── Repo root ─────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ── Script paths ──────────────────────────────────────────────────────────────

_COLLECTORS_BASE = _REPO_ROOT / "scripts" / "collectors" / "base.py"

# ── Artifact paths ────────────────────────────────────────────────────────────

_CHECK_PARQUET = (
    _REPO_ROOT / "data" / "catalog_inventory" / "generated" / "source_check_results.parquet"
)
_INVENTORY_PARQUET = (
    _REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_latest.parquet"
)
_INVENTORY_REPORT = (
    _REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_report.json"
)
_SIGNALS_JSON = _REPO_ROOT / "data" / "catalog" / "catalog_signals.json"
_RADAR_JSON = _REPO_ROOT / "data" / "radar" / "radar_summary.json"
_RADAR_HISTORY_JSON = _REPO_ROOT / "data" / "radar" / "radar_history.json"
_STATUS_MD = _REPO_ROOT / "data" / "radar" / "STATUS.md"
_REGISTRY_YAML = _REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
_DEFAULT_CACHE_MAX_AGE_HOURS = 24

# ── GCS prefix defaults ──────────────────────────────────────────────────────

_DEFAULT_GCS_PREFIXES: dict[str, str] = {
    "CATALOG_INVENTORY_GCS_PREFIX": f"gs://{CLEAN_BUCKET}/catalog_inventory",
}

_SOURCE_CHECK_ARTIFACT = "source_check_results.parquet"
_CATALOG_INVENTORY_ARTIFACT = "catalog_inventory_latest.parquet"
_CATALOG_INVENTORY_REPORT_ARTIFACT = "catalog_inventory_report.json"

# ── Format maps ───────────────────────────────────────────────────────────────

_FORMAT_BY_CONTENT_TYPE: dict[str, str] = {
    "text/csv": "CSV",
    "application/json": "JSON",
    "application/ld+json": "JSON",
    "application/vnd.ms-excel": "XLS",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/xml": "XML",
    "text/xml": "XML",
    "application/pdf": "PDF",
    "application/parquet": "PARQUET",
    "text/html": "HTML",
    "text/plain": "TXT",
    "application/octet-stream": "BIN",
    "text/tab-separated-values": "TSV",
    "application/gzip": "GZ",
    "application/zip": "ZIP",
    "application/x-tar": "TAR",
    "application/vnd.oasis.opendocument.spreadsheet": "ODS",
}
_FORMAT_BY_SUFFIX: dict[str, str] = {
    ".csv": "CSV",
    ".json": "JSON",
    ".geojson": "JSON",
    ".xlsx": "XLSX",
    ".xls": "XLS",
    ".xml": "XML",
    ".pdf": "PDF",
    ".parquet": "PARQUET",
    ".zip": "ZIP",
}

# ── Env loading (lazy, once) ─────────────────────────────────────────────────

_ENV_LOADED = False


def _load_env_file_once() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = Path(os.environ.get("SO_ENV_FILE") or _REPO_ROOT.parent / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str) -> str | None:
    _load_env_file_once()
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _artifact_backend() -> str:
    backend = (_env("SO_ARTIFACT_BACKEND") or "auto").lower()
    if backend not in {"auto", "gcs", "local"}:
        return "auto"
    return backend


def _cache_max_age_hours() -> int:
    raw = _env("SO_CACHE_MAX_AGE_HOURS")
    if raw is None:
        return _DEFAULT_CACHE_MAX_AGE_HOURS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_CACHE_MAX_AGE_HOURS


def _gcs_prefix(env_name: str) -> str | None:
    return _env(f"SO_{env_name}") or _env(env_name) or _DEFAULT_GCS_PREFIXES.get(env_name)


# ── Observatory GET / collectors base (lazy load) ────────────────────────────

_collectors_base = None
observatory_get = None


def _get_observatory_get() -> Any:
    """Lazy-load observatory_get from collectors.base (used for POST cases like SPARQL)."""
    global _collectors_base, observatory_get
    if _collectors_base is None:
        spec = importlib.util.spec_from_file_location("_so_collectors_base", _COLLECTORS_BASE)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load collectors base from {_COLLECTORS_BASE}")
        _collectors_base = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = _collectors_base
        spec.loader.exec_module(_collectors_base)
        observatory_get = _collectors_base.observatory_get
    return observatory_get


# ── Artifact types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _ParquetArtifact:
    name: str
    local_path: Path
    gcs_env: str
    gcs_key: str

    def gcs_uri(self) -> str | None:
        prefix = _gcs_prefix(self.gcs_env)
        if prefix is None:
            return None
        return f"{prefix.rstrip('/')}/{self.gcs_key}"


@dataclass(frozen=True)
class _JsonArtifact:
    name: str
    local_path: Path
    gcs_env: str
    gcs_key: str

    def gcs_uri(self) -> str | None:
        prefix = _gcs_prefix(self.gcs_env)
        if prefix is None:
            return None
        return f"{prefix.rstrip('/')}/{self.gcs_key}"


# ── Artifact factory functions ───────────────────────────────────────────────


def _source_check_parquet() -> _ParquetArtifact:
    return _ParquetArtifact(
        name=_SOURCE_CHECK_ARTIFACT,
        local_path=_CHECK_PARQUET,
        gcs_env="CATALOG_INVENTORY_GCS_PREFIX",
        gcs_key="source-check/source_check_results.parquet",
    )


def _catalog_inventory_parquet() -> _ParquetArtifact:
    return _ParquetArtifact(
        name=_CATALOG_INVENTORY_ARTIFACT,
        local_path=_INVENTORY_PARQUET,
        gcs_env="CATALOG_INVENTORY_GCS_PREFIX",
        gcs_key="catalog_inventory_latest.parquet",
    )


def _catalog_inventory_report_artifact() -> _JsonArtifact:
    return _JsonArtifact(
        name=_CATALOG_INVENTORY_REPORT_ARTIFACT,
        local_path=_INVENTORY_REPORT,
        gcs_env="CATALOG_INVENTORY_GCS_PREFIX",
        gcs_key="catalog_inventory_report.json",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _artifact_not_found(path: Path, artifact_name: str) -> dict[str, Any]:
    return {
        "error": "artifact_not_found",
        "artifact": artifact_name,
        "message": f"{artifact_name} not found at {path}",
        "hint": "Fetch the latest GitHub Actions artifact or run the SO workflow locally.",
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def _table_columns(con: duckdb.DuckDBPyConnection, parquet_path: str) -> list[str]:
    return [row[0] for row in con.execute(f'DESCRIBE FROM "{parquet_path}"').fetchall()]


def _select_expr(column: str, columns: set[str]) -> str:
    if column in columns:
        return column
    return f"NULL AS {column}"


# ── Cache info ────────────────────────────────────────────────────────────────


def _artifact_cache_info(
    path: Path,
    *,
    source: str = "local_cache",
    uri: str | None = None,
    fallback_warning: str | None = None,
) -> dict[str, Any]:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified_at).total_seconds() / 3600
    max_age_hours = _cache_max_age_hours()
    stale = source == "local_cache" and age_hours > max_age_hours
    info: dict[str, Any] = {
        "source": source,
        "path": _display_path(path),
        "uri": uri,
        "modified_at": modified_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "max_age_hours": max_age_hours,
        "stale": stale,
        "source_of_truth": "GitHub Actions artifact or configured GCS prefix",
    }
    if source == "gcs":
        info["source_of_truth"] = "configured GCS prefix"
    if stale:
        info["warning"] = (
            "Local artifact cache is older than the operational freshness threshold; "
            "refresh it from CI/GCS or regenerate it before using results as current."
        )
    if fallback_warning:
        info["fallback_warning"] = fallback_warning
    return info


# ── GCS download helpers ──────────────────────────────────────────────────────


def _public_url(uri: str) -> str:
    if uri.startswith("gs://"):
        bucket_and_path = uri.removeprefix("gs://")
        bucket, _, object_name = bucket_and_path.partition("/")
        return f"https://storage.googleapis.com/{bucket}/{object_name}"
    return uri


def _download_public_to_temp(uri: str, tmp_path: Path) -> None:
    response = requests.get(_public_url(uri), timeout=120, stream=True)
    response.raise_for_status()
    with tmp_path.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                fh.write(chunk)


def _copy_gcs_to_temp(uri: str, artifact_name: str) -> Path:
    suffix = Path(artifact_name).suffix or ".tmp"
    tmp = tempfile.NamedTemporaryFile(prefix=f"so_mcp_{artifact_name}_", suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        try:
            _download_public_to_temp(uri, tmp_path)
        except requests.RequestException:
            subprocess.run(
                ["gcloud", "storage", "cp", uri, str(tmp_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


# ── Artifact resolution (context manager) ─────────────────────────────────────


@contextmanager
def _resolved_artifact(artifact: _ParquetArtifact | _JsonArtifact):
    backend = _artifact_backend()
    uri = artifact.gcs_uri()
    fallback_warning = None

    if backend in {"auto", "gcs"} and uri:
        tmp_path: Path | None = None
        try:
            tmp_path = _copy_gcs_to_temp(uri, artifact.name)
        except Exception as exc:
            if backend == "gcs":
                raise RuntimeError(f"Cannot read {artifact.name} from GCS {uri}: {exc}") from exc
            fallback_warning = f"Cannot read GCS artifact {uri}; using local cache if available."
        else:
            try:
                yield tmp_path, _artifact_cache_info(tmp_path, source="gcs", uri=uri)
                return
            finally:
                tmp_path.unlink(missing_ok=True)

    if artifact.local_path.exists():
        yield artifact.local_path, _artifact_cache_info(
            artifact.local_path,
            source="local_cache",
            uri=uri,
            fallback_warning=fallback_warning,
        )
        return

    raise FileNotFoundError(
        f"{artifact.name} not found locally at {artifact.local_path}"
        + (f" and no readable GCS artifact at {uri}" if uri else "")
    )


def _resolved_parquet(artifact: _ParquetArtifact) -> AbstractContextManager[tuple[Path, dict[str, Any]]]:
    return _resolved_artifact(artifact)


def _resolved_json(artifact: _JsonArtifact) -> AbstractContextManager[tuple[Path, dict[str, Any]]]:
    return _resolved_artifact(artifact)


def _parquet_not_found(artifact: _ParquetArtifact) -> dict[str, Any]:
    return _artifact_not_found(artifact.local_path, artifact.name)


def _json_not_found(artifact: _JsonArtifact) -> dict[str, Any]:
    return _artifact_not_found(artifact.local_path, artifact.name)


# ── Shared report helpers (used by _inventory, _sdmx, _recommend) ────────────


def _load_inventory_report() -> tuple[dict[str, Any], dict[str, Any]] | None:
    artifact = _catalog_inventory_report_artifact()
    try:
        with _resolved_json(artifact) as (path, cache):
            with path.open(encoding="utf-8") as fh:
                return json.load(fh), cache
    except FileNotFoundError:
        return None


def _inventory_source_status(source_id: str) -> dict[str, Any] | None:
    loaded = _load_inventory_report()
    if loaded is None:
        return None
    report, _cache = loaded
    sources = report.get("sources")
    if not isinstance(sources, dict):
        return None
    source_info = sources.get(source_id)
    return source_info if isinstance(source_info, dict) else None
