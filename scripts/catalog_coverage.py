#!/usr/bin/env python3
"""Diagnostica: quale repo dati del workspace e' copribile da so-catalog.

Combina tre segnali per classificare la FONTE di ogni repo (non il metodo
di ingestion):

  1. ``raw.sources[].type`` nei dataset.yml — ckan/sdmx/sparql = connector
     enumerabile; http_file/script/local_file = accesso diretto
  2. ``source_id`` dei dataset.yml vs il registro SO centrale
  3. URL espliciti nei dataset.yml vs i base_url delle fonti SO

Classi:
  A · fonte enumerabile, copribile 100%   (solo connector enumerabili)
  B · fonte in SO, copertura parziale      (fonte nota + accessi diretti)
  C · fonte non in SO, da verificare      (URL presenti ma non mappati)
  D · opaca / solo locale                 (senza segnali di fonte esterna)

Uso::

    python -m scripts.catalog_coverage --workspace /path/to/workspace
    python -m scripts.catalog_coverage --json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

ENUM_CONNECTORS = frozenset({"ckan", "sdmx", "sparql"})
DIRECT_TYPES = frozenset(
    {"http_file", "http_post_file", "local_file", "unzip_first_csv", "unzip_all", "script"}
)
ENUM_SO_PROTOCOLS = frozenset({"ckan", "sdmx", "sparql", "html"})
SKIP_PREFIXES = (
    "toolkit",
    "lab-connectors",
    ".venv",
    "node_modules",
    "vendors",
    "_local",
    "esperimenti-locali",
    "infra/source-observatory",
    "infra/agent-context-builder",
    "infra/lab-ops",
    "infra/project-template",
    "infra/data-explorer",
    "infra/lab-dashboard",
    "infra/dataset-incubator",
    "infra/dataciviclab",
)


@dataclass
class RepoCoverage:
    repo: str
    path: str
    classification: str
    source_ids: list[str] = field(default_factory=list)
    source_ids_in_so: list[str] = field(default_factory=list)
    source_ids_not_in_so: list[str] = field(default_factory=list)
    ingestion_types: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _load_so_registry(so_repo: Path) -> dict:
    reg_path = so_repo / "data" / "radar" / "sources_registry.yaml"
    if not reg_path.exists():
        return {}
    return yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}


def _analyze_repo(root: Path) -> tuple[set[str], Counter, set[str]]:
    source_ids: set[str] = set()
    types: Counter = Counter()
    urls: set[str] = set()
    for pattern in ("datasets/*/dataset.yml", "candidates/*/dataset.yml", "compose/*/dataset.yml"):
        for yml in root.glob(pattern):
            text = yml.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'(?<![A-Za-z_])source_id:\s*["\']?([A-Za-z0-9_-]+)', text):
                source_ids.add(m.group(1))
            in_raw = False
            for line in text.splitlines():
                if re.match(r"^raw:", line):
                    in_raw = True
                elif re.match(r"^[a-z_]+:", line) and not line.startswith("raw"):
                    in_raw = False
                if in_raw:
                    tm = re.search(r'type:\s*["\']?([a-z_]+)', line)
                    if tm:
                        types[tm.group(1)] += 1
                    for u in re.findall(r'https?://[^\s"\'{}]+', line):
                        urls.add(u.split("?")[0].rstrip("/"))
    source_ids.discard("dataciviclab_composite")
    return source_ids, types, urls


def classify_repo(
    root: Path,
    rel: str,
    source_ids: set[str],
    types: Counter,
    urls: set[str],
    so_registry: dict,
) -> RepoCoverage:
    so_proto = {k: v.get("protocol") for k, v in so_registry.items()}
    in_so = sorted(s for s in source_ids if s in so_proto)
    enum_in_so = [s for s in in_so if so_proto[s] in ENUM_SO_PROTOCOLS]
    not_in_so = sorted(s for s in source_ids if s not in so_proto)

    has_enum_connector = any(t in ENUM_CONNECTORS for t in types)
    has_direct = any(t in DIRECT_TYPES for t in types)
    notes: list[str] = []

    if has_enum_connector and not has_direct:
        cls = "A · fonte enumerabile, copribile 100%"
    elif has_enum_connector or enum_in_so:
        cls = "B · fonte in SO, copertura parziale"
        if has_direct:
            notes.append("accessi diretti oltre alla fonte enumerabile")
    elif not_in_so and urls:
        cls = "C · fonte non in SO, da verificare"
    elif not_in_so:
        cls = "D · opaca / solo locale"
        notes.append("nessun URL fonte nei dataset.yml")
    else:
        cls = "D · opaca / solo locale"

    return RepoCoverage(
        repo=root.name,
        path=rel,
        classification=cls,
        source_ids=sorted(source_ids),
        source_ids_in_so=in_so,
        source_ids_not_in_so=not_in_so,
        ingestion_types=dict(sorted(types.items())),
        notes=notes,
    )


def scan_workspace(workspace: Path, so_repo: Path | None = None) -> list[RepoCoverage]:
    so_repo = so_repo or (workspace / "infra" / "source-observatory")
    so_registry = _load_so_registry(so_repo)
    results: list[RepoCoverage] = []
    for pyproject in sorted(workspace.rglob("pyproject.toml")):
        root = pyproject.parent
        rel = str(root.relative_to(workspace))
        if any(rel.startswith(p) for p in SKIP_PREFIXES):
            continue
        if not any((root / d).is_dir() for d in ("datasets", "candidates", "compose")):
            continue
        source_ids, types, urls = _analyze_repo(root)
        results.append(classify_repo(root, rel, source_ids, types, urls, so_registry))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classifica la copertura so-catalog dei repo dati."
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Root del workspace (default: CWD)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON invece della tabella")
    args = parser.parse_args(argv)

    results = scan_workspace(args.workspace)

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))
        return 0

    by_class = Counter(r.classification for r in results)
    print("=== COPERTURA FONTE (so-catalog) ===")
    for cls, n in sorted(by_class.items()):
        print(f"  {n:>2}  {cls}")
    print(f"\nTotale: {len(results)} repo dati\n")
    print(f"{'repo':<28} {'classe':<44} {'fonti SO':<20} {'fonti non in SO'}")
    print("-" * 120)
    for r in sorted(results, key=lambda x: (x.classification, x.repo)):
        enum = ",".join(r.source_ids_in_so[:3]) + ("…" if len(r.source_ids_in_so) > 3 else "")
        enum = enum or "-"
        not_so = ",".join(r.source_ids_not_in_so[:3]) or "-"
        print(f"{r.repo:<28} {r.classification:<44} {enum:<20} {not_so}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
