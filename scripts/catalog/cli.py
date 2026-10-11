"""CLI ``so-catalog``: genera registry/catalog.json per un repo dati.

Uso::

    so-catalog                          # repo corrente
    so-catalog --repo-root ../eurostat  # repo esplicito
    so-catalog --skip-validate          # probe + inventory, niente HTTP item-level
    so-catalog --workers 8              # parallellismo validate
    so-catalog --max-groups 20          # limita i gruppi (testing)
    so-catalog --dry-run                # calcola senza scrivere

Exit codes:
    0  ok
    2  config error (pyproject/ [tool.observatory] non valido)
    3  catalog non valido contro lo schema
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.catalog.config import ObservatoryConfigError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="so-catalog",
        description="Build registry/catalog.json for a data repo from [tool.observatory].",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Data repo root (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for item-level HTTP probes (default: 1)",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip item-level validation (probe + inventory only)",
    )
    parser.add_argument(
        "--max-groups",
        type=int,
        help="Max dataset groups to validate (testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build in memory only, do not write catalog.json or parquet",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import jsonschema

    from scripts.catalog.build import build_catalog

    args = parse_args(argv)

    try:
        catalog = build_catalog(
            repo_root=args.repo_root,
            workers=args.workers,
            skip_validate=args.skip_validate,
            max_groups=args.max_groups,
            write=not args.dry_run,
        )
    except ObservatoryConfigError as exc:
        print(f"❌ Config error: {exc}", file=sys.stderr)
        return 2
    except jsonschema.ValidationError as exc:
        print(f"❌ Catalog schema violation: {exc.message}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — exit code strutturato per CI
        import traceback

        traceback.print_exc()
        print(f"❌ Catalog build failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"🏁 dry-run ok: verdict={catalog['operational_verdict']['label']} (nothing written)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
