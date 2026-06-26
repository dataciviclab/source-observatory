#!/usr/bin/env python3
"""
Run end-to-end per una fonte: radar → inventory → source-check → health score.

Utilizzo:
    python scripts/run_source.py mit_opendata
    python scripts/run_source.py dati_camera --verbose
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from _constants import load_registry  # noqa: E402
from collectors import dispatch  # noqa: E402

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


def _inventory(source_id: str, cfg: dict) -> list[dict]:
    """2. INVENTORY — raccoglie dataset/item della fonte."""
    import time as _time

    _heading(f"INVENTORY — {source_id}  ({cfg.get('protocol', '?')})")

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = _time.time()
    try:
        res = dispatch(source_id, cfg, captured_at)
    except Exception as e:
        print(f"  ❌ ERRORE: {e}")
        return []
    elapsed = _time.time() - t0

    rows = res.rows
    print(f"  Item: {len(rows)}  [{elapsed:.1f}s]")

    if res.warning:
        print(f"  ⚠️  {res.warning}")

    if res.ssl_fallback_used:
        print("  ⚠️  SSL fallback durante inventory")

    # Aggregazione da rows (sempre disponibile, indipendente dal collector)
    if rows:
        fmt_dist = Counter((r.get("format") or "?").upper() for r in rows)
        print(f"  Formati: {', '.join(f'{k}:{v}' for k, v in sorted(fmt_dist.items()))}")

        years = []
        for r in rows:
            for k in ("year_min", "year_signal", "issued"):
                v = r.get(k)
                if v is not None:
                    try:
                        years.append(int(v))
                    except (ValueError, TypeError):
                        pass
        if years:
            print(f"  Anni: {min(years)}–{max(years)}")

        orgs = {r.get("organization") for r in rows if r.get("organization")}
        if orgs and len(orgs) <= 5:
            print(f"  Organizzazioni: {', '.join(sorted(orgs))}")
        elif orgs:
            print(f"  Organizzazioni: {len(orgs)}")

    return rows


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

    total = len(results)
    reachable = sum(1 for r in results if r.get("reachable"))
    circuit = sum(1 for r in results if r.get("check_notes") == "circuit_open")
    content_mismatch = sum(
        1 for r in results if (r.get("check_notes") or "").startswith("content_mismatch")
    )
    formats = Counter(r.get("resource_format") or "?" for r in results)
    statuses = Counter(str(r.get("http_status", "?")) for r in results)

    print(f"  Totali: {total} item")
    print(
        f"  Raggiungibili: {_color('GREEN', str(reachable))}/{total}  "
        f"({round(reachable / total * 100, 1)}%)"
    )
    if circuit:
        print(f"  ⚠️  Circuit open: {circuit}")
    if content_mismatch:
        print(f"  ⚠️  Content mismatch: {content_mismatch}")
    if formats:
        print(f"  Formati: {', '.join(f'{k}:{v}' for k, v in formats.most_common(5))}")
    if len(statuses) > 1:
        non_ok = {k: v for k, v in statuses.most_common() if k not in ("200", "?")}
        if non_ok:
            print(f"  ⚠️  HTTP non-200: {dict(non_ok)}")

    # Preview (profilazione reale col toolkit)
    with_preview = [r for r in results if r.get("paqa_score") is not None]
    if with_preview:
        avg = sum(r["paqa_score"] for r in with_preview if r["paqa_score"] is not None) / len(
            with_preview
        )
        p_verdicts = Counter(r.get("paqa_verdict") or "?" for r in with_preview)
        print(f"  Preview CSV: {len(with_preview)}/{total}")
        print(
            f"  PAQA medio: {avg:.0f}/100  ({', '.join(f'{k}:{v}' for k, v in p_verdicts.most_common())})"
        )

    # Needs review: granularità non determinata e/o anno minimo mancante
    no_gran = sum(1 for r in results if r.get("granularity") in (None, "", "non_determinato"))
    no_year = sum(
        r.get("year_min") is None
        or (isinstance(r.get("year_min"), float) and math.isnan(r.get("year_min")))  # type: ignore[arg-type]
        for r in results
    )
    if no_gran or no_year:
        flags = []
        if no_gran:
            flags.append(f"granularità:{no_gran}/{total}")
        if no_year:
            flags.append(f"anni:{no_year}/{total}")
        print(f"  ⚠️  Needs review: {', '.join(flags)}")

    # Metriche probe: media per item (con workers attivi)
    has_no_url = sum(1 for r in results if not r.get("url_checked"))
    if has_no_url:
        print(f"  ℹ️  Senza URL: {has_no_url}/{total}")
    print(f"  Worker: {max_workers}")

    problematic = [r for r in results if not r.get("reachable")]
    if problematic:
        print("  🔴 Esempi non raggiungibili:")
        for r in problematic[:3]:
            url = (r.get("url_checked") or "N/A")[:80]
            print(f"    {r.get('http_status')} – {r.get('check_notes')} – {url}")

    return results


def _health_score(
    source_id: str,
    _cfg: dict,
    rows: list[dict] | None = None,
    results: list[dict] | None = None,
) -> dict | None:
    """4. HEALTH SCORE — calcola e mostra il punteggio finale.

    Usa rows (inventory) e results (source-check) in memoria per evitare
    fake signals da parquet non aggiornato.
    """
    _heading(f"HEALTH SCORE — {source_id}")
    from scripts.build_compliance_scores import (
        _build_inventory_stats,
        _build_license_stats,
        _build_source_check_stats,
        build_scores,
    )

    reg = load_registry()
    radar_path = REPO_ROOT / "data" / "radar" / "radar_summary.json"
    signals_path = REPO_ROOT / "data" / "catalog" / "catalog_signals.json"

    radar_sources: list = []
    if radar_path.exists():
        radar_sources = __import__("json").loads(radar_path.read_text()).get("sources", [])

    signals_data: dict | None = None
    if signals_path.exists():
        signals_data = __import__("json").loads(signals_path.read_text())

    # Costruisce stats in memoria invece di leggere da parquet
    inventory_stats = _build_inventory_stats(source_id, rows) if rows else None
    license_stats = _build_license_stats(source_id, rows) if rows else None
    source_check_stats = _build_source_check_stats(source_id, results) if results else None

    result = build_scores(
        {source_id: reg.get(source_id, {})},
        [s for s in radar_sources if s["id"] == source_id],
        signals_data,
        inventory_stats=inventory_stats,
        license_stats=license_stats,
        source_check_stats=source_check_stats,
    )
    entry = result["scores"][0] if result["scores"] else None
    if not entry:
        print("  Nessun health score disponibile")
        return None

    c = _color(entry["livello"], entry["livello"].upper())
    print(f"  Score: {entry['totale']}/100  ({c})")
    print(f"  Azione: {entry['azione_raccomandata']}")
    if entry.get("flag_urgenza"):
        print(f"  Flag: {', '.join(entry['flag_urgenza'])}")

    print("\n  Assi:")
    for k, v in entry["assi"].items():
        assi_color = _color(
            "GREEN" if v["score"] >= 70 else "YELLOW" if v["score"] >= 55 else "RED",
            f"{v['score']:.0f}",
        )
        src = v["fonte"]
        print(f"    {k:30s} {assi_color:>5s}  ({src})")
    return entry


# ── MAIN ─────────────────────────────────────────────────────────────────────


def _report_markdown(
    source_id: str,
    cfg: dict,
    radar: str,
    rows: list[dict],
    results: list[dict],
    health_entry: dict | None,
    timing: dict,
) -> None:
    """Stampa report Markdown della fonte (per allegati FOIA)."""
    protocol = cfg.get("protocol", "?")
    print(f"\n## Report fonte: {source_id}")
    print(f"- **Protocollo**: {protocol}")
    print(f"- **RADAR**: {radar}")

    if rows:
        print(f"- **Inventory**: {len(rows)} dataset")
        from collections import Counter

        fmt_dist = Counter((r.get("format") or "?").upper() for r in rows)
        fmt_str = ", ".join(f"{k}:{v}" for k, v in sorted(fmt_dist.items()) if k != "?")
        if fmt_str:
            print(f"- **Formati (inventory)**: {fmt_str}")

    if results:
        total = len(results)
        reachable = sum(1 for r in results if r.get("reachable"))
        circuit = sum(1 for r in results if r.get("check_notes") == "circuit_open")
        with_preview = [r for r in results if r.get("paqa_score") is not None]
        formats = Counter(r.get("resource_format") or "?" for r in results)
        no_gran = sum(1 for r in results if r.get("granularity") in (None, "", "non_determinato"))

        print(f"- **Source-check**: {reachable}/{total} raggiungibili", end="")
        if circuit:
            print(f" ({circuit} circuit open)", end="")
        print()
        print(f"  - Formati: {', '.join(f'{k}:{v}' for k, v in formats.most_common(4))}")
        if with_preview:
            avg = sum(r["paqa_score"] for r in with_preview if r["paqa_score"] is not None) / len(
                with_preview
            )
            print(f"  - Preview CSV: {len(with_preview)}/{total}, PAQA medio: {avg:.0f}/100")
        if no_gran:
            print(f"  - Needs review (granularità): {no_gran}/{total}")
        if circuit:
            print(f"  - Circuit open: {circuit}")

    if health_entry:
        print(f"\n### Health score: {health_entry['totale']}/100 ({health_entry['livello']})")
        print(f"- **Azione**: {health_entry['azione_raccomandata']}")
        max_assi = len(health_entry.get("assi", {}))
        print(f"- **Assi computed**: {health_entry.get('assi_computed', 0)}/{max_assi}")
        print()
        print("| Asse | Score | Fonte |")
        print("|---|---|---|")
        for k, v in health_entry.get("assi", {}).items():
            print(f"| {k} | {v['score']:.0f} | {v['fonte']} |")

    # Tempi
    print("\n### Tempi di esecuzione")
    for fase in ("RADAR", "INVENTORY", "SOURCE-CHECK", "HEALTH"):
        v = timing.get(fase, "?")
        if not isinstance(v, str):
            print(f"- **{fase}**: {v:.1f}s")
    if isinstance(timing.get("TOTALE"), float):
        print(f"- **Totale**: {timing['TOTALE']:.1f}s")

    if health_entry and health_entry.get("flag_urgenza"):
        print(f"\n⚠️ **Flag urgenza**: {', '.join(health_entry['flag_urgenza'])}")

    print(
        f"\n_Report generato da DataCivicLab — run_source.py il {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
    )


def main() -> int:
    import argparse
    import time as _time

    parser = argparse.ArgumentParser(description="End-to-end per una fonte")
    parser.add_argument("source", help="source_id dalla registry")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-radar", action="store_true")
    parser.add_argument("--no-inventory", action="store_true")
    parser.add_argument("--no-sourcecheck", action="store_true")
    parser.add_argument("--no-health", action="store_true")
    parser.add_argument(
        "--markdown", action="store_true", help="Output in Markdown (per allegati FOIA)"
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
    rows = []
    if not args.no_inventory:
        t0 = _time.time()
        rows = _inventory(args.source, cfg)
        timing["INVENTORY"] = round(_time.time() - t0, 1)
    else:
        timing["INVENTORY"] = "skip"

    # 3. SOURCE-CHECK
    results = []
    if not args.no_sourcecheck:
        t0 = _time.time()
        results = _source_check(args.source, cfg, rows)
        timing["SOURCE-CHECK"] = round(_time.time() - t0, 1)
    else:
        timing["SOURCE-CHECK"] = "skip"

    # 4. HEALTH SCORE
    health_entry = None
    if not args.no_health:
        t0 = _time.time()
        health_entry = _health_score(args.source, cfg, rows=rows, results=results)
        timing["HEALTH"] = round(_time.time() - t0, 1)
    else:
        timing["HEALTH"] = "skip"

    timing["TOTALE"] = round(_time.time() - t_start, 1)

    if args.markdown:
        _report_markdown(args.source, cfg, radar_str, rows, results, health_entry, timing)
    else:
        # Riepilogo tempi
        print(f"\n{'─' * 50}")
        print("  ⏱  RIEPILOGO TEMPI")
        print(f"{'─' * 50}")
        for fase in ("RADAR", "INVENTORY", "SOURCE-CHECK", "HEALTH"):
            v = timing[fase]
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
