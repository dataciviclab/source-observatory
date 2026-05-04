"""
SO MCP core: read-only artifact queries and lightweight probes.

Artifact paths are resolved relative to the source-observatory repository.
"""
from __future__ import annotations

import json
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb
import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COLLECTORS_BASE = _REPO_ROOT / "scripts" / "collectors" / "base.py"
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
_DEFAULT_GCS_PREFIXES = {
    "CATALOG_INVENTORY_GCS_PREFIX": "gs://dataciviclab-clean/catalog_inventory",
}
_SOURCE_CHECK_ARTIFACT = "source_check_results.parquet"
_CATALOG_INVENTORY_ARTIFACT = "catalog_inventory_latest.parquet"
_CATALOG_INVENTORY_REPORT_ARTIFACT = "catalog_inventory_report.json"

_FORMAT_BY_CONTENT_TYPE = {
    "text/csv": "CSV",
    "application/json": "JSON",
    "application/ld+json": "JSON",
    "application/vnd.ms-excel": "XLS",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/xml": "XML",
    "text/xml": "XML",
    "application/pdf": "PDF",
    "application/parquet": "PARQUET",
}
_FORMAT_BY_SUFFIX = {
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

_ENV_LOADED = False


_collectors_base = None
observatory_get = None
observatory_head = None


def _get_observatory_get() -> Any:
    global _collectors_base, observatory_get, observatory_head
    if _collectors_base is None:
        spec = importlib.util.spec_from_file_location("_so_collectors_base", _COLLECTORS_BASE)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load collectors base from {_COLLECTORS_BASE}")
        _collectors_base = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = _collectors_base
        spec.loader.exec_module(_collectors_base)
        observatory_get = _collectors_base.observatory_get
        observatory_head = _collectors_base.observatory_head
    return observatory_get


def _get_observatory_head() -> Any:
    _get_observatory_get()  # ensure initialized
    return observatory_head


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


def _resolved_parquet(artifact: _ParquetArtifact):
    return _resolved_artifact(artifact)


def _resolved_json(artifact: _JsonArtifact):
    return _resolved_artifact(artifact)


def _parquet_not_found(artifact: _ParquetArtifact) -> dict[str, Any]:
    return _artifact_not_found(artifact.local_path, artifact.name)


def _json_not_found(artifact: _JsonArtifact) -> dict[str, Any]:
    return _artifact_not_found(artifact.local_path, artifact.name)


def _load_inventory_report() -> tuple[dict[str, Any], dict[str, Any]] | None:
    artifact = _catalog_inventory_report_artifact()
    try:
        with _resolved_json(artifact) as (path, cache):
            with path.open(encoding="utf-8") as fh:
                return json.load(fh), cache
    except FileNotFoundError:
        return None


def query_signals(source_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Query catalog_signals.json with optional source filter."""
    if not _SIGNALS_JSON.exists():
        return _artifact_not_found(_SIGNALS_JSON, "catalog_signals.json")

    with _SIGNALS_JSON.open(encoding="utf-8") as fh:
        signals_doc = json.load(fh)

    signals = signals_doc.get("signals", [])
    if source_id:
        signals = [signal for signal in signals if signal.get("source") == source_id]

    safe_limit = None if limit is None else max(1, min(int(limit), 200))
    selected = signals[-safe_limit:] if safe_limit is not None else signals
    return {
        "artifact": _display_path(_SIGNALS_JSON),
        "captured_at": signals_doc.get("captured_at", ""),
        "filters": {"source_id": source_id, "limit": safe_limit},
        "signals": selected,
        "returned": len(selected),
    }


def radar_summary(source_id: str | None = None) -> dict[str, Any]:
    """Return radar health summary, optionally for one source."""
    if not _RADAR_JSON.exists():
        return _artifact_not_found(_RADAR_JSON, "radar_summary.json")

    with _RADAR_JSON.open(encoding="utf-8") as fh:
        radar_doc = json.load(fh)

    sources = radar_doc.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    if source_id:
        sources = [source for source in sources if source.get("id") == source_id]

    return {
        "artifact": _display_path(_RADAR_JSON),
        "generated_at": radar_doc.get("generated_at"),
        "probe_date": radar_doc.get("probe_date"),
        "sources_total": radar_doc.get("sources_total"),
        "status_counts": radar_doc.get("status_counts", {}),
        "persistent_red": radar_doc.get("persistent_red"),
        "filters": {"source_id": source_id},
        "sources": sources,
        "returned": len(sources),
    }


def radar_history(source_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    """Return radar_history.json: probe history per fonte, per calcolare streak/persistent."""
    if not _RADAR_HISTORY_JSON.exists():
        return _artifact_not_found(_RADAR_HISTORY_JSON, "radar_history.json")

    with _RADAR_HISTORY_JSON.open(encoding="utf-8") as fh:
        history_doc = json.load(fh)

    probes = history_doc.get("probes", [])
    if not isinstance(probes, list):
        probes = []

    safe_limit = max(1, min(int(limit or 5), 20))
    recent_probes = list(reversed(probes))[-safe_limit:] if probes else []

    sources_map: dict[str, list[dict[str, Any]]] = {}
    for probe in recent_probes:
        for src in probe.get("sources", []):
            sid = src.get("id", "unknown")
            if source_id and sid != source_id:
                continue
            if sid not in sources_map:
                sources_map[sid] = []
            sources_map[sid].append({
                "probe_date": probe.get("probe_date"),
                "status": src.get("status"),
                "http_code": src.get("http_code"),
                "note": src.get("note"),
            })

    results = []
    for sid, entries in sorted(sources_map.items()):
        entries.sort(key=lambda e: e.get("probe_date") or "", reverse=True)
        red_count = sum(1 for e in entries if e.get("status") == "RED")
        results.append({
            "source_id": sid,
            "probes": entries,
            "recent_red_count": red_count,
            "current_status": entries[0].get("status") if entries else None,
        })

    return {
        "artifact": _display_path(_RADAR_HISTORY_JSON),
        "captured_at": history_doc.get("captured_at"),
        "filters": {"source_id": source_id, "limit": safe_limit},
        "sources": results,
        "returned": len(results),
        "probes_in_window": len(recent_probes),
    }


def radar_status_md() -> dict[str, Any]:
    """Return STATUS.md content as plain text for human-readable radar state."""
    if not _STATUS_MD.exists():
        return _artifact_not_found(_STATUS_MD, "STATUS.md")

    content = _STATUS_MD.read_text(encoding="utf-8")
    stat = _STATUS_MD.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified_at).total_seconds() / 3600

    return {
        "artifact": _display_path(_STATUS_MD),
        "modified_at": modified_at.isoformat(),
        "age_hours": round(age_hours, 2),
        "content": content,
    }


def radar_delta() -> dict[str, Any]:
    """Compare latest and previous probe to return only changed sources."""
    if not _RADAR_HISTORY_JSON.exists():
        return _artifact_not_found(_RADAR_HISTORY_JSON, "radar_history.json")

    with _RADAR_HISTORY_JSON.open(encoding="utf-8") as fh:
        history_doc = json.load(fh)

    probes = history_doc.get("probes", [])
    if not isinstance(probes, list) or len(probes) < 2:
        return {
            "artifact": _display_path(_RADAR_HISTORY_JSON),
            "captured_at": history_doc.get("captured_at"),
            "message": "Not enough probes to compute delta (need at least 2)",
            "changes": [],
            "new_red": [],
            "recoveries": [],
            "persistent_red": [],
        }

    latest = probes[-1]
    previous = probes[-2]
    latest_sources = {s["id"]: s for s in latest.get("sources", [])}
    prev_sources = {s["id"]: s for s in previous.get("sources", [])}

    changes = []
    new_red = []
    recoveries = []
    persistent_red = []

    all_ids = set(latest_sources.keys()) | set(prev_sources.keys())
    for sid in sorted(all_ids):
        curr = latest_sources.get(sid)
        prev = prev_sources.get(sid)

        curr_status = curr.get("status") if curr else None
        prev_status = prev.get("status") if prev else None

        if curr_status != prev_status:
            changes.append({
                "source_id": sid,
                "previous": prev_status,
                "current": curr_status,
                "http_code": curr.get("http_code") if curr else None,
                "note": curr.get("note") if curr else None,
            })
            if curr_status == "RED":
                new_red.append(sid)
            elif prev_status == "RED" and curr_status != "RED":
                recoveries.append(sid)

        if curr_status == "RED":
            streak = 0
            for probe in reversed(probes):
                src = next((s for s in probe.get("sources", []) if s.get("id") == sid), None)
                if src and src.get("status") == "RED":
                    streak += 1
                else:
                    break
            if streak >= 2:
                persistent_red.append(sid)

    return {
        "artifact": _display_path(_RADAR_HISTORY_JSON),
        "captured_at": history_doc.get("captured_at"),
        "probe_date_latest": latest.get("probe_date"),
        "probe_date_previous": previous.get("probe_date"),
        "changes": changes,
        "new_red": new_red,
        "recoveries": recoveries,
        "persistent_red": persistent_red,
        "changed_count": len(changes),
    }


def find_by_url(url: str) -> dict[str, Any]:
    """Find a URL across source_check_results and catalog_inventory."""
    clean_url = (url or "").strip()
    if not clean_url:
        return {"error": "empty_url", "message": "Provide a non-empty URL."}

    results: dict[str, Any] = {
        "query_url": clean_url,
        "source_check_results": [],
        "catalog_inventory": [],
    }

    source_check_artifact = _source_check_parquet()
    try:
        with _resolved_parquet(source_check_artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            con = duckdb.connect()
            try:
                cols = _table_columns(con, parquet_path)
                url_cols = [c for c in cols if c in ("url", "url_checked", "distribution_url", "landing_page", "source_url")]
                if not url_cols:
                    results["source_check_error"] = "No URL columns found in parquet"
                else:
                    where = " OR ".join(
                        f"lower(coalesce(cast({c} as varchar), '')) LIKE ?"
                        for c in url_cols
                    )
                    like = f"%{clean_url}%"
                    sql = f'SELECT * FROM "{parquet_path}" WHERE {where} LIMIT 10'
                    rows = con.execute(sql, [like] * len(url_cols)).fetchall()
                    results["source_check_results"] = [dict(zip(cols, row)) for row in rows]
                    results["source_check_cache"] = cache
            finally:
                con.close()
    except FileNotFoundError:
        results["source_check_error"] = f"{source_check_artifact.name} not found"

    catalog_artifact = _catalog_inventory_parquet()
    try:
        with _resolved_parquet(catalog_artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            con = duckdb.connect()
            try:
                cols = _table_columns(con, parquet_path)
                url_cols = [c for c in cols if c in ("url", "url_checked", "distribution_url", "landing_page", "source_url")]
                if not url_cols:
                    results["catalog_inventory_error"] = "No URL columns found in parquet"
                else:
                    where = " OR ".join(
                        f"lower(coalesce(cast({c} as varchar), '')) LIKE ?"
                        for c in url_cols
                    )
                    like = f"%{clean_url}%"
                    sql = f'SELECT * FROM "{parquet_path}" WHERE {where} LIMIT 10'
                    rows = con.execute(sql, [like] * len(url_cols)).fetchall()
                    results["catalog_inventory"] = [dict(zip(cols, row)) for row in rows]
                    results["catalog_inventory_cache"] = cache
            finally:
                con.close()
    except FileNotFoundError:
        results["catalog_inventory_error"] = f"{catalog_artifact.name} not found"

    return results


def registry_query(
    protocol: str | None = None,
    source_kind: str | None = None,
    observation_mode: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Query sources_registry.yaml with optional filters."""
    if not _REGISTRY_YAML.exists():
        return _artifact_not_found(_REGISTRY_YAML, "sources_registry.yaml")

    import yaml
    with _REGISTRY_YAML.open(encoding="utf-8") as fh:
        registry = yaml.safe_load(fh)

    if not isinstance(registry, dict):
        return {"error": "invalid_registry", "message": "Registry is not a dict."}

    results = []
    for sid, info in sorted(registry.items()):
        if source_id and sid != source_id:
            continue
        if source_kind and info.get("source_kind") != source_kind:
            continue
        if protocol and info.get("protocol") != protocol:
            continue
        if observation_mode and info.get("observation_mode") != observation_mode:
            continue
        results.append({
            "source_id": sid,
            "source_kind": info.get("source_kind"),
            "protocol": info.get("protocol"),
            "observation_mode": info.get("observation_mode"),
            "base_url": info.get("base_url"),
            "verdict": info.get("verdict"),
            "last_probed": info.get("last_probed"),
            "datasets_in_use": info.get("datasets_in_use", []),
            "note": info.get("note"),
        })

    return {
        "artifact": _display_path(_REGISTRY_YAML),
        "filters": {
            "source_id": source_id,
            "protocol": protocol,
            "source_kind": source_kind,
            "observation_mode": observation_mode,
        },
        "results": results,
        "returned": len(results),
    }


def query_inventory(
    source_id: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
    has_results: bool | None = None,
) -> dict[str, Any]:
    """Query source_check_results.parquet with optional source and score filters."""
    safe_limit = max(1, min(int(limit or 50), 200))
    artifact = _source_check_parquet()
    try:
        with _resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            con = duckdb.connect()
            try:
                cols = _table_columns(con, parquet_path)
                query = f'SELECT * FROM "{parquet_path}"'
                filters: list[str] = []
                params: list[Any] = []

                if source_id:
                    filters.append("source_id = ?")
                    params.append(source_id)
                if min_score is not None:
                    filters.append("intake_score >= ?")
                    params.append(min_score)
                if has_results is not None:
                    if has_results:
                        filters.append("intake_score IS NOT NULL AND intake_score > 0")
                    else:
                        filters.append("(intake_score IS NULL OR intake_score = 0)")
                if filters:
                    query += " WHERE " + " AND ".join(filters)
                query += f" ORDER BY intake_score DESC NULLS LAST LIMIT {safe_limit}"

                rows = con.execute(query, params).fetchall()
            finally:
                con.close()
    except FileNotFoundError:
        return _parquet_not_found(artifact)

    return {
        "artifact": _display_path(_CHECK_PARQUET),
        "cache": cache,
        "gcs_uri": artifact.gcs_uri(),
        "filters": {"source_id": source_id, "min_score": min_score, "limit": safe_limit, "has_results": has_results},
        "results": [dict(zip(cols, row)) for row in rows],
        "returned": len(rows),
        "has_more": len(rows) == safe_limit,
    }


def inventory_status(source_id: str | None = None) -> dict[str, Any]:
    """Return catalog inventory build status from catalog_inventory_report.json."""
    loaded = _load_inventory_report()
    if loaded is None:
        return _json_not_found(_catalog_inventory_report_artifact())
    report, cache = loaded

    sources = report.get("sources", {})
    if not isinstance(sources, dict):
        sources = {}

    status_counts: dict[str, int] = {}
    rows_total = 0
    for info in sources.values():
        if not isinstance(info, dict):
            continue
        status = str(info.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        rows = info.get("rows")
        if isinstance(rows, int):
            rows_total += rows

    if source_id:
        source_info = sources.get(source_id)
        return {
            "artifact": _display_path(_INVENTORY_REPORT),
            "cache": cache,
            "captured_at": report.get("captured_at"),
            "filters": {"source_id": source_id},
            "source": source_info if isinstance(source_info, dict) else None,
            "returned": 1 if isinstance(source_info, dict) else 0,
        }

    compact_sources = []
    for key, info in sorted(sources.items()):
        if not isinstance(info, dict):
            continue
        compact_sources.append(
            {
                "source_id": key,
                "status": info.get("status"),
                "protocol": info.get("protocol"),
                "rows": info.get("rows"),
                "method": info.get("method"),
                "error": info.get("error"),
            }
        )

    return {
        "artifact": _display_path(_INVENTORY_REPORT),
        "cache": cache,
        "captured_at": report.get("captured_at"),
        "registry_path": report.get("registry_path"),
        "status_counts": status_counts,
        "rows_total": rows_total,
        "sources": compact_sources,
        "returned": len(compact_sources),
    }


def catalog_inventory_search(
    query: str,
    source_id: str | None = None,
    protocol: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Search catalog_inventory_latest.parquet across key text fields."""
    clean_query = (query or "").strip().lower()
    if not clean_query:
        return {"error": "empty_query", "message": "Provide a non-empty query."}

    safe_limit = max(1, min(int(limit or 25), 200))
    artifact = _catalog_inventory_parquet()
    try:
        with _resolved_parquet(artifact) as (resolved_path, cache):
            parquet_path = str(resolved_path)
            con = duckdb.connect()
            try:
                columns = set(_table_columns(con, parquet_path))
                search_columns = [
                    column
                    for column in (
                        "item_id",
                        "item_name",
                        "title",
                        "tags",
                        "notes_excerpt",
                        "topic",
                        "theme",
                    )
                    if column in columns
                ]
                if not search_columns:
                    return {"error": "schema_mismatch", "message": "No searchable text columns found."}
                where = [
                    "("
                    + " OR ".join(
                        f"lower(coalesce(cast({column} as varchar), '')) LIKE ?"
                        for column in search_columns
                    )
                    + ")"
                ]
                like = f"%{clean_query}%"
                params: list[Any] = [like] * len(search_columns)
                if source_id:
                    where.append("source_id = ?")
                    params.append(source_id)
                if protocol:
                    where.append("protocol = ?")
                    params.append(protocol)

                select_columns = [
                    "source_id",
                    "protocol",
                    "item_id",
                    "item_name",
                    "title",
                    "organization",
                    "tags",
                    "landing_page",
                    "distribution_url",
                    "format",
                    "source_status",
                    "inventory_method",
                    "item_kind",
                    "api_base_url",
                    "captured_at",
                    "civic_priority",
                ]
                select_sql = ", ".join(_select_expr(column, columns) for column in select_columns)
                sql = f"""
                    SELECT {select_sql}
                    FROM "{parquet_path}"
                    WHERE {" AND ".join(where)}
                    ORDER BY source_id NULLS LAST, title NULLS LAST, item_id
                    LIMIT {safe_limit}
                """
                rows = con.execute(sql, params).fetchall()
                cols = [desc[0] for desc in con.description]
            finally:
                con.close()
    except FileNotFoundError:
        return _parquet_not_found(artifact)

    result: dict[str, Any] = {
        "artifact": _display_path(_INVENTORY_PARQUET),
        "cache": cache,
        "filters": {
            "query": clean_query,
            "source_id": source_id,
            "protocol": protocol,
            "limit": safe_limit,
        },
        "results": [dict(zip(cols, row)) for row in rows],
        "returned": len(rows),
        "has_more": len(rows) == safe_limit,
    }
    if not rows and source_id:
        result["source_status"] = _inventory_source_status(source_id)
    return result


def _guess_format(url: str, content_type: str | None) -> str | None:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type in _FORMAT_BY_CONTENT_TYPE:
        return _FORMAT_BY_CONTENT_TYPE[media_type]

    suffix = Path(urlparse(url).path).suffix.lower()
    return _FORMAT_BY_SUFFIX.get(suffix)


def probe_url(url: str, timeout: int = 15) -> dict[str, Any]:
    """Probe a single URL with HEAD and a small GET fallback."""
    clean_url = (url or "").strip()
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "url": clean_url,
            "http_status": None,
            "content_type": None,
            "format": None,
            "size": None,
            "is_reachable": False,
            "error": "invalid_url",
        }

    safe_timeout = max(1, min(int(timeout or 15), 60))
    try:
        response = _get_observatory_head()(clean_url, timeout=safe_timeout)
    except requests.RequestException as exc:
        try:
            response = _get_observatory_get()(
                clean_url,
                timeout=safe_timeout,
                headers={"Range": "bytes=0-0"},
                stream=True,
            )
        except requests.RequestException as fallback_exc:
            return {
                "url": clean_url,
                "http_status": None,
                "content_type": None,
                "format": _guess_format(clean_url, None),
                "size": None,
                "is_reachable": False,
                "error": type(fallback_exc).__name__,
                "message": str(fallback_exc)[:200] or str(exc)[:200],
            }

    content_type = response.headers.get("content-type")
    content_length = response.headers.get("content-length")
    try:
        size = int(content_length) if content_length is not None else None
    except ValueError:
        size = None

    return {
        "url": clean_url,
        "http_status": response.status_code,
        "content_type": content_type,
        "format": _guess_format(clean_url, content_type),
        "size": size,
        "is_reachable": response.status_code < 400,
    }


def _score_dataflow(text: str, keywords: list[str]) -> int:
    low = text.lower()
    score = 0
    for keyword in keywords:
        pattern = re.escape(keyword.lower())
        if re.search(rf"\b{pattern}\b", low):
            score += 3
        elif keyword.lower() in low:
            score += 1
    return score


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


def _read_sdmx_inventory_rows(parquet_path: Path) -> list[dict[str, Any]]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT source_id, item_id, item_name, title, tags, api_base_url, source_url
            FROM "{parquet_path}"
            WHERE source_id = 'istat_sdmx'
            """
        ).fetchall()
    finally:
        con.close()
    cols = [
        "source_id",
        "item_id",
        "item_name",
        "title",
        "tags",
        "api_base_url",
        "source_url",
    ]
    return [dict(zip(cols, row)) for row in rows]


def discover_sdmx(keywords: list[str] | str, limit: int = 30) -> dict[str, Any]:
    """Discover ISTAT SDMX dataflows from local SO artifacts."""
    if isinstance(keywords, str):
        clean_keywords = [part.strip().lower() for part in keywords.split(",") if part.strip()]
    else:
        clean_keywords = [str(part).strip().lower() for part in keywords if str(part).strip()]
    if not clean_keywords:
        return {"error": "empty_keywords", "message": "Provide at least one keyword."}

    safe_limit = max(1, min(int(limit or 30), 100))
    try:
        artifact = _catalog_inventory_parquet()
        with _resolved_parquet(artifact) as (resolved_path, cache):
            rows = _read_sdmx_inventory_rows(resolved_path)
    except FileNotFoundError:
        return _parquet_not_found(_catalog_inventory_parquet())

    if not rows:
        source_status = _inventory_source_status("istat_sdmx")
        return {
            "error": "source_unavailable",
            "artifact": _display_path(_INVENTORY_PARQUET),
            "cache": cache,
            "source_id": "istat_sdmx",
            "message": "No ISTAT SDMX rows found in catalog_inventory_latest.parquet.",
            "source_status": source_status,
            "filters": {"keywords": clean_keywords, "limit": safe_limit},
            "dataflows": [],
            "returned": 0,
            "matched": 0,
        }

    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        text = " ".join(
            str(item.get(key) or "") for key in ("item_id", "item_name", "title", "tags")
        )
        score = _score_dataflow(text, clean_keywords)
        if score <= 0:
            continue
        item["relevance_score"] = score
        results.append(item)

    results.sort(
        key=lambda item: (
            item["relevance_score"],
            str(item.get("title") or item.get("item_name") or ""),
        ),
        reverse=True,
    )
    return {
        "artifact": _display_path(_INVENTORY_PARQUET),
        "cache": cache,
        "filters": {"keywords": clean_keywords, "limit": safe_limit},
        "dataflows": results[:safe_limit],
        "returned": min(len(results), safe_limit),
        "matched": len(results),
    }
