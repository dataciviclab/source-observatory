#!/usr/bin/env python3
"""
run_portal_scout_batch.py — batch runner per portal_scout.

Legge discovered_portals.parquet, filtra candidati strutturati non in registry,
costruisce un registry YAML temporaneo per portal_scout.py, invoca lo scout,
e restituisce uno stato machine-readable.

Uso:
    python scripts/run_portal_scout_batch.py  # usa paths di default
    python scripts/run_portal_scout_batch.py \
        --portals data/portal_scout/discovered_portals.parquet \
        --registry data/radar/sources_registry.yaml \
        --out-dir data/portal_scout/scout_results
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# ── paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTALS = REPO_ROOT / "data" / "portal_scout" / "discovered_portals.parquet"
DEFAULT_REGISTRY = REPO_ROOT / "data" / "radar" / "sources_registry.yaml"
DEFAULT_OUT = REPO_ROOT / "data" / "portal_scout" / "scout_results"


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch runner per portal_scout.")
    parser.add_argument("--portals", type=Path, default=DEFAULT_PORTALS, help="Parquet con portali scoperti.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Registry YAML esistente (per escludere gia' scoutati).")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="Directory output scout results.")
    parser.add_argument("--portal-scout", type=Path, default=REPO_ROOT / "scripts" / "portal_scout.py", help="Path a portal_scout.py.")
    args = parser.parse_args(argv)

    # ── load portals parquet ────────────────────────────────────────────────
    if not args.portals.exists():
        print(f"[error] portals parquet non trovato: {args.portals}", file=sys.stderr)
        return 1

    df = pd.read_parquet(args.portals)

    # ── filter structured candidates not in registry ───────────────────────
    candidates = df[
        df["protocol"].isin(["ckan", "sdmx", "sparql"])
    ]
    if candidates.empty:
        print("Nessun candidato strutturato da sondare.")
        _write_status(args.out_dir, "skipped", 0, 0, 0)
        return 0

    print(f"Candidati da sondare: {len(candidates)}")

    # ── build registry dict for portal_scout ──────────────────────────────
    cfg: dict[str, Any] = {}
    for _, row in candidates.iterrows():
        entry: dict[str, Any] = {"protocol": row["protocol"], "base_url": row["base_url"]}
        if row["protocol"] == "sparql" and row.get("probe_url"):
            entry["sparql"] = {"endpoint_url": row["probe_url"]}
        cfg[row["domain"]] = entry

    # ── write temp registry and invoke portal_scout ────────────────────────
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg, f)
        tmp_registry = Path(f.name)

    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(args.portal_scout), "--registry-path", str(tmp_registry), "--out-dir", str(args.out_dir)],
            check=False,
        )
    finally:
        tmp_registry.unlink()

    # ── determine status based on summary ──────────────────────────────────
    summary_path = args.out_dir / "_scout_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        ok = summary.get("ok", 0)
        error = summary.get("error", 0)
        skipped = summary.get("skipped", 0)
        if error == 0:
            status = "ok"
        elif ok > 0:
            status = f"degraded ({error} errors)"
        else:
            status = f"failed ({error} errors)"
        _write_status(args.out_dir, status, ok, error, skipped)
        print(f"Scout completed: {status}")
        return 0
    else:
        # fallback: use exit code
        if result.returncode == 0:
            status = "ok"
        else:
            status = f"failed (exit {result.returncode})"
        _write_status(args.out_dir, status, 0, 1, 0)
        print(f"[warn] summary non trovato, status da exit code: {status}", file=sys.stderr)
        return 1


def _write_status(out_dir: Path, status: str, ok: int, error: int, skipped: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".scout_status").write_text(status)
    summary = {
        "status": status,
        "ok": ok,
        "error": error,
        "skipped": skipped,
    }
    (out_dir / "_batch_status.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())