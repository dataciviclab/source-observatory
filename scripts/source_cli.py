"""CLI comandi singola-fonte — probe, inventory, report, status.

Equivalente CLI dei tool MCP per umani e script senza MCP:

  so-source probe <id>       Probe HTTP di una fonte → GREEN/YELLOW/RED
  so-source inventory <id>   Inventario della fonte → conteggi, formati
  so-source report <id>      Source report completo (legge dal catalog per-repo
                             o dal registry centrale)
  so-source status           Riepilogo: fonti, radar, verdict

Le fonti si risolvono da:
  1. [tool.observatory] del pyproject nel CWD (o --repo-root)
  2. sources_registry.yaml centrale (fallback)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ── Risoluzione fonte ─────────────────────────────────────────────────────────


def _load_from_pyproject(repo_root: Path) -> dict[str, Any] | None:
    """Prova a caricare la config da [tool.observatory] del pyproject locale."""
    try:
        from scripts.catalog.config import load_observatory_config

        return load_observatory_config(repo_root)
    except Exception:
        return None


def _load_from_registry(source_id: str) -> dict[str, Any] | None:
    """Fallback: carica dal sources_registry.yaml centrale."""
    try:
        from scripts._constants import load_registry

        reg = load_registry()
        entry = reg.get(source_id)
        if entry:
            return {**entry, "source_id": source_id}
    except Exception:
        pass
    return None


def _resolve_source(source_id: str, repo_root: Path | None) -> dict[str, Any] | None:
    if repo_root:
        cfg = _load_from_pyproject(repo_root)
        if cfg and cfg.get("source_id") == source_id:
            return cfg
    # Cerca nel CWD
    cfg = _load_from_pyproject(Path.cwd())
    if cfg and cfg.get("source_id") == source_id:
        return cfg
    return _load_from_registry(source_id)


# ── so-probe ─────────────────────────────────────────────────────────────────


def cmd_probe(args: argparse.Namespace) -> int:
    cfg = _resolve_source(args.source_id, args.repo_root)
    if not cfg:
        print(
            f"❌ Fonte '{args.source_id}' non trovata (pyproject locale né registry centrale)",
            file=sys.stderr,
        )
        return 2

    from scripts.radar_check import probe_url

    url = cfg["base_url"]
    print(f"🔭 probing {args.source_id}: {url}")
    result = probe_url(url)
    print(f"  status:   {result.status}")
    print(f"  http:     {result.http_code}")
    if result.note:
        print(f"  note:     {result.note}")
    if result.ssl_fallback_used:
        print("  ssl:      fallback used")
    if result.final_url and result.final_url != url:
        print(f"  redirect: {result.final_url}")

    return 0 if result.status == "GREEN" else 1


# ── so-inventory ─────────────────────────────────────────────────────────────


def cmd_inventory(args: argparse.Namespace) -> int:
    cfg = _resolve_source(args.source_id, args.repo_root)
    if not cfg:
        print(f"❌ Fonte '{args.source_id}' non trovata", file=sys.stderr)
        return 2

    from datetime import datetime, timezone

    from scripts.collectors import dispatch

    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(f"📦 inventory {args.source_id} ({cfg['protocol']})...")
    result = dispatch(args.source_id, cfg, captured_at)
    rows = result.rows

    # Riepilogo
    formats: dict[str, int] = {}
    for r in rows:
        fmt = r.get("format") or "?"
        formats[fmt] = formats.get(fmt, 0) + 1

    print(f"  items:  {len(rows)}")
    print(f"  formati: {dict(sorted(formats.items(), key=lambda x: -x[1]))}")
    if result.warning:
        print(f"  warning: {result.warning}")

    if args.json:
        print(
            json.dumps(
                rows[: args.limit] if args.limit else rows,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    elif args.limit:
        print(f"\n  primi {args.limit} item:")
        for r in rows[: args.limit]:
            print(f"    {r.get('format', '?'):<8} {str(r.get('title') or r.get('item_name'))[:60]}")

    return 0


# ── so-report ────────────────────────────────────────────────────────────────


def cmd_report(args: argparse.Namespace) -> int:
    # 1) Prova il catalog per-repo
    for root in [args.repo_root, Path.cwd()]:
        if root is None:
            continue
        catalog_path = root / "registry" / "catalog.json"
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            if catalog.get("source_id") == args.source_id:
                print(json.dumps(catalog, indent=2, ensure_ascii=False))
                return 0

    # 2) Fallback: report centrale
    reports_dir = Path(__file__).resolve().parents[1] / "data" / "reports" / "source_reports"
    central = reports_dir / f"{args.source_id}.json"
    if central.exists():
        print(central.read_text(encoding="utf-8"))
        return 0

    print(
        f"❌ Nessun report per '{args.source_id}' (né catalog per-repo né centrale)",
        file=sys.stderr,
    )
    return 2


# ── so-status ────────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    # Radar centrale
    from scripts._constants import RADAR_SUMMARY_PATH

    if RADAR_SUMMARY_PATH.exists():
        radar = json.loads(RADAR_SUMMARY_PATH.read_text(encoding="utf-8"))
        sources = radar.get("sources", [])
        by_status: dict[str, int] = {}
        for s in sources:
            st = s.get("status", "?")
            by_status[st] = by_status.get(st, 0) + 1
        print(f"🔭 Radar centrale: {len(sources)} fonti — {dict(sorted(by_status.items()))}")
        red = [s["id"] for s in sources if s.get("status") == "RED"]
        if red:
            print(f"  🔴 RED: {', '.join(red)}")
    else:
        print("🔭 Radar centrale: non disponibile (radar_summary.json assente)")

    # Catalog per-repo nel CWD
    catalog_path = Path.cwd() / "registry" / "catalog.json"
    if catalog_path.exists():
        c = json.loads(catalog_path.read_text(encoding="utf-8"))
        h = c.get("health", {})
        v = c.get("operational_verdict", {})
        sc = c.get("source_check", {})
        print(f"\n📦 Catalog locale: {c.get('source_id')}")
        print(f"  radar:     {h.get('radar_status')} (streak {h.get('streak')})")
        print(f"  inventario: {c.get('inventory', {}).get('total_items')} item")
        print(f"  validate:  {sc.get('reachable')}/{sc.get('total_scored')} reachable")
        print(f"  verdict:   {v.get('label')} {v.get('triggers', [])}")
        probes = c.get("pattern_probes", [])
        if probes:
            avail = sum(1 for p in probes if p.get("available"))
            print(f"  probes:    {avail}/{len(probes)} available")

    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="so-source",
        description="Comandi singola-fonte: probe, inventory, report, status.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="Probe HTTP di una fonte")
    p_probe.add_argument("source_id")
    p_probe.add_argument("--repo-root", type=Path, default=None)
    p_probe.set_defaults(func=cmd_probe)

    p_inv = sub.add_parser("inventory", help="Inventario della fonte")
    p_inv.add_argument("source_id")
    p_inv.add_argument("--repo-root", type=Path, default=None)
    p_inv.add_argument("--json", action="store_true", help="Output JSON")
    p_inv.add_argument("--limit", type=int, default=10, help="Righe in output (default 10)")
    p_inv.set_defaults(func=cmd_inventory)

    p_rep = sub.add_parser("report", help="Source report completo")
    p_rep.add_argument("source_id")
    p_rep.add_argument("--repo-root", type=Path, default=None)
    p_rep.set_defaults(func=cmd_report)

    p_status = sub.add_parser("status", help="Riepilogo stato")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
