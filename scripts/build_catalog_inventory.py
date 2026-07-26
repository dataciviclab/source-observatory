from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, cast

import pandas as pd
from lab_connectors.duckdb import safe_connect

from scripts._constants import (
    CATALOG_INVENTORY_DIR_PATH,
    RADAR_SUMMARY_PATH,
    REGISTRY_PATH,
    get_red_source_ids,
    load_registry,
    stale_reason_from_exception,
)
from scripts.collectors import dispatch, supported_protocols
from scripts.collectors.base import inventory_cfg, now_utc_iso
from scripts.collectors.ckan import (
    collect as _collect_ckan_inventory,
)
from scripts.collectors.ckan import (
    collect_ckan_inventory_via_package_list,
    collect_ckan_inventory_via_package_show_sample,
    collect_ckan_inventory_via_search,
)
from scripts.collectors.sdmx import collect as _collect_sdmx_inventory
from scripts.collectors.sparql import collect as _collect_sparql_inventory

# Backwards-compatible alias for tests
_error_to_stale_reason = stale_reason_from_exception


logger = logging.getLogger(__name__)


def collect_ckan_inventory(source_id: str, source_cfg: dict[str, Any], captured_at: str):
    res = _collect_ckan_inventory(
        source_id,
        source_cfg,
        captured_at,
        search_fn=collect_ckan_inventory_via_search,
        package_list_fn=collect_ckan_inventory_via_package_list,
        package_show_sample_fn=collect_ckan_inventory_via_package_show_sample,
    )
    return res.rows, res.warning


def collect_sparql_inventory(source_id: str, source_cfg: dict[str, Any], captured_at: str):
    res = _collect_sparql_inventory(source_id, source_cfg, captured_at)
    return res.rows, res.summary


def collect_sdmx_inventory(source_id: str, source_cfg: dict[str, Any], captured_at: str):
    res = _collect_sdmx_inventory(source_id, source_cfg, captured_at)
    return res.rows, res.warning


DEFAULT_OUT_DIR = CATALOG_INVENTORY_DIR_PATH
DEFAULT_OUT_PARQUET = "catalog_inventory_latest.parquet"
DEFAULT_OUT_REPORT = "catalog_inventory_report.json"


_SOURCE_TIMEOUT = 120  # timeout individuale per fonte (2 min)
# Timestamp di effettivo avvio thread executor (non di submission).
# Usato dal timeout loop per non timeoutare fonti in coda (queued).
_SOURCE_STARTED: dict[str, float] = {}


def _collect_source(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[
    str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None
]:
    """Worker per ThreadPoolExecutor: raccoglie una fonte e cattura eccezioni.

    NON usa threading.Thread annidato — dispatch() ha già timeout HTTP
    esplicito via HttpClient. Il timeout globale per fonte è gestito dal
    chiamante via source_timing check nel loop wait()/heartbeat.

    Registra l'effettivo avvio in _SOURCE_STARTED per evitare che fonti
    in coda (queued) vengano timeoutate prima di partire.

    Il vantaggio: niente GIL contention su join(), niente daemon thread leak,
    niente doppio annidamento di thread.
    """
    _SOURCE_STARTED[source_id] = time.time()
    try:
        res = dispatch(source_id, source_cfg, captured_at)
        return source_id, res.rows, res.warning, res.summary, None
    except Exception as exc:
        return source_id, [], None, None, exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Costruisce il catalog inventory derivato dal registry di source-observatory."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory di output per parquet e report JSON.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        choices=range(1, 17),
        metavar="N (1-16)",
        help="Thread per la raccolta parallela (default: 4).",
    )
    parser.add_argument(
        "--source-ids",
        nargs="+",
        metavar="SOURCE_ID",
        help="Limita il build a queste source_id (spazio-separato).",
    )
    parser.add_argument(
        "--skip-red-sources",
        action="store_true",
        default=False,
        help="Skip fonti con status RED in radar_summary.json (evita timeout su fonti down).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir
    out_parquet = out_dir / DEFAULT_OUT_PARQUET
    out_report = out_dir / DEFAULT_OUT_REPORT

    registry = load_registry()
    captured_at = now_utc_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    _SOURCE_STARTED.clear()

    all_rows: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "captured_at": captured_at,
        "registry_path": str(REGISTRY_PATH),
        "sources": {},
    }

    source_id_filter = set(args.source_ids) if args.source_ids else None

    inventoriable: list[tuple[str, dict[str, Any]]] = []
    for source_id, source_cfg in registry.items():
        if source_id_filter and source_id not in source_id_filter:
            continue
        if source_cfg.get("source_kind") != "catalog":
            continue
        if source_cfg.get("observation_mode") != "catalog-watch":
            continue

        inv = inventory_cfg(source_cfg)
        if inv.get("non_inventoriable"):
            report["sources"][source_id] = {
                "status": "non_inventariabile",
                "protocol": source_cfg.get("protocol"),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": inv.get("reason", "Fonte non inventariabile."),
            }
            continue

        protocol = source_cfg.get("protocol")
        if protocol not in supported_protocols():
            report["sources"][source_id] = {
                "status": "protocol_not_supported",
                "protocol": protocol,
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
                "reason": f"Protocollo {protocol} non ancora supportato dal builder inventory.",
            }
            continue

        inventoriable.append((source_id, source_cfg))

    # ── Skip RED sources da radar ─────────────────────────────────────────────
    if args.skip_red_sources:
        red_ids = get_red_source_ids()
        if red_ids:
            before = len(inventoriable)
            inventoriable = [(sid, cfg) for sid, cfg in inventoriable if sid not in red_ids]
            skipped = before - len(inventoriable)
            if skipped:
                print(
                    f"  skip RED sources (radar): {red_ids} — {skipped} fonti saltate",
                    file=sys.stderr,
                )
        elif not RADAR_SUMMARY_PATH.exists():
            print("  skip-red-sources: radar_summary.json not found", file=sys.stderr)

    collected: dict[
        str,
        tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None],
    ] = {}
    source_timing: dict[str, float] = {}

    # Timeout per-fonte: leggibile dal blocco inventory.timeout nel registry,
    # fallback a _SOURCE_TIMEOUT (120s). Permette a fonti lente (es. openbdap
    # con sample_size=4000) di avere più tempo senza impattare le altre.
    source_timeout: dict[str, int] = {}
    for source_id, source_cfg in inventoriable:
        inv = inventory_cfg(source_cfg)
        source_timeout[source_id] = int(inv.get("timeout", _SOURCE_TIMEOUT))

    executor = ThreadPoolExecutor(max_workers=args.workers)
    try:
        future_to_id: dict[Any, str] = {}
        submit_times: dict[str, float] = {}
        for source_id, source_cfg in inventoriable:
            f = executor.submit(_collect_source, source_id, source_cfg, captured_at)
            future_to_id[f] = source_id
            submit_times[source_id] = time.time()

            # Timing per-fonte: registra quando il future completa,
            # non quando wait() ritorna (che e' il tempo del piu' lento).
            # NOTA: chiudere _sid nel default del lambda per evitare
            # il bug classico di chiusura su variabile di loop.
            def _record_timing(_f: object, _sid: str = source_id) -> None:
                source_timing.setdefault(_sid, time.time() - submit_times[_sid])

            f.add_done_callback(_record_timing)

        # wait() con heartbeat ogni 30s. Il timeout per-fonte è imposto
        # via submission time, non via thread join annidato (eliminato).
        # Questa è la root cause fix: niente daemon thread leak, niente
        # GIL contention su join() in C extension (XML parsing).
        _BATCH_TIMEOUT = 3600
        _HEARTBEAT_INTERVAL = 30
        pending: set[Any] = set(future_to_id.keys())
        batch_start = time.time()
        while pending:
            remaining = _BATCH_TIMEOUT - (time.time() - batch_start)
            if remaining <= 0:
                break

            batch_done, pending = wait(pending, timeout=min(_HEARTBEAT_INTERVAL, remaining))

            # Process completed futures from this batch
            now = time.time()
            for f in batch_done:
                sid = future_to_id[f]
                try:
                    _, rows, warning, summary, err = f.result()
                except Exception as exc:
                    collected[sid] = ([], None, None, exc)
                else:
                    if sid not in source_timing:
                        source_timing[sid] = now - submit_times[sid]
                    collected[sid] = (rows, warning, summary, err)

            # Per-source timeout: usa source_timeout[sid] dal registry
            # (fallback _SOURCE_TIMEOUT) MA solo per fonti effettivamente
            # avviate (presenti in _SOURCE_STARTED). Fonti in coda (queued)
            # non vengono timeoutate — il timeout parte dall'effettiva
            # esecuzione, non dalla submission.
            for f in list(pending):
                sid = future_to_id[f]
                if sid not in _SOURCE_STARTED:
                    continue
                to = source_timeout.get(sid, _SOURCE_TIMEOUT)
                if now - _SOURCE_STARTED[sid] >= to:
                    pending.discard(f)
                    f.cancel()
                    if sid not in source_timing:
                        source_timing[sid] = now - submit_times[sid]
                    collected[sid] = (
                        [],
                        None,
                        None,
                        TimeoutError(f"Source {sid} timed out after {to}s"),
                    )
                    print(
                        f"  [timeout] {sid} — {(now - submit_times[sid]):.0f}s"
                        f" exceeded {to}s limit",
                        file=sys.stderr,
                        flush=True,
                    )

            # Heartbeat
            if pending:
                elapsed = now - batch_start
                print(
                    f"  [heartbeat] {len(collected)}/{len(inventoriable)} sources done"
                    f" in {elapsed:.0f}s — still waiting:"
                    f" {[f'{future_to_id[f]}({now - submit_times[future_to_id[f]]:.0f}s)' for f in pending]}",
                    file=sys.stderr,
                    flush=True,
                )

        # Batch timeout: sources that still haven't completed
        now = time.time()
        for f in pending:
            sid = future_to_id[f]
            if sid not in source_timing:
                source_timing[sid] = now - submit_times[sid]
            f.cancel()
            if sid not in collected:
                logger.warning(
                    "Source %s non completato entro %ds (batch timeout), treat as failed",
                    sid,
                    _BATCH_TIMEOUT,
                )
                collected[sid] = (
                    [],
                    None,
                    None,
                    TimeoutError(f"Batch timeout after {_BATCH_TIMEOUT}s"),
                )
    finally:
        # shutdown(wait=False) non aspetta task bloccati — il timeout HTTP
        # (5s) li terminerà prima o poi, ma non blocca il workflow.
        executor.shutdown(wait=False, cancel_futures=True)

    # Load existing inventory for merge (always, not just with --source-ids filter)
    existing_df: pd.DataFrame | None = None
    if out_parquet.exists():
        try:
            existing_df = pd.read_parquet(out_parquet)
            # Drop colonne morte (mai popolate) — https://github.com/dataciviclab/source-observatory/issues/372
            _COLONNE_MORTE = {"civic_priority"}
            da_droppare = _COLONNE_MORTE & set(existing_df.columns)
            if da_droppare:
                existing_df = existing_df.drop(columns=da_droppare)
                print(f"🧹 Droppate colonne morte: {da_droppare}", file=sys.stderr)
        except Exception:
            existing_df = None

    # Check if existing_df has source_status column — if not, a full re-run is needed
    # to populate the new fields consistently across all sources
    if existing_df is not None:
        if "source_status" not in existing_df.columns:
            print(
                "WARNING: existing inventory lacks 'source_status' column. "
                "A full re-run is recommended to populate stale/active semantics consistently. "
                "(New fields added in this PR: source_status, stale_reason, last_successful_fetch)",
                file=sys.stderr,
            )

    for source_id, source_cfg in inventoriable:
        rows, warning, summary, err = collected[source_id]
        if err is not None:
            # Source failed: preserve existing rows as stale
            report["sources"][source_id] = {
                "status": "error",
                "protocol": source_cfg.get("protocol"),
                "error": str(err),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }
            if existing_df is not None:
                stale_rows = existing_df[existing_df["source_id"] == source_id].copy()
                if not stale_rows.empty:
                    stale_rows["source_status"] = "stale"
                    stale_rows["stale_reason"] = stale_reason_from_exception(err)
                    all_rows.extend(
                        cast(list[dict[str, Any]], stale_rows.to_dict(orient="records"))
                    )
            continue

        # Source succeeded: add rows with active status
        for row in rows:
            row["source_status"] = "active"
            row["stale_reason"] = None
            row["last_successful_fetch"] = captured_at

        all_rows.extend(rows)

        source_report: dict[str, Any] = {
            "status": "ok",
            "protocol": source_cfg.get("protocol"),
            "rows": len(rows),
            "method": source_cfg.get("catalog_baseline", {}).get("method"),
        }
        if warning:
            source_report["warning"] = warning
        if summary:
            source_report["summary"] = summary
        report["sources"][source_id] = source_report

    df = pd.DataFrame(all_rows)

    # Merge with existing inventory (preserves sources not in this run)
    if out_parquet.exists() and existing_df is not None:
        # Sources not in this run at all → keep as-is
        this_run_sources = {sid for sid, _ in inventoriable}
        preserved = existing_df[~existing_df["source_id"].isin(this_run_sources)]
        if not preserved.empty:
            # Mark as stale if older than last successful fetch
            preserved = preserved.copy()
            if "source_status" in preserved.columns:
                preserved["source_status"] = preserved["source_status"].fillna("unknown")
            else:
                preserved["source_status"] = "unknown"
            df = pd.concat([df, preserved], ignore_index=True)

    # ── Fix C: dedup per (source_id, item_id) ─────────────────────────────────────
    # quando una fonte produce righe con stesso item_id ma formati diversi (es. CSV/JSON/XML),
    # o quando preserve aggiunge righe stale dello stesso item_id, teniamo la più recente.
    # Priorità: active > stale; a parità di status, last_successful_fetch più recente.
    if not df.empty and "item_id" in df.columns and "source_id" in df.columns:
        _status_order = {"active": 0, "stale": 1, "unknown": 2}
        df["_status_ord"] = df["source_status"].map(lambda s: _status_order.get(str(s), 2))
        df = df.sort_values(["_status_ord", "last_successful_fetch"], ascending=[True, False])
        df = df.drop_duplicates(subset=["source_id", "item_id"], keep="first").drop(
            columns=["_status_ord"]
        )
        df = df.reset_index(drop=True)
        logger.info("  dedup (source_id, item_id): %d items", len(df))

    # After merge, if still no rows → nothing worked
    if df.empty:
        raise RuntimeError(
            "No catalog inventory rows collected (no sources succeeded and no preserved rows)."
        )

    # merge report: mantieni le entry precedenti per le fonti non ri-buildate in questo run
    # (le rows sono già preservate nel DataFrame; il report JSON tiene traccia storica)
    if out_report.exists():
        with out_report.open(encoding="utf-8") as fh:
            prev_report = json.load(fh)
        for sid, info in prev_report.get("sources", {}).items():
            if sid not in report["sources"]:
                report["sources"][sid] = info

    with safe_connect() as con:
        con.register("inventory_df", df)
        con.execute("CREATE TABLE inventory AS SELECT * FROM inventory_df")
        con.execute("COPY inventory TO ? (FORMAT PARQUET)", [str(out_parquet)])

    with out_report.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print(f"{'Source':<24} {'Status':<12} {'Items':<8} {'Time':<8}  {'Note'}")
    print("-" * 72)
    for source_id, source_cfg in inventoriable:
        rows_count, _warning, _summary, err = collected[source_id]
        elapsed = source_timing.get(source_id, 0)
        if err is not None:
            err_str = str(err)
            if "timed out" in err_str.lower():
                status = "TIMEOUT"
                note = err_str[:70]
            else:
                status = "ERROR"
                note = type(err).__name__
        else:
            status = "OK"
            note = f"{len(rows_count)} items" if rows_count else "empty"
        print(f"{source_id:<24} {status:<12} {len(rows_count):<8} {elapsed:>6.1f}s  {note}")
    print()

    print(f"Wrote {len(all_rows)} rows to {out_parquet}")
    print(f"Wrote report to {out_report}")


if __name__ == "__main__":
    main()
    # os._exit(0) fuori da main() così main() è testabile.
    # Necessario perché i worker thread di ThreadPoolExecutor sono non-daemon
    # in Python 3.12: quando main() ritorna, Python chiama threading._shutdown()
    # che fa join dei worker — bloccati su HTTP request in timeout.
    # Il lavoro (parquet, report) è già completato.
    os._exit(0)
