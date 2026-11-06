#!/usr/bin/env python3
"""
run_pipeline: orchestrazione sequenziale del nuovo funnel SO.

Steps:
  1. Load inventory from parquet (prodotto da build_catalog_inventory.py)
  2. MERGE: raggruppa item in dataset logici (compute_dataset_group)
  3. VALIDATE: per ogni gruppo, pick best URL → HEAD → sniff CSV schema
  4. Output: validated.parquet + summary JSON

Uso:
    python scripts/pipeline/run_pipeline.py
    python scripts/pipeline/run_pipeline.py --inventory data/custom.parquet
    python scripts/pipeline/run_pipeline.py --source-ids mef_irpef aci
    python scripts/pipeline/run_pipeline.py --dry-run  # solo merge, niente HTTP
    python scripts/pipeline/run_pipeline.py --max-groups 10  # primi 10 gruppi
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import pandas as pd

from scripts.collectors import dispatch_validate
from scripts.collectors._validate_base import pick_best_url
from scripts.pipeline._merge_utils import add_dataset_group_columns

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = (
    REPO_ROOT / "data" / "catalog_inventory" / "generated" / "catalog_inventory_latest.parquet"
)
DEFAULT_OUTPUT = REPO_ROOT / "data" / "pipeline" / "validated.parquet"
DEFAULT_SUMMARY = REPO_ROOT / "data" / "pipeline" / "summary.json"


# ── Step 1: Load inventory ────────────────────────────────────────────────────


def load_inventory(path: Path, source_ids: list[str] | None = None) -> pd.DataFrame:
    """Load inventory parquet, optionally filtered by source_id."""
    if not path.exists():
        print(f"❌ Inventory not found: {path}")
        print("   Run build_catalog_inventory.py first or specify --inventory")
        sys.exit(1)

    df = pd.read_parquet(path)
    print(f"📦 Loaded inventory: {len(df)} items from {path}")

    if source_ids:
        df = df[df["source_id"].isin(source_ids)]
        print(f"   Filtered to {len(df)} items from sources: {source_ids}")

    return df


# ── Step 2: Merge ─────────────────────────────────────────────────────────────


def run_merge(df: pd.DataFrame, dry_run: bool = False) -> pd.DataFrame:
    """Apply dataset_group merge, return enhanced DataFrame."""
    print(f"\n🔗 Step 2: MERGE — grouping {len(df)} items into logical datasets")

    t0 = time.time()
    df = add_dataset_group_columns(df)
    elapsed = time.time() - t0

    ngroups = df["dataset_group"].nunique()
    print(f"   {ngroups} unique groups ({len(df)} items, {elapsed:.1f}s)")

    if dry_run:
        # Show distribution
        group_sizes = df.groupby("dataset_group").size()
        print("\n   Group size distribution:")
        for size_bucket in [1, 2, 3, 5, 10, 20, 50, 100]:
            count = (group_sizes >= size_bucket).sum()
            if count > 0:
                print(f"     ≥{size_bucket:3d} items: {count:5d} groups")

    return df


# ── Step 3: Validate ──────────────────────────────────────────────────────────


def _validate_one(group_df: pd.DataFrame, client=None) -> dict:
    """Validate a single group: pick protocol, dispatch validator."""
    items = group_df.to_dict("records")
    protocol = str(items[0].get("protocol", "")) if items else ""
    validator = dispatch_validate(protocol)
    return validator(items, client=client)


def run_validate(
    df: pd.DataFrame,
    max_groups: int | None = None,
    workers: int = 1,
    user_agent: str | None = None,
    max_concurrency_per_host: int = 4,
) -> list[dict | None]:
    """For each dataset_group, pick best URL, probe, sniff schema.

    Con workers > 1 usa ThreadPoolExecutor per parallelizzare i probe HTTP.
    Due limiti proteggono le fonti: ``max_concurrency_per_host`` globale e
    ``max_concurrency`` per fonte (colonna inventory, dal registry).
    """
    groups = list(df.groupby("dataset_group"))
    if max_groups:
        groups = groups[:max_groups]

    total = len(groups)
    print(f"\n✅ Step 3: VALIDATE — probing {total} groups (workers={workers})")

    results: list[dict | None] = [None] * total  # pre-allocate per ordine
    ok = 0
    fail = 0
    csv_ok = 0
    t0 = time.time()

    # Client condiviso con circuit breaker: se un host fallisce N volte
    # consecutive (es. lavoro_opendata giu'), i gruppi successivi della
    # stessa fonte non ritentano la rete — CircuitOpenError immediato.
    # Un solo client per tutta la run => il breaker e' cross-gruppo.
    # timeout=5 coerente con _validate_base: il default del client (60s)
    # farebbe bruciare ~114s per fallimento prima che il breaker apra.
    from lab_connectors.http import HttpClient

    # Un client per User-Agent, non uno globale: alcune fonti (ANAC) hanno un
    # WAF che blocca l'UA di default ma accetta un UA browser. L'UA della fonte
    # arriva dalla riga di inventory (`user_agent`), quindi il motore non
    # importa il registry centrale.
    clients: dict[str | None, Any] = {}

    def _client_for(group_df: pd.DataFrame) -> Any:
        ua = user_agent
        if len(group_df):
            value = group_df.iloc[0].get("user_agent")
            if isinstance(value, str) and value:
                ua = value
        if ua not in clients:
            clients[ua] = HttpClient(timeout=5, circuit_threshold=3, user_agent=ua)
        return clients[ua]

    # Rate limit per host e per fonte. Il ThreadPool può avere 16 worker, ma
    # una singola fonte non deve ricevere 16 richieste concorrenti.
    host_semaphores: dict[str, threading.Semaphore] = {}
    source_semaphores: dict[str, threading.Semaphore] = {}
    semaphores_lock = threading.Lock()

    def _semaphore(
        cache: dict[str, threading.Semaphore], key: str, limit: int
    ) -> threading.Semaphore:
        with semaphores_lock:
            if key not in cache:
                cache[key] = threading.Semaphore(max(1, limit))
            return cache[key]

    def _host_for(group_df: pd.DataFrame) -> str:
        if len(group_df):
            items = cast(list[dict[str, Any]], group_df.to_dict("records"))
            best = pick_best_url(items)
            if best:
                url = str(best.get("distribution_url") or best.get("url") or "")
                host = urlsplit(url).hostname
                if host:
                    return host
        return "unknown"

    def _source_for(group_df: pd.DataFrame) -> str:
        return str(group_df.iloc[0].get("source_id") or "unknown") if len(group_df) else "unknown"

    def _source_limit(group_df: pd.DataFrame) -> int | None:
        if not len(group_df):
            return None
        value = group_df.iloc[0].get("max_concurrency")
        if value is None or (isinstance(value, float) and value != value):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _validate_limited(group_df: pd.DataFrame) -> dict[str, Any]:
        host = _host_for(group_df)
        source_id = _source_for(group_df)
        source_limit = _source_limit(group_df)
        with ExitStack() as stack:
            stack.enter_context(_semaphore(host_semaphores, host, max_concurrency_per_host))
            if source_limit:
                stack.enter_context(_semaphore(source_semaphores, source_id, source_limit))
            return _validate_one(group_df, client=_client_for(group_df))

    if workers <= 1:
        # Sequenziale
        for i, (group_name, group_df) in enumerate(groups):
            result = _validate_limited(group_df)
            results[i] = result
            if result.get("reachable"):
                ok += 1
                if result.get("columns"):
                    csv_ok += 1
            else:
                fail += 1
            _report_progress(i + 1, total, ok, fail, csv_ok, t0)
    else:
        # Parallelo con ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {
                pool.submit(_validate_limited, group_df): i
                for i, (_, group_df) in enumerate(groups)
            }
            for future in as_completed(future_map):
                i = future_map[future]
                result = future.result()
                results[i] = result
                if result.get("reachable"):
                    ok += 1
                    if result.get("columns"):
                        csv_ok += 1
                else:
                    fail += 1
                done = sum(1 for r in results if r is not None)
                _report_progress(done, total, ok, fail, csv_ok, t0)

    elapsed = time.time() - t0
    print(
        f"\n   ✅ Validate done: {ok} reachable, {csv_ok} CSV, {fail} unreachable ({elapsed:.1f}s)"
    )
    return results


def _report_progress(done: int, total: int, ok: int, fail: int, csv_ok: int, t0: float):
    """Print progress every 50 groups or at the end."""
    if done % 50 != 0 and done != total:
        return
    pct = done / total * 100
    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 else 0
    print(
        f"   [{done}/{total}] {pct:.0f}% — "
        f"{ok} ok, {fail} unreachable, {csv_ok} csv — "
        f"{rate:.1f} groups/s"
    )


# ── Step 4: Output ────────────────────────────────────────────────────────────


def write_output(
    results: list[dict],
    validated_path: Path,
    summary_path: Path,
    groups_by_source: dict[str, int] | None = None,
):
    """Write validated results as parquet + summary JSON.

    ``groups_by_source`` è il numero di gruppi logici *prima* della
    validazione: serve ai report per distinguere "non validato" da
    "validato e caduto".
    """
    validated_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    # Write validated parquet
    df = pd.DataFrame(results)
    df.to_parquet(validated_path, index=False)
    print(f"\n💾 Validated: {validated_path} ({len(df)} rows)")

    # Write summary JSON
    reachable = sum(1 for r in results if r.get("reachable"))
    csv_with_schema = sum(1 for r in results if r.get("reachable") and r.get("columns"))
    by_source: dict[str, dict] = {
        src: {"total": 0, "reachable": 0, "csv": 0, "groups_total": groups}
        for src, groups in (groups_by_source or {}).items()
    }
    for r in results:
        src = r.get("source_id", "unknown")
        if src not in by_source:
            by_source[src] = {"total": 0, "reachable": 0, "csv": 0, "groups_total": 0}
        by_source[src]["total"] += 1
        if r.get("reachable"):
            by_source[src]["reachable"] += 1
        if r.get("columns"):
            by_source[src]["csv"] += 1

    summary = {
        "pipeline_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_groups": len(results),
        "groups_total": sum(groups_by_source.values()) if groups_by_source else len(results),
        "reachable": reachable,
        "unreachable": len(results) - reachable,
        "csv_with_schema": csv_with_schema,
        "by_source": {
            src: stats for src, stats in sorted(by_source.items(), key=lambda x: -x[1]["total"])
        },
    }

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"📊 Summary: {summary_path}")
    print(
        f"   {summary['total_groups']} groups, {summary['reachable']} reachable, {summary['csv_with_schema']} CSV"
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Run the SO pipeline: merge → validate → output")
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help=f"Inventory parquet path (default: {DEFAULT_INVENTORY})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output validated parquet (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY,
        help=f"Output summary JSON (default: {DEFAULT_SUMMARY})",
    )
    parser.add_argument(
        "--source-ids",
        nargs="+",
        help="Filter to specific source IDs (e.g., --source-ids aci mef_irpef)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only run merge step, skip HTTP probes",
    )
    parser.add_argument(
        "--max-groups",
        type=int,
        help="Max groups to validate (for testing)",
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Skip merge step (use existing dataset_group column)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for HTTP probes (default: 1, sequenziale)",
    )
    parser.add_argument(
        "--max-concurrency-per-host",
        type=int,
        default=4,
        help="Max richieste concorrenti per host nel validate (default: 4)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("🧪 SO Pipeline: merge → validate")
    print("=" * 60)

    # Step 1: Load
    df = load_inventory(args.inventory, args.source_ids)

    # Step 2: Merge
    if not args.skip_merge:
        df = run_merge(df, dry_run=args.dry_run)
    else:
        print("\n⏩ Skipping merge (--skip-merge)")
        if "dataset_group" not in df.columns:
            print("❌ No dataset_group column found, cannot skip merge")
            sys.exit(1)
        ngroups = df["dataset_group"].nunique()
        print(f"   Using existing groups: {ngroups}")

    groups_by_source = (
        df.groupby("source_id")["dataset_group"].nunique().to_dict() if "source_id" in df else {}
    )

    # Step 3: Validate
    if args.dry_run:
        print("\n⏩ Skipping validate (--dry-run)")
    else:
        results = run_validate(
            df,
            max_groups=args.max_groups,
            workers=args.workers,
            max_concurrency_per_host=args.max_concurrency_per_host,
        )
        write_output(results, args.output, args.summary, groups_by_source=groups_by_source)

    print("\n✅ Pipeline complete")


if __name__ == "__main__":  # pragma: no cover
    main()
