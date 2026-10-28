"""Scoring dei formati — primitiva condivisa del motore.

Unico punto di definizione: usato dal collector CKAN (``_best_resource_url``)
e dai validatori item-level (``collectors/_validate_base.py``).

Stava in ``scripts/_constants.py`` (modulo del centrale): il motore lo
importava dal centrale e, per transitività, tirava dentro ``so_mcp``.
"""

from __future__ import annotations

FORMAT_PRIORITY: dict[str, int] = {
    "csv": 10,
    "tsv": 10,
    "json": 9,
    "parquet": 8,
    "xml": 7,
    "xlsx": 6,
    "xls": 5,
    "ods": 4,
    "zip": 3,
    "ttl": 2,
    "rdf": 2,
    "pdf": 1,
}

FORMAT_CSV_KEYWORDS = {"csv", "tsv"}


def format_score(fmt: str | float | None) -> int:
    """Score format: piu' alto = piu' facile da pipeline."""
    if fmt is None or not isinstance(fmt, str):
        return 0
    key = fmt.strip().lower()
    if key in FORMAT_PRIORITY:
        return FORMAT_PRIORITY[key]
    if any(kw in key for kw in FORMAT_CSV_KEYWORDS):
        return 10
    if "json" in key:
        return 9
    if "xml" in key:
        return 7
    if "zip" in key:
        return 3
    if "ttl" in key or "rdf" in key:
        return 2
    return 1
