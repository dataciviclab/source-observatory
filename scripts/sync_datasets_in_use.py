"""Sync ``datasets_in_use`` in ``sources_registry.yaml`` from ACB's topic index.

ACB (``agent-context-builder``) pubblica ogni 6 ore il ``topic_index.json``
sul branch ``context``: è il registry merged di tutti i repo del Lab, con la
mappa ``source_id -> [dataset]``. Questa è la fonte di verità dell'uso reale:
DI contiene solo i candidate, non tutti i dataset pubblicati.

Il comando resta nel workflow daily ``radar.yml``: una GET pubblica, nessun
token, nessuna dipendenza pesante. Se ACB non è raggiungibile il registry
resta invariato e il comando esce con errore (il workflow può continuare a
committare lo stato del radar).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from lab_connectors.http import HttpClient

from scripts._constants import REGISTRY_PATH, load_registry, save_registry

ACB_TOPIC_INDEX_URL = (
    "https://raw.githubusercontent.com/dataciviclab/agent-context-builder/context/topic_index.json"
)
DEFAULT_TIMEOUT = 30
USER_AGENT = "DataCivicLab-SourceObservatory/1.0"

# Contratto ACB: il topic index è un artifact generato, non una release.
# Se cambia forma ci fermiamo prima di scrivere un registry sbagliato.
EXPECTED_SCHEMA_VERSION = 7
MIN_EXPECTED_LINKS = 50
MAX_LINK_DROP_PCT = 20.0


class UsageDropError(RuntimeError):
    """Il payload ACB sembra parziale: il registry non viene scritto."""


def fetch_topic_index(
    url: str = ACB_TOPIC_INDEX_URL,
    timeout: int = DEFAULT_TIMEOUT,
    client: Any | None = None,
) -> dict[str, Any]:
    """Scarica e valida il topic index ACB.

    ``client`` è iniettabile nei test; in produzione usa ``HttpClient``.
    """
    http = client or HttpClient(timeout=timeout, user_agent=USER_AGENT)
    result = http.get(url, allow_redirects=True)
    if not result.is_ok or result.response is None:
        raise RuntimeError(f"ACB fetch failed for {url}: {result.err}")
    try:
        payload = result.response.json()
    except ValueError as exc:
        raise ValueError(f"ACB topic index is not valid JSON: {url}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"ACB topic index must be a JSON object: {url}")
    if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise ValueError(
            "ACB topic index schema_version "
            f"{payload.get('schema_version')!r} != expected {EXPECTED_SCHEMA_VERSION}: {url}"
        )
    if not isinstance(payload.get("datasets"), dict):
        raise ValueError(f"ACB topic index missing 'datasets' mapping: {url}")
    return payload


def group_by_source_id(topic_index: dict[str, Any]) -> dict[str, list[str]]:
    """Raggruppa gli slug dei dataset per ``source_id``.

    Legge la forma ACB ``{"datasets": {source_id: [{slug, ...}, ...]}}`` e
    restituisce ``{source_id: [slug, ...]}`` ordinato. Le card senza slug
    valido vengono ignorate; una fonte senza dataset non compare nel risultato.
    """
    datasets = topic_index.get("datasets")
    if not isinstance(datasets, dict):
        raise ValueError("topic_index['datasets'] must be an object")

    groups: dict[str, list[str]] = {}
    for source_id, cards in datasets.items():
        if not isinstance(source_id, str) or not source_id:
            continue
        if not isinstance(cards, list):
            continue
        slugs = {
            str(card["slug"])
            for card in cards
            if isinstance(card, dict) and isinstance(card.get("slug"), str) and card["slug"]
        }
        if slugs:
            groups[source_id] = sorted(slugs)
    return groups


def update_registry(
    registry_path: Path,
    source_groups: dict[str, list[str]],
    *,
    dry_run: bool = False,
    allow_drop: bool = False,
) -> int:
    """Aggiorna ``datasets_in_use`` nel registry.

    - aggiorna solo le fonti presenti nel registry;
    - una fonte senza dataset in ACB riceve una lista vuota;
    - le fonti ACB non presenti nel registry vengono saltate e loggate;
    - ``dry_run`` mostra il diff senza scrivere;
    - ``allow_drop`` autorizza esplicitamente rimozioni di dataset/fonti.

    Guardia anti-wipe: un payload ACB parziale è uno stato previsto (un repo
    può mancare dal merge). Prima di scrivere, il default rifiuta di:

    - svuotare una fonte che prima aveva dataset;
    - perdere più del 20% dei link totali;
    - scendere sotto i 50 link quando il registry ne aveva almeno 50.

    In quei casi solleva ``UsageDropError`` e non tocca il registry.
    """
    registry = load_registry(registry_path)

    old_lists: dict[str, list[str]] = {}
    new_lists: dict[str, list[str]] = {}
    for source_id in registry:
        old_raw = registry[source_id].get("datasets_in_use") or []
        old_lists[source_id] = old_raw if isinstance(old_raw, list) else []
        new_lists[source_id] = sorted(source_groups.get(source_id, []))

    old_total = sum(len(slugs) for slugs in old_lists.values())
    new_total = sum(len(slugs) for slugs in new_lists.values())
    emptied = [
        source_id
        for source_id in sorted(registry)
        if old_lists[source_id] and not new_lists[source_id]
    ]
    drop_pct = ((old_total - new_total) / old_total * 100) if old_total else 0.0

    if not allow_drop:
        if emptied:
            raise UsageDropError(
                f"{len(emptied)} fonti non vuote diventerebbero vuote: {', '.join(emptied)}"
            )
        if old_total and drop_pct > MAX_LINK_DROP_PCT:
            raise UsageDropError(
                f"link in calo del {drop_pct:.1f}% ({old_total} -> {new_total}), "
                f"soglia {MAX_LINK_DROP_PCT:.0f}%"
            )
        if old_total >= MIN_EXPECTED_LINKS and new_total < MIN_EXPECTED_LINKS:
            raise UsageDropError(
                f"link sotto la soglia minima ({new_total} < {MIN_EXPECTED_LINKS}), "
                f"prima erano {old_total}"
            )

    updated = 0
    for source_id in sorted(registry):
        old_list = old_lists[source_id]
        new_list = new_lists[source_id]

        if old_list != new_list:
            print(f"  UPDATE {source_id}: {old_list} -> {new_list}")
            registry[source_id]["datasets_in_use"] = new_list
            updated += 1
        else:
            print(f"  OK     {source_id}: {new_list}")

    unknown = sorted(set(source_groups) - set(registry))
    for source_id in unknown:
        print(f"  SKIP   {source_id}: non presente in {registry_path.name}")

    empty = [source_id for source_id in sorted(registry) if not source_groups.get(source_id)]
    if empty:
        print(f"  INFO   {len(empty)} fonti senza dataset in ACB: {', '.join(empty)}")

    if not dry_run:
        save_registry(registry_path, registry)
    return updated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincronizza datasets_in_use dal topic_index di agent-context-builder."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=REGISTRY_PATH,
        help=f"Registry YAML da aggiornare (default: {REGISTRY_PATH})",
    )
    parser.add_argument(
        "--url",
        default=ACB_TOPIC_INDEX_URL,
        help="URL del topic_index ACB.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout HTTP in secondi (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra il diff senza scrivere il registry.",
    )
    parser.add_argument(
        "--allow-drop",
        action="store_true",
        help="Autorizza esplicitamente la rimozione di dataset/fonti (bypassa la guardia anti-wipe).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        topic_index = fetch_topic_index(url=args.url, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 — errore di rete/parsing: registry invariato
        print(f"ERROR: impossibile leggere ACB topic index: {exc}", file=sys.stderr)
        return 1

    generated_at = topic_index.get("generated_at") or "?"
    schema_version = topic_index.get("schema_version") or "?"
    groups = group_by_source_id(topic_index)
    n_datasets = sum(len(slugs) for slugs in groups.values())

    print(f"ACB topic_index: schema={schema_version} generated_at={generated_at}")
    print(f"Source groups: {len(groups)} — dataset: {n_datasets}")
    print(f"Registry: {args.registry}")

    try:
        updated = update_registry(
            args.registry,
            groups,
            dry_run=args.dry_run,
            allow_drop=args.allow_drop,
        )
    except UsageDropError as exc:
        print(f"ERROR: guardia anti-wipe: {exc}", file=sys.stderr)
        print(
            "Registry invariato. Usa --allow-drop per una rimozione intenzionale.", file=sys.stderr
        )
        return 2

    if args.dry_run:
        print(f"\nDry-run: {updated} fonte/i da aggiornare (nessuna scrittura).")
    elif updated:
        print(f"\nUpdated {updated} source(s) in {args.registry.name}")
    else:
        print("\nNo changes needed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
