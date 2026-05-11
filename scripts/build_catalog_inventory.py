from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from pathlib import Path
from typing import Any, cast

import duckdb
import pandas as pd

from collectors import dispatch, supported_protocols
from collectors.base import inventory_cfg, now_utc_iso
from collectors.ckan import (
    collect_ckan_inventory_via_search,
    collect_ckan_inventory_via_current_list,
    collect_ckan_inventory_via_package_list,
    collect_ckan_inventory_via_package_show_sample,
    collect as _collect_ckan_inventory,
)
from collectors.sparql import collect as _collect_sparql_inventory
from collectors.sdmx import collect as _collect_sdmx_inventory

from _constants import REGISTRY_PATH, load_registry, stale_reason_from_exception

# Backwards-compatible alias for tests
_error_to_stale_reason = stale_reason_from_exception


logger = logging.getLogger(__name__)


def collect_ckan_inventory(source_id: str, source_cfg: dict[str, Any], captured_at: str):
    res = _collect_ckan_inventory(
        source_id,
        source_cfg,
        captured_at,
        search_fn=collect_ckan_inventory_via_search,
        current_list_fn=collect_ckan_inventory_via_current_list,
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


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "catalog_inventory" / "generated"
DEFAULT_OUT_PARQUET = "catalog_inventory_latest.parquet"
DEFAULT_OUT_REPORT = "catalog_inventory_report.json"


_SOURCE_TIMEOUT = 300  # timeout individuale per fonte (5 min)


def _collect_source(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
    """Worker per ThreadPoolExecutor: raccoglie una fonte e cattura eccezioni.

    Usa threading.Thread(daemon=True) per timeout reale. Se dispatch() non
    completa in _SOURCE_TIMEOUT secondi, la fonte viene marcata fallita.
    Il thread va in timeout ma non blocca l'uscita dello script (daemon=True).
    """
    import threading as _threading

    _result: list = []
    _error: list = []

    def _run() -> None:
        try:
            _result.append(dispatch(source_id, source_cfg, captured_at))
        except Exception as exc:
            _error.append(exc)

    t = _threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=_SOURCE_TIMEOUT)

    if t.is_alive():
        return source_id, [], None, None, TimeoutError(
            f"Source {source_id} timed out after {_SOURCE_TIMEOUT}s"
        )
    if _error:
        return source_id, [], None, None, _error[0]
    res = _result[0]
    return source_id, res.rows, res.warning, res.summary, None


# Formati per cui vale la pena fare sniff leggero del file dati
_SNIFFABLE_FORMATS = {"csv", "xlsx", "xls", "tsv"}


def _is_sniffable(format_str: Any) -> bool:
    """True se format contiene uno dei formati sniffabili (es. 'csv', 'csv,xml')."""
    if not isinstance(format_str, str):
        return False
    return any(f in format_str.lower() for f in _SNIFFABLE_FORMATS)


def _sniff_csv_rows(rows: list[dict[str, Any]], logger: logging.Logger) -> None:
    """Lightweight CSV sniff per item con URL diretto a file dati.

    Scarica primi ~10KB, sniffa encoding/delim/decimal/skip con
    ``toolkit.profile.raw.sniff_source_file`` (puro Python, nessun DuckDB).
    I risultati aggiornano direttamente le righe (encoding_suggested, ecc.).

    Costo: ~0.5s per download + ~0.02s per sniff. Skip per formati non sniffabili
    o URL non HTTP.
    """
    from pathlib import Path
    import tempfile

    from lab_connectors.http import HttpClient
    from toolkit.profile.raw import sniff_source_file

    # Filtra righe con formato sniffabile e URL diretto
    targets = [
        (i, row) for i, row in enumerate(rows)
        if _is_sniffable(row.get("format"))
        and isinstance(row.get("distribution_url"), str)
        and row["distribution_url"].startswith("http")
    ]
    if not targets:
        return

    # Nessun limite — il timeout 5s per download e 8 workers rendono il costo
    # irrisorio (~0.5s per item con 8 workers). Il vero rallentamento era il
    # timeout 15s sulle pagine HTML, fixato separatamente.
    logger.info("  sniff CSV: %d items", len(targets))
    sniffed = 0

    def _infer_sniff_ext(dist_url: str) -> str:
        """Inferisce estensione per tempfile dall'URL (gestisce query string)."""
        from urllib.parse import urlparse
        ext = Path(urlparse(dist_url).path).suffix.lower()
        return ext if ext in (".csv", ".tsv", ".xlsx", ".xls") else ".csv"

    def _sniff_one(dist_url: str) -> dict[str, Any]:
        client = HttpClient(timeout=(3, 5))
        fetch = client.get(dist_url, headers={"Range": "bytes=0-10239"})
        if not fetch.is_ok or fetch.response is None or fetch.response.status_code >= 400:
            return {}
        content = fetch.response.content[:10 * 1024]  # 10KB max
        with tempfile.NamedTemporaryFile(suffix=_infer_sniff_ext(dist_url), delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            sniff = sniff_source_file(tmp_path)
            return {
                "encoding_suggested": sniff.get("encoding_suggested"),
                "delim_suggested": sniff.get("delim_suggested"),
                "decimal_suggested": sniff.get("decimal_suggested"),
                "skip_suggested": sniff.get("skip_suggested", 0),
            }
        finally:
            tmp_path.unlink(missing_ok=True)

    _SNIFF_BATCH_TIMEOUT = 300  # 5 min per batch sniff CSV (matcha _SOURCE_TIMEOUT)
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        fut_to_idx = {pool.submit(_sniff_one, row["distribution_url"]): idx for idx, row in targets}
        for fut in as_completed(fut_to_idx, timeout=_SNIFF_BATCH_TIMEOUT):
            idx = fut_to_idx[fut]
            try:
                result = fut.result()
                if result and result.get("encoding_suggested"):
                    rows[idx].update(result)
                    sniffed += 1
            except Exception:
                pass
    except TimeoutError:
        logger.warning("  sniff CSV timeout after %ds (%d/%d processed)",
                       _SNIFF_BATCH_TIMEOUT, sniffed, len(targets))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    logger.info("  sniff CSV OK: %d/%d", sniffed, len(targets))


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
        default=1,
        choices=range(1, 9),
        metavar="N (1-8)",
        help="Thread per la raccolta parallela (default: 1 = seriale).",
    )
    parser.add_argument(
        "--source-ids",
        nargs="+",
        metavar="SOURCE_ID",
        help="Limita il build a queste source_id (spazio-separato).",
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

    collected: dict[str, tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None]] = {}
    source_timing: dict[str, float] = {}
    executor = ThreadPoolExecutor(max_workers=args.workers)
    try:
        future_to_id: dict[Any, str] = {}
        submit_times: dict[str, float] = {}
        for source_id, source_cfg in inventoriable:
            f = executor.submit(_collect_source, source_id, source_cfg, captured_at)
            future_to_id[f] = source_id
            submit_times[source_id] = time.time()
            # Timing per-fonte: registra quando il future completa,
            # non quando wait() ritorna (che e' il tempo del piu' lento)
            def _record_timing(_sid: str = source_id) -> None:
                source_timing.setdefault(_sid, time.time() - submit_times[_sid])
            f.add_done_callback(lambda _: _record_timing())

        # wait() timeout globale per il batch (rete di sicurezza). Il timeout
        # reale per fonte è in _collect_source (_SOURCE_TIMEOUT = 300s).
        _BATCH_TIMEOUT = 3600
        done, not_done = wait(future_to_id, timeout=_BATCH_TIMEOUT)
        now = time.time()
        for f in not_done:
            sid = future_to_id[f]
            if sid not in source_timing:
                source_timing[sid] = now - submit_times[sid]
            f.cancel()
            logger.warning("Source %s non completato entro %ds (batch timeout), treat as failed", sid, _BATCH_TIMEOUT)
            collected[sid] = ([], None, None, TimeoutError(f"Batch timeout after {_BATCH_TIMEOUT}s"))
        for f in done:
            sid, rows, warning, summary, exc = f.result()
            if sid not in source_timing:
                source_timing[sid] = time.time() - submit_times[sid]
            collected[sid] = (rows, warning, summary, exc)
    finally:
        # shutdown(wait=False) non aspetta task bloccati — il timeout HTTP
        # (5s) li terminerà prima o poi, ma non blocca il workflow.
        executor.shutdown(wait=False, cancel_futures=True)

    # Load existing inventory for merge (always, not just with --source-ids filter)
    existing_df: pd.DataFrame | None = None
    if out_parquet.exists():
        try:
            existing_df = pd.read_parquet(out_parquet)
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
        rows, warning, summary, exc = collected[source_id]
        if exc is not None:
            # Source failed: preserve existing rows as stale
            report["sources"][source_id] = {
                "status": "error",
                "protocol": source_cfg.get("protocol"),
                "error": str(exc),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }
            if existing_df is not None:
                stale_rows = existing_df[existing_df["source_id"] == source_id].copy()
                if not stale_rows.empty:
                    stale_rows["source_status"] = "stale"
                    stale_rows["stale_reason"] = stale_reason_from_exception(exc)
                    all_rows.extend(cast(list[dict[str, Any]], stale_rows.to_dict(orient="records")))
            continue

        # Source succeeded: add rows with active status
        for row in rows:
            row["source_status"] = "active"
            row["stale_reason"] = None
            row["last_successful_fetch"] = captured_at

        # Lightweight CSV sniff: per ogni item con URL diretto a file dati,
        # scarica ~10KB e sniffa encoding/delim/decimal/skip.
        # Non usa DuckDB — solo puro Python, ~0.02s per sniff + ~0.5s per download.
        # I risultati (encoding_suggested, delim_suggested, ...) vengono scritti
        # direttamente nel catalog inventory, pronti per source-check e scoring.
        if rows:
            _sniff_csv_rows(rows, logger)

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
        df = df.drop_duplicates(subset=["source_id", "item_id"], keep="first").drop(columns=["_status_ord"])
        df = df.reset_index(drop=True)
        logger.info("  dedup (source_id, item_id): %d items", len(df))

    # After merge, if still no rows → nothing worked
    if df.empty:
        raise RuntimeError("No catalog inventory rows collected (no sources succeeded and no preserved rows).")

    # merge report: mantieni le entry precedenti per le fonti non ri-buildate in questo run
    # (le rows sono già preservate nel DataFrame; il report JSON tiene traccia storica)
    if out_report.exists():
        with out_report.open(encoding="utf-8") as fh:
            prev_report = json.load(fh)
        for sid, info in prev_report.get("sources", {}).items():
            if sid not in report["sources"]:
                report["sources"][sid] = info

    con = duckdb.connect()
    con.register("inventory_df", df)
    con.execute("CREATE TABLE inventory AS SELECT * FROM inventory_df")
    con.execute("COPY inventory TO ? (FORMAT PARQUET)", [str(out_parquet)])
    con.close()

    with out_report.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print(f"{'Source':<24} {'Status':<12} {'Items':<8} {'Time':<8}  {'Note'}")
    print("-" * 72)
    for source_id, source_cfg in inventoriable:
        rows_count, _warning, _summary, exc = collected[source_id]
        elapsed = source_timing.get(source_id, 0)
        if exc is not None:
            err_str = str(exc)
            if "timed out" in err_str.lower():
                status = "TIMEOUT"
                note = err_str[:70]
            else:
                status = "ERROR"
                note = type(exc).__name__
        else:
            status = "OK"
            note = f"{len(rows_count)} items" if rows_count else "empty"
        print(f"{source_id:<24} {status:<12} {len(rows_count):<8} {elapsed:>6.1f}s  {note}")
    print()

    print(f"Wrote {len(all_rows)} rows to {out_parquet}")
    print(f"Wrote report to {out_report}")


if __name__ == "__main__":
    main()
