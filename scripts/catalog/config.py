"""Loader della config fonte da ``pyproject.toml`` (sezione ``[tool.observatory]``).

Sostituisce la lettura dal ``sources_registry.yaml`` centrale per i run
per-repo. La shape restituita e' compatibile con quella attesa dai collectors
(voce di registry): ``protocol``, ``base_url``, ``inventory`` e i blocchi
specifici di protocollo (``sparql``, ``html_portal``, …) passano inalterati.

Esempio di sezione::

    [tool.observatory]
    source_id = "eurostat"
    protocol = "sdmx"
    base_url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/dataflow/ESTAT"
    observation_mode = "catalog-watch"
    verdict = "go"
    note = "Catalogo SDMX Eurostat (dataflow ESTAT)."

    [tool.observatory.inventory]
    timeout = 300

Cross-check: se il repo dichiara anche ``[tool.toolkit.extends] source_id``,
i due valori devono coincidere.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from scripts.collectors import supported_protocols

REQUIRED_KEYS = ("source_id", "protocol", "base_url")
DEFAULT_OBSERVATION_MODE = "catalog-watch"
VALID_OBSERVATION_MODES = frozenset({"catalog-watch", "radar-only", "monitor-active"})
VALID_VERDICTS = frozenset({"go", "hold", "drop"})


class ObservatoryConfigError(ValueError):
    """Config ``[tool.observatory]`` mancante o non valida."""


def _load_pyproject(pyproject_path: Path) -> dict[str, Any]:
    if not pyproject_path.exists():
        raise ObservatoryConfigError(f"pyproject.toml not found: {pyproject_path}")
    try:
        with pyproject_path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ObservatoryConfigError(f"Invalid TOML in {pyproject_path}: {exc}") from exc


def _extract_tool_table(data: dict[str, Any], section: str) -> dict[str, Any]:
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}
    block = tool.get(section)
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise ObservatoryConfigError(
            f"[tool.{section}] must be a table, got {type(block).__name__}"
        )
    return dict(block)


def validate_observatory_config(
    obs: dict[str, Any],
    *,
    toolkit_source_id: str | None = None,
    pyproject_path: Path | None = None,
) -> dict[str, Any]:
    """Valida la sezione ``[tool.observatory]`` e restituisce il dict normalizzato.

    Campi ignoti vengono preservati (pass-through ai collectors): blocchi come
    ``sparql`` o ``html_portal`` restano nella config.
    """
    where = f" in {pyproject_path}" if pyproject_path else ""

    missing = [k for k in REQUIRED_KEYS if not obs.get(k)]
    if missing:
        raise ObservatoryConfigError(
            f"[tool.observatory]{where}: missing required keys: {', '.join(missing)}"
        )

    source_id = str(obs["source_id"])
    protocol = str(obs["protocol"])
    if protocol not in supported_protocols():
        raise ObservatoryConfigError(
            f"[tool.observatory]{where}: unsupported protocol '{protocol}' "
            f"(supported: {', '.join(sorted(supported_protocols()))})"
        )

    observation_mode = str(obs.get("observation_mode") or DEFAULT_OBSERVATION_MODE)
    if observation_mode not in VALID_OBSERVATION_MODES:
        raise ObservatoryConfigError(
            f"[tool.observatory]{where}: invalid observation_mode '{observation_mode}' "
            f"(valid: {', '.join(sorted(VALID_OBSERVATION_MODES))})"
        )

    verdict = obs.get("verdict")
    if verdict is not None and str(verdict) not in VALID_VERDICTS:
        raise ObservatoryConfigError(
            f"[tool.observatory]{where}: invalid verdict '{verdict}' "
            f"(valid: {', '.join(sorted(VALID_VERDICTS))})"
        )

    if toolkit_source_id is not None and toolkit_source_id != source_id:
        # Warning, non errore: [tool.toolkit.extends].source_id e' spesso
        # un id "da repo" (es. oecd-benchmark) mentre i dataset.yml usano
        # l'id fonte reale (es. oecd). La verita' operativa per i catalog
        # per-repo e' il source_id dei dataset.yml (abbinamento automatico
        # di datasets_in_use dal registry locale).
        print(
            f"⚠️  [tool.observatory]{where}: source_id '{source_id}' differs from "
            f"[tool.toolkit.extends] source_id '{toolkit_source_id}' "
            f"(datasets_in_use follows dataset.yml source_id)"
        )

    cfg: dict[str, Any] = {
        "source_id": source_id,
        "protocol": protocol,
        "base_url": str(obs["base_url"]),
        "observation_mode": observation_mode,
        "source_kind": str(obs.get("source_kind") or "catalog"),
    }
    if verdict is not None:
        cfg["verdict"] = str(verdict)
    if obs.get("note"):
        cfg["note"] = str(obs["note"])
    if isinstance(obs.get("inventory"), dict):
        cfg["inventory"] = dict(obs["inventory"])
    if isinstance(obs.get("catalog_baseline"), dict):
        cfg["catalog_baseline"] = dict(obs["catalog_baseline"])
    if isinstance(obs.get("pattern_probes"), list):
        cfg["pattern_probes"] = [dict(p) for p in obs["pattern_probes"] if isinstance(p, dict)]

    # Pass-through: blocchi specifici di protocollo e campi ignoti.
    known = set(REQUIRED_KEYS) | {
        "observation_mode",
        "source_kind",
        "verdict",
        "note",
        "inventory",
        "catalog_baseline",
        "pattern_probes",
    }
    for key, value in obs.items():
        if key not in known and key not in cfg:
            cfg[key] = value

    return cfg


def load_observatory_config(repo_root: Path) -> dict[str, Any]:
    """Carica ``[tool.observatory]`` dal pyproject del repo.

    Returns:
        Dict config fonte compatibile con la shape registry (collectors).

    Raises:
        ObservatoryConfigError: sezione assente, chiavi mancanti, valori non
            validi, o disallineamento con ``[tool.toolkit.extends].source_id``.
    """
    pyproject_path = repo_root / "pyproject.toml"
    data = _load_pyproject(pyproject_path)

    obs = _extract_tool_table(data, "observatory")
    if not obs:
        raise ObservatoryConfigError(f"[tool.observatory] section not found in {pyproject_path}")

    extends = _extract_tool_table(data, "toolkit")
    raw_extends = extends.get("extends")
    toolkit_extends: dict[str, Any] = raw_extends if isinstance(raw_extends, dict) else {}
    toolkit_source_id = (
        str(toolkit_extends["source_id"]) if toolkit_extends.get("source_id") else None
    )

    return validate_observatory_config(
        obs, toolkit_source_id=toolkit_source_id, pyproject_path=pyproject_path
    )
