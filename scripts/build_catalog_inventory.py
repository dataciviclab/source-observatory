from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from collectors import dispatch, supported_protocols
from collectors.base import inventory_cfg, now_utc_iso
# Re-exporting functions for tests (monkeypatching support)
from collectors.ckan import (
    collect_ckan_inventory_via_search,
    collect_ckan_inventory_via_current_list,
    collect_ckan_inventory_via_package_list,
    collect_ckan_inventory_via_package_show_sample,
    collect as _collect_ckan_inventory,
)
from collectors.sparql import collect as _collect_sparql_inventory
from collectors.sdmx import collect as _collect_sdmx_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "catalog_inventory" / "generated"
DEFAULT_OUT_PARQUET = "catalog_inventory_latest.parquet"
DEFAULT_OUT_REPORT = "catalog_inventory_report.json"

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


def load_registry() -> dict[str, Any]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _collect_source(
    source_id: str, source_cfg: dict[str, Any], captured_at: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
    """Worker per ThreadPoolExecutor: raccoglie una fonte e cattura eccezioni."""
    try:
        result = dispatch(source_id, source_cfg, captured_at)
        return source_id, result.rows, result.warning, result.summary, None
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
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_id = {
            executor.submit(_collect_source, source_id, source_cfg, captured_at): source_id
            for source_id, source_cfg in inventoriable
        }
        for future in as_completed(future_to_id):
            sid, rows, warning, summary, exc = future.result()
            collected[sid] = (rows, warning, summary, exc)

    for source_id, source_cfg in inventoriable:
        rows, warning, summary, exc = collected[source_id]
        if exc is not None:
            report["sources"][source_id] = {
                "status": "error",
                "protocol": source_cfg.get("protocol"),
                "error": str(exc),
                "method": source_cfg.get("catalog_baseline", {}).get("method"),
            }
            continue

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

    if not all_rows:
        raise RuntimeError("No catalog inventory rows collected.")

    df = pd.DataFrame(all_rows)

    if source_id_filter and out_parquet.exists():
        existing = pd.read_parquet(out_parquet)
        existing = existing[~existing["source_id"].isin(source_id_filter)]
        df = pd.concat([existing, df], ignore_index=True)

        # merge report: mantieni le entry precedenti per le fonti non ri-buildate
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

    print(f"Wrote {len(all_rows)} rows to {out_parquet}")
    print(f"Wrote report to {out_report}")


if __name__ == "__main__":
    main()
