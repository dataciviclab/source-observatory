"""Build del catalog per-repo: probe → inventory → validate → catalog.json.

Flusso (per un repo dati con ``[tool.observatory]``):

  1. Config: ``pyproject.toml`` → dict fonte (compatibile collectors)
  2. Probe: ``radar_check.probe_url`` sul ``base_url`` + streak dal catalog precedente
  3. Inventory: ``collectors.dispatch`` → righe + parquet locale ``out/so/``
  4. Validate: merge + probe item-level (riuso ``run_pipeline``) → ``out/so/validated.parquet``
  5. Report: ``source_report.build_report`` (funzione pura) → dict catalog
  6. ``datasets_in_use`` dal ``registry/registry.json`` locale
  7. Validazione schema + scrittura ``registry/catalog.json``

Nessun artifact del repo SO centrale viene letto o scritto: il builder e'
totalmente radicato nel repo target.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import pandas as pd

from scripts.catalog.config import load_observatory_config
from scripts.catalog.drift import check_referenced_items
from scripts.catalog.layout import RepoLayout, resolve_layout
from scripts.catalog.pattern_probes import (
    compute_new_content_trigger,
    probe_pattern,
    run_pattern_probes,
)
from scripts.catalog.upstream import load_upstream_map
from scripts.collectors import dispatch
from scripts.pipeline.run_pipeline import run_merge, run_validate
from scripts.radar_check import ProbeResult, probe_url
from scripts.source_report import build_report

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "catalog.schema.json"
CATALOG_SCHEMA_VERSION = 1

# Codici HTTP che indicano un blocco o un limite (WAF, rate limit, auth di
# proxy): non provano che la risorsa non esista, quindi non sono drift.
_INCONCLUSIVE_HTTP_CODES = frozenset({"401", "403", "407", "429"})


class _UrlProbe:
    """Verifica l'esistenza di un URL consumato, con cache per run.

    Adatta ``probe_pattern`` al contratto tri-stato di ``drift``:

      - 2xx → ``True`` (l'URL esiste);
      - risposta HTTP di errore (4xx/5xx) → ``False`` (non esiste);
      - errore di rete (``http_code == "-"``) → ``None``, non concludente:
        un timeout non deve produrre un falso drift.

    Serve perché l'inventario non è autorevole per gli URL di ``http_file``:
    può descrivere un altro endpoint dello stesso dato (AGID) o una sola
    distribuzione per item (Consip: un resource per package, N anni nel repo).
    """

    def __init__(self, user_agent: str | None = None) -> None:
        self._user_agent = user_agent
        self._cache: dict[str, bool | None] = {}

    def __call__(self, url: str) -> bool | None:
        if url not in self._cache:
            self._cache[url] = self._probe(url)
        return self._cache[url]

    def _probe(self, url: str) -> bool | None:
        # Solo esistenza: nessuna lettura del corpo (basta lo status).
        result = probe_pattern(url, user_agent=self._user_agent, read_body=False)
        if result.get("available"):
            return True
        code = str(result.get("http_code") or "-")
        if code == "-" or code in _INCONCLUSIVE_HTTP_CODES:
            return None
        return False

    @property
    def probed(self) -> int:
        """Quanti URL distinti sono stati verificati via HTTP."""
        return len(self._cache)


def load_catalog_schema() -> dict[str, Any]:
    """JSON schema del catalog (viaggia nel package engine)."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_catalog(catalog: dict[str, Any]) -> None:
    """Valida il catalog contro lo schema del package.

    Raises:
        jsonschema.ValidationError: catalog non conforme.
        FileNotFoundError: schema mancante nell'installazione.
    """
    schema = load_catalog_schema()
    jsonschema.validate(instance=catalog, schema=schema)


def load_previous_catalog(layout: RepoLayout) -> dict[str, Any] | None:
    """Legge il catalog committato precedente (per streak). None se assente."""
    if not layout.catalog_path.exists():
        return None
    try:
        return json.loads(layout.catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_local_datasets_in_use(layout: RepoLayout, source_id: str) -> list[dict[str, Any]]:
    """Datasets del repo con ``source_id`` coincidente, da registry/registry.json.

    Graceful: registry assente o illeggibile → lista vuota.
    """
    path = layout.toolkit_registry_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out: list[dict[str, str]] = []
    for ds in data.get("datasets") or []:
        if not isinstance(ds, dict) or ds.get("source_id") != source_id:
            continue
        slug = ds.get("slug")
        if not slug:
            continue
        out.append({"slug": str(slug), "status": str(ds.get("stage") or "unknown")})
    return out


def compute_streak(health: dict[str, Any], previous: dict[str, Any] | None) -> int:
    """Consecutive probe con stesso ``radar_status`` (1 se cambiato o primo run)."""
    status = health.get("radar_status")
    prev_health = (previous or {}).get("health") or {}
    if prev_health.get("radar_status") == status and status is not None:
        try:
            return int(prev_health.get("streak") or 1) + 1
        except (TypeError, ValueError):
            return 1
    return 1


def _probe_result_as_dict(result: ProbeResult) -> dict[str, Any]:
    d = asdict(result)
    # Chiavi attese da build_report(radar_result=...)
    return {
        "status": d["status"],
        "http_code": d["http_code"],
        "note": d["note"],
        "ssl_fallback_used": d["ssl_fallback_used"],
    }


def build_catalog(
    repo_root: Path | None = None,
    *,
    workers: int = 1,
    skip_validate: bool = False,
    max_groups: int | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Costruisce il catalog per-repo e (opzionalmente) lo scrive.

    Args:
        repo_root: Root del repo dati (default: CWD).
        workers: Parallellismo probe HTTP during validate.
        skip_validate: Salta la fase item-level (probe+inventory-only).
        max_groups: Limita i gruppi validati (testing).
        write: Scrive catalog.json + parquet in out/so/.

    Returns:
        Il dict catalog (validato contro lo schema).
    """
    layout = resolve_layout(repo_root)
    cfg = load_observatory_config(layout.repo_root)
    source_id = cfg["source_id"]
    previous = load_previous_catalog(layout)

    print(f"🔭 so-catalog: {source_id} @ {layout.repo_root}")

    # ── Probe ────────────────────────────────────────────────────────────────
    print(f"  → probe {cfg['base_url']}")
    probe = probe_url(cfg["base_url"], user_agent=cfg.get("user_agent"))
    radar_result = _probe_result_as_dict(probe)
    print(f"  ← {radar_result['status']} (HTTP {radar_result['http_code']})")

    # ── Inventory ────────────────────────────────────────────────────────────
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    if cfg.get("observation_mode") == "radar-only":
        print("  ⏭️  inventory skipped (radar-only)")
    else:
        print("  → inventory")
        inv = dispatch(source_id, cfg, captured_at)
        rows = inv.rows
        if inv.warning:
            print(f"  ⚠️  inventory warning: {inv.warning}")
        print(f"  ← {len(rows)} items")

    layout.out_dir.mkdir(parents=True, exist_ok=True)
    inventory_df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not inventory_df.empty:
        inventory_df["source_id"] = source_id
        inventory_df.to_parquet(layout.inventory_parquet, index=False)
        print(f"  💾 {layout.inventory_parquet}")

    # ── Validate (item-level) ────────────────────────────────────────────────
    validated_rows: list[dict[str, Any]] = []
    if skip_validate or cfg.get("observation_mode") == "radar-only" or inventory_df.empty:
        reason = (
            "skip-validate"
            if skip_validate
            else "radar-only"
            if cfg.get("observation_mode") == "radar-only"
            else "empty-inventory"
        )
        print(f"  ⏭️  validate skipped ({reason})")
    else:
        print("  → validate")
        merged = run_merge(inventory_df)
        validated_rows_raw = run_validate(
            merged,
            max_groups=max_groups,
            workers=workers,
            user_agent=cfg.get("user_agent"),
        )
        validated_rows = [r for r in validated_rows_raw if r is not None]
        if validated_rows:
            pd.DataFrame(validated_rows).to_parquet(layout.validated_parquet, index=False)
            print(f"  💾 {layout.validated_parquet}")

    # ── Assemble catalog ─────────────────────────────────────────────────────
    datasets_in_use = load_local_datasets_in_use(layout, source_id)
    upstream_map = load_upstream_map(layout.repo_root)
    for entry in datasets_in_use:
        refs = upstream_map.get(entry["slug"], [])
        if refs:
            entry["upstream"] = refs

    # ── Referenced-item drift ────────────────────────────────────────────────
    # Verifica che gli item upstream referenziati dai dataset esistano ancora.
    # L'inventario non è autorevole per gli URL consumati (può descrivere un
    # altro endpoint o una sola distribuzione per item): quando non conferma,
    # si verifica l'URL via HTTP (``_UrlProbe``).
    url_probe = _UrlProbe(cfg.get("user_agent"))
    drift = check_referenced_items(datasets_in_use, rows, url_probe=url_probe)
    if url_probe.probed:
        print(f"  ℹ️  {url_probe.probed} URL consumati verificati via HTTP")
    if drift["missing"]:
        print(
            f"  ⚠️ referenced-item drift: {len(drift['missing'])} upstream non trovati in inventario"
        )
    elif drift.get("unknown"):
        print(
            f"  ℹ️ referenced-item drift: {len(drift['unknown'])} upstream non verificabili "
            "(inventario non copre l'area)"
        )

    report_cfg = {
        **cfg,
        "last_probed": datetime.now(timezone.utc).date().isoformat(),
        "datasets_in_use": [d["slug"] for d in datasets_in_use],
    }
    catalog = build_report(
        source_id=source_id,
        cfg=report_cfg,
        radar_result=radar_result,
        rows=rows,
        captured_at=captured_at,
        results=validated_rows,
    )
    catalog["repo"] = layout.repo_root.name
    catalog["catalog_schema_version"] = CATALOG_SCHEMA_VERSION
    catalog["datasets_in_use"] = datasets_in_use
    health = catalog.get("health") or {
        "radar_status": radar_result["status"],
        "http_code": radar_result["http_code"],
        "note": radar_result["note"],
        "ssl_fallback": radar_result["ssl_fallback_used"],
    }
    health["streak"] = compute_streak(health, previous)
    catalog["health"] = health

    # ── Referenced-item drift nel catalog ────────────────────────────────────
    catalog["referenced_items"] = drift
    if drift["missing"]:
        verdict = catalog.get("operational_verdict") or {}
        triggers = list(verdict.get("triggers") or [])
        if "referenced_item_missing" not in triggers:
            triggers.append("referenced_item_missing")
        verdict["triggers"] = triggers
        # Non sovrascrivere label gia' impostate (es. NEW_CONTENT)
        if verdict.get("label") == "STABLE":
            verdict["label"] = "REFERENCED_MISSING"
            verdict["score"] = "referenced_missing"
            verdict["next_action"] = "review missing upstream items"
        catalog["operational_verdict"] = verdict

    # ── Pattern probes (sentinel URL per nuovi contenuti) ────────────────────
    probe_cfg = cfg.get("pattern_probes") or []
    if probe_cfg:
        print(f"  → pattern probes ({len(probe_cfg)})")
        probe_results = run_pattern_probes(probe_cfg)
        available = sum(1 for p in probe_results if p.get("available"))
        print(f"  ← {available}/{len(probe_results)} available")
        catalog["pattern_probes"] = probe_results
        if compute_new_content_trigger(probe_results, previous):
            verdict = catalog.get("operational_verdict") or {}
            triggers = list(verdict.get("triggers") or [])
            if "new_content_available" not in triggers:
                triggers.append("new_content_available")
            verdict["triggers"] = triggers
            if verdict.get("label") == "STABLE":
                verdict["label"] = "NEW_CONTENT"
                verdict["score"] = "new_content"
                verdict["next_action"] = "review new upstream content"
            catalog["operational_verdict"] = verdict
            print("  🆕 new_content_available trigger fired")

    validate_catalog(catalog)

    # ── Write ────────────────────────────────────────────────────────────────
    if write:
        layout.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        layout.catalog_path.write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"  💾 {layout.catalog_path}")
        print(
            f"✅ catalog {source_id}: verdict={catalog['operational_verdict']['label']} "
            f"radar={catalog.get('health', {}).get('radar_status')} "
            f"items={catalog['inventory']['total_items']} "
            f"datasets_in_use={len(datasets_in_use)}"
        )

    return catalog
