"""Sync datasets_in_use in sources_registry.yaml from DI's registry.json.

Reads dataset-incubator/registry/registry.json (fusion), groups datasets by
source_id, and updates sources_registry.yaml so that each source lists its
DI candidate slugs.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen

from ruamel.yaml import YAML

from scripts._constants import REGISTRY_PATH

DI_REGISTRY_URL = (
    "https://raw.githubusercontent.com/dataciviclab/dataset-incubator/main/registry/registry.json"
)


def fetch_di_registry() -> list[dict]:
    print(f"Fetching {DI_REGISTRY_URL}...")
    with urlopen(DI_REGISTRY_URL) as resp:
        registry = json.loads(resp.read().decode())
    return registry["datasets"]


def group_by_source_id(datasets: list[dict]) -> dict[str, list[str]]:
    """Group DI dataset slugs by source_id.

    Returns {source_id: [slug1, slug2, ...]} sorted by slug.
    """
    groups: dict[str, list[str]] = {}
    for ds in datasets:
        sid = ds.get("source_id")
        if not sid:
            continue
        groups.setdefault(sid, []).append(ds["slug"])
    # Sort slugs within each group
    for sid in groups:
        groups[sid].sort()
    return groups


def update_registry(registry_path: Path, source_groups: dict[str, list[str]]) -> int:
    yaml = YAML(typ="rt")  # round-trip preserve order
    yaml.indent(mapping=2, sequence=4, offset=2)

    with open(registry_path, encoding="utf-8") as f:
        registry = yaml.load(f) or {}

    updated = 0
    for source_id, di_slugs in sorted(source_groups.items()):
        if source_id not in registry:
            print(f"  SKIP {source_id}: not in sources_registry.yaml")
            continue

        old_list = registry[source_id].get("datasets_in_use", [])
        new_list = sorted(di_slugs)

        if old_list != new_list:
            registry[source_id]["datasets_in_use"] = new_list
            print(f"  UPDATE {source_id}: {old_list} -> {new_list}")
            updated += 1
        else:
            print(f"  OK    {source_id}: {new_list}")

    # Write back preserving order
    with open(registry_path, "w", encoding="utf-8") as f:
        yaml.dump(registry, f)

    return updated


def main() -> int:
    datasets = fetch_di_registry()
    print(f"DI registry: {len(datasets)} datasets")

    groups = group_by_source_id(datasets)
    print(f"Source groups: {len(groups)}")

    updated = update_registry(REGISTRY_PATH, groups)

    if updated:
        print(f"\nUpdated {updated} source(s) in {REGISTRY_PATH.name}")
    else:
        print("\nNo changes needed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
