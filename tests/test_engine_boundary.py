"""Ratchet del confine del motore.

Il motore del Source Observatory (``scripts/engine``, ``scripts/collectors``,
``scripts/catalog``, ``scripts/pipeline``) è ciò che un repo dati installa per
generare il proprio ``registry/catalog.json``. Deve restare autonomo dal
centrale: prima di questo confine il motore importava ``scripts.radar_check``,
``scripts.source_report``, ``scripts._constants`` (che a sua volta tirava
dentro ``so_mcp``).

Questo test è il gate. Due regole:

1. **Confine dei moduli** — nel motore si importa solo da questi prefissi:
   ``scripts.engine``, ``scripts.collectors``, ``scripts.catalog``,
   ``scripts.pipeline``. Qualsiasi altro modulo ``scripts.*`` è centrale.
   Vale anche per ``so_mcp``.
2. **Peso delle dipendenze** — niente ``duckdb``, ``pandas``, ``pyarrow``,
   ``ddgs``, ``mcp``. Le eccezioni note sono elencate e possono solo
   **diminuire** (il confronto è di sottoinsieme): toglierne una passa,
   aggiungerne una fallisce.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Directory del motore (relative alla root del repo).
_ENGINE_DIRS = (
    "scripts/engine",
    "scripts/collectors",
    "scripts/catalog",
    "scripts/pipeline",
)

# Prefissi di import ammessi per i moduli interni del Lab (nomi di modulo).
_ALLOWED_SCRIPT_PREFIXES = (
    "scripts.engine",
    "scripts.collectors",
    "scripts.catalog",
    "scripts.pipeline",
)

# Librerie pesanti che il motore non deve importare.
_HEAVY_MODULES = ("duckdb", "pandas", "pyarrow", "ddgs", "mcp")

# Eccezioni note, da eliminare con B4/B5 del piano di alleggerimento.
# `assert found <= allowed` → togliere un'eccezione passa, aggiungerne una no.
_ALLOWED_HEAVY: set[tuple[str, str]] = {
    # build.py scrive il parquet di inventario locale (out/so/, gitignored).
    ("scripts/catalog/build.py", "pandas"),
    # run_pipeline.py fa il merge item-level (opzionale: skip-validate/radar-only).
    ("scripts/pipeline/run_pipeline.py", "pandas"),
    ("scripts/pipeline/_merge_utils.py", "pandas"),
    # _validate_base.py: duckdb importato lazy dentro la funzione di validate.
    ("scripts/collectors/_validate_base.py", "duckdb"),
}


def _engine_files() -> list[Path]:
    files: list[Path] = []
    for rel in _ENGINE_DIRS:
        files.extend(sorted((_REPO_ROOT / rel).rglob("*.py")))
    return files


def _imported_modules(path: Path) -> set[str]:
    """Nomi dei moduli importati nel file (inclusi gli import dentro le funzioni)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def test_engine_does_not_import_central_modules() -> None:
    """Il motore non importa moduli del centrale (né `so_mcp`)."""
    violations: list[str] = []
    for path in _engine_files():
        for module in sorted(_imported_modules(path)):
            if module == "so_mcp" or module.startswith("so_mcp."):
                violations.append(f"{_rel(path)} → {module}")
                continue
            if not module.startswith("scripts."):
                continue
            if not any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in _ALLOWED_SCRIPT_PREFIXES
            ):
                violations.append(f"{_rel(path)} → {module}")

    assert not violations, (
        "Il motore importa moduli fuori dal proprio confine.\n"
        "Sposta la primitiva condivisa in `scripts/engine/` e falla importare "
        "al centrale (direzione: centrale → motore).\nViolazioni:\n  " + "\n  ".join(violations)
    )


def test_engine_heavy_imports_only_known_exceptions() -> None:
    """Le librerie pesanti nel motore sono solo le eccezioni note (che possono solo calare)."""
    found: set[tuple[str, str]] = set()
    for path in _engine_files():
        for module in _imported_modules(path):
            top = module.split(".")[0]
            if top in _HEAVY_MODULES:
                found.add((_rel(path), top))

    unexpected = found - _ALLOWED_HEAVY
    assert not unexpected, (
        "Nuove dipendenze pesanti nel motore.\n"
        "Il motore deve restare installabile con poche dipendenze: usa lo "
        "standard library o sposta la logica nel centrale.\nNuove:\n  "
        + "\n  ".join(f"{f} → {m}" for f, m in sorted(unexpected))
    )
