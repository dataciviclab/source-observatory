#!/usr/bin/env python3
"""
Run end-to-end per una fonte: radar → inventory → source-check → health score.

Utilizzo:
    python scripts/run_source.py mit_opendata
    python scripts/run_source.py dati_camera --verbose
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from _constants import load_registry  # noqa: E402
from collectors import dispatch  # noqa: E402

from scripts.source_report import (  # noqa: E402
    aggregate_inventory_rows,
    aggregate_source_check,
    build_report,
)

# ── HELPERS ──────────────────────────────────────────────────────────────────


def _color(status: str, text: str) -> str:
    if status == "GREEN":
        return f"\033[32m{text}\033[0m"
    elif status in ("YELLOW", "medio", "debole"):
        return f"\033[33m{text}\033[0m"
    elif status in ("RED", "carente"):
        return f"\033[31m{text}\033[0m"
    return text


def _heading(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ── FASI ─────────────────────────────────────────────────────────────────────


def _radar(source_id: str, cfg: dict) -> dict:
    """1. RADAR — probe l'endpoint della fonte."""
    import time as _time

    from scripts.radar_check import _probe_one

    _heading(f"RADAR — {source_id}")
    base_url = cfg.get("base_url", "N/A")
    print(f"  Endpoint: {base_url}")

    t0 = _time.time()
    _, result = _probe_one(source_id, base_url)
    elapsed = _time.time() - t0

    c = _color(result.status, result.status)
    print(f"  Stato: {c}  (HTTP {result.http_code})  [{elapsed:.1f}s]")
    if result.note:
        print(f"  Nota: {result.note}")
    if result.ssl_fallback_used:
        print("  ⚠️  SSL fallback usato")
    if result.final_url and result.final_url != base_url:
        print(f"  ↳ redirect → {result.final_url}")
    if result.content_type:
        print(f"  Content-Type: {result.content_type}")
    return {"status": result.status, "http_code": result.http_code, "note": result.note}


def _inventory(source_id: str, cfg: dict) -> tuple[list[dict], str]:
    """2. INVENTORY — raccoglie dataset/item della fonte.

    Restituisce (rows, captured_at).
    """
    import time as _time

    _heading(f"INVENTORY — {source_id}  ({cfg.get('protocol', '?')})")

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = _time.time()
    try:
        res = dispatch(source_id, cfg, captured_at)
    except Exception as e:
        print(f"  ❌ ERRORE: {e}")
        return [], captured_at
    elapsed = _time.time() - t0

    rows = res.rows
    print(f"  Item: {len(rows)}  [{elapsed:.1f}s]")

    if res.warning:
        print(f"  ⚠️  {res.warning}")

    if res.ssl_fallback_used:
        print("  ⚠️  SSL fallback durante inventory")

    # Aggregazione (condivisa)
    agg = aggregate_inventory_rows(rows)
    if agg["formats"]:
        print(f"  Formati: {', '.join(f'{k}:{v}' for k, v in sorted(agg['formats'].items()))}")
    if agg["years_range"]:
        print(f"  Anni: {agg['years_range'][0]}–{agg['years_range'][1]}")
    if agg["organizations"]:
        orgs = agg["organizations"]
        if len(orgs) <= 5:
            print(f"  Organizzazioni: {', '.join(orgs)}")
        else:
            print(f"  Organizzazioni: {len(orgs)}")

    return rows, captured_at


def _source_check(source_id: str, cfg: dict, rows: list[dict]) -> list[dict]:
    """3. SOURCE-CHECK — probe per-item. Restituisce lista di risultati."""
    protocol = cfg.get("protocol", "")

    if protocol in ("sdmx", "sparql"):
        _heading(f"SOURCE-CHECK — {source_id}")
        print(f"  SKIP: protocollo {protocol} — inventory ha già metadati sufficienti")
        return []

    if not rows:
        _heading(f"SOURCE-CHECK — {source_id}")
        print("  SKIP: nessun item da controllare")
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scripts.bulk_source_check import _check_row
    from scripts.source_check_fetch import configure_source_check_http

    _heading(f"SOURCE-CHECK — {source_id}")
    check_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg = load_registry()
    client = configure_source_check_http()  # client condiviso — circuit breaker unico

    # Workers: rispetta max_concurrency dalla registry (es. MIMIT RNA = 2)
    sc_cfg = cfg.get("source_check", {}) or {}
    max_workers = max(1, int(sc_cfg.get("max_concurrency", 10)))
    max_workers = min(max_workers, len(rows)) if rows else max_workers
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check_row, row, check_ts, reg, client): row for row in rows}  # type: ignore[arg-type]
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                results.append(r)

    agg = aggregate_source_check(results)
    print(f"  Totali: {agg['total']} item")
    print(
        f"  Raggiungibili: {_color('GREEN', str(agg['reachable']))}/{agg['total']}  "
        f"({round(agg['reachable'] / agg['total'] * 100, 1)}%)"
    )
    if agg["circuit"]:
        print(f"  ⚠️  Circuit open: {agg['circuit']}")
    if agg["content_mismatch"]:
        print(f"  ⚠️  Content mismatch: {agg['content_mismatch']}")
    if agg["formats"]:
        top5 = list(agg["formats"].items())[:5]
        print(f"  Formati: {', '.join(f'{k}:{v}' for k, v in top5)}")
    non_ok = {k: v for k, v in agg["statuses"].items() if k not in ("200", "?")}
    if non_ok:
        print(f"  ⚠️  HTTP non-200: {non_ok}")

    if agg["with_preview_count"]:
        print(f"  Preview CSV: {agg['with_preview_count']}/{agg['total']}")
        print(
            f"  PAQA medio: {agg['paqa_avg']:.0f}/100  "
            f"({', '.join(f'{k}:{v}' for k, v in agg['paqa_verdicts'].items())})"
        )

    flags = []
    if agg["no_gran"]:
        flags.append(f"granularità:{agg['no_gran']}/{agg['total']}")
    if agg["no_year"]:
        flags.append(f"anni:{agg['no_year']}/{agg['total']}")
    if flags:
        print(f"  ⚠️  Needs review: {', '.join(flags)}")

    if agg["has_no_url"]:
        print(f"  ℹ️  Senza URL: {agg['has_no_url']}/{agg['total']}")
    print(f"  Worker: {max_workers}")

    if agg["problematic"]:
        print("  🔴 Esempi non raggiungibili:")
        for r in agg["problematic"]:
            url = (r.get("url_checked") or "N/A")[:80] if isinstance(r, dict) else "N/A"
            print(f"    {r.get('http_status')} – {r.get('check_notes')} – {url}")

    return results


# ── MAIN ─────────────────────────────────────────────────────────────────────


def _report_markdown(
    source_id: str,
    cfg: dict,
    radar: str,
    rows: list[dict],
    results: list[dict],
    timing: dict,
) -> None:
    """Stampa report Markdown della fonte (per allegati FOIA)."""
    protocol = cfg.get("protocol", "?")
    print(f"\n## Report fonte: {source_id}")
    print(f"- **Protocollo**: {protocol}")
    print(f"- **RADAR**: {radar}")

    inv_agg = aggregate_inventory_rows(rows)
    if inv_agg["formats"]:
        fmt_str = ", ".join(f"{k}:{v}" for k, v in sorted(inv_agg["formats"].items()) if k != "?")
        print(f"- **Inventory**: {len(rows)} dataset")
        if fmt_str:
            print(f"- **Formati (inventory)**: {fmt_str}")

    sc_agg = aggregate_source_check(results)
    if sc_agg["total"]:
        print(f"- **Source-check**: {sc_agg['reachable']}/{sc_agg['total']} raggiungibili", end="")
        if sc_agg["circuit"]:
            print(f" ({sc_agg['circuit']} circuit open)", end="")
        print()
        top4 = list(sc_agg["formats"].items())[:4]
        if top4:
            print(f"  - Formati: {', '.join(f'{k}:{v}' for k, v in top4)}")
        if sc_agg["with_preview_count"]:
            print(
                f"  - Preview CSV: {sc_agg['with_preview_count']}/{sc_agg['total']}, "
                f"PAQA medio: {sc_agg['paqa_avg']:.0f}/100"
            )
        if sc_agg["no_gran"]:
            print(f"  - Needs review (granularità): {sc_agg['no_gran']}/{sc_agg['total']}")
        if sc_agg["circuit"]:
            print(f"  - Circuit open: {sc_agg['circuit']}")

    # Tempi
    print("\n### Tempi di esecuzione")
    for fase in (
        "RADAR",
        "INVENTORY",
        "SOURCE-CHECK",
    ):
        v = timing.get(fase, "?")
        if not isinstance(v, str):
            print(f"- **{fase}**: {v:.1f}s")
    if isinstance(timing.get("TOTALE"), float):
        print(f"- **Totale**: {timing['TOTALE']:.1f}s")

    print(
        f"\n_Report generato da DataCivicLab — run_source.py il {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
    )


def main() -> int:
    import argparse
    import json
    import time as _time

    parser = argparse.ArgumentParser(description="End-to-end per una fonte")
    parser.add_argument("source", help="source_id dalla registry")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-radar", action="store_true")
    parser.add_argument("--no-inventory", action="store_true")
    parser.add_argument("--no-sourcecheck", action="store_true")
    parser.add_argument(
        "--markdown", action="store_true", help="Output in Markdown (per allegati FOIA)"
    )
    parser.add_argument("--report", action="store_true", help="Produce source report JSON")
    parser.add_argument(
        "--report-dir",
        default=".",
        help="Directory per il report JSON (default: corrente)",
    )
    args = parser.parse_args()

    reg = load_registry()
    if args.source not in reg:
        print(f"❌ Fonte '{args.source}' non trovata nella registry")
        return 1

    cfg = reg[args.source]
    print(f"\n{'=' * 55}")
    print(f"  {args.source}  ({cfg.get('protocol', '?')})")
    print(f"{'=' * 55}\n")

    timing: dict[str, float | str] = {}
    t_start = _time.time()

    # 1. RADAR
    radar_result: dict | None = None
    radar_str = "?"
    if not args.no_radar:
        t0 = _time.time()
        radar_result = _radar(args.source, cfg)
        timing["RADAR"] = round(_time.time() - t0, 1)
        radar_str = f"{radar_result['status']} (HTTP {radar_result['http_code']})"
        if radar_result.get("note"):
            radar_str += f" — {radar_result['note']}"
    else:
        timing["RADAR"] = "skip"

    # 2. INVENTORY
    rows: list[dict] = []
    captured_at: str | None = None
    if not args.no_inventory:
        t0 = _time.time()
        rows, captured_at = _inventory(args.source, cfg)  # type: ignore[assignment]
        timing["INVENTORY"] = round(_time.time() - t0, 1)
    else:
        timing["INVENTORY"] = "skip"

    # 3. SOURCE-CHECK
    results: list[dict] = []
    if not args.no_sourcecheck:
        t0 = _time.time()
        results = _source_check(args.source, cfg, rows)
        timing["SOURCE-CHECK"] = round(_time.time() - t0, 1)
    else:
        timing["SOURCE-CHECK"] = "skip"

    timing["TOTALE"] = round(_time.time() - t_start, 1)

    if args.report:
        report = build_report(
            args.source,
            cfg,
            radar_result,
            rows,
            captured_at,
            results,
        )
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"source_report_{args.source}.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\n📄 Report JSON salvato: {report_path}")

    if args.markdown:
        _report_markdown(args.source, cfg, radar_str, rows, results, timing)
    else:
        # Riepilogo tempi
        print(f"\n{'─' * 50}")
        print("  ⏱  RIEPILOGO TEMPI")
        print(f"{'─' * 50}")
        for fase in (
            "RADAR",
            "INVENTORY",
            "SOURCE-CHECK",
        ):
            v = timing.get(fase, "?")
            if isinstance(v, str):
                print(f"    {fase:<15} {v}")
            else:
                c = "🟢" if v < 10 else "🟡" if v < 60 else "🔴"
                print(f"    {fase:<15} {v:>6.1f}s  {c}")
        print(f"    {'─' * 15}")
        print(f"    {'TOTALE':<15} {timing['TOTALE']:>6.1f}s")
        print(f"\n✔  Fine — {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
