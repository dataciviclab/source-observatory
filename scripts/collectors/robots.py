"""robots.txt guard per i fetch HTML diretti del collector.

Il collector HTML fetcha pagine di portali pubblici senza passare da una
discovery che legga robots.txt (``area_pages``, ``page_url_template``,
``homepage``). Questa guardia rende esplicito il rispetto delle regole del
sito prima di ogni fetch, con cache per origine (una sola richiesta a
``robots.txt`` per host).

Il matching segue RFC 9309, non ``urllib.robotparser`` (che ignora
wildcard e longest-match):

- il gruppo più specifico per lo user agent vince su ``*``;
- ``*`` è un jolly, ``$`` ancora la fine del path;
- vince la regola con il pattern più lungo;
- a parità di lunghezza vince ``Allow``;
- nessuna regola che combacia → consentito.

Politica di fallback:
  - robots.txt assente o 4xx → nessuna regola: fetch consentito
  - robots.txt illeggibile / 5xx / errore di rete → fail-open: fetch
    consentito, ma la condizione resta visibile nel summary (``robots_error``)

Il fail-open è deliberato: un robots.txt temporaneamente rotto non deve
bloccare l'intero osservatorio. Se in futuro serve fail-closed, basta
cambiare ``_fetch_rules``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from lab_connectors.http import HttpClient

USER_AGENT = "DataCivicLab-SourceObservatory/1.0"


@dataclass(frozen=True)
class _Rule:
    """Una riga ``Allow``/``Disallow`` già compilata."""

    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def weight(self) -> int:
        """Specificità = lunghezza del pattern, ``*`` incluso (RFC 9309)."""
        return len(self.pattern)


def _origin(url: str) -> str:
    """Origine (scheme://netloc) di un URL, o stringa vuota se non valido."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _url_path(url: str) -> str:
    """Path + query di un URL, come vuole il matching robots."""
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return path


def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Converte un pattern robots in regex: ``*`` jolly, ``$`` fine path."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    parts: list[str] = []
    for char in body:
        parts.append(".*" if char == "*" else re.escape(char))
    return re.compile("^" + "".join(parts) + ("$" if anchored else ""))


def _parse_rules(text: str) -> dict[str, list[_Rule]]:
    """Raggruppa le regole per user-agent (chiavi minuscole)."""
    groups: dict[str, list[_Rule]] = {}
    current: list[str] | None = None
    in_rules = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = line.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if current is None or in_rules:
                current = []
                in_rules = False
            current.append(value.lower())
            for agent in current:
                groups.setdefault(agent, [])
            continue

        if field not in ("allow", "disallow") or current is None:
            continue
        in_rules = True
        if not value:
            # `Disallow:` vuoto = nessuna restrizione.
            continue
        rule = _Rule(
            allow=field == "allow",
            pattern=value,
            regex=_compile_pattern(value),
        )
        for agent in current:
            groups[agent].append(rule)

    return groups


def _select_rules(groups: dict[str, list[_Rule]], user_agent: str) -> list[_Rule]:
    """Regole del gruppo più specifico per lo user agent."""
    token = user_agent.split("/", 1)[0].lower()
    candidates = [
        name for name in groups if name != "*" and name and name.split("/", 1)[0] in token
    ]
    if candidates:
        return groups[max(candidates, key=len)]
    return groups.get("*", [])


def _allowed(rules: list[_Rule], path: str) -> bool:
    """Longest-match: vince il pattern più lungo, pareggio a ``Allow``."""
    best: _Rule | None = None
    for rule in rules:
        if not rule.regex.match(path):
            continue
        if best is None or rule.weight > best.weight:
            best = rule
        elif rule.weight == best.weight and rule.allow and not best.allow:
            best = rule
    return True if best is None else best.allow


class RobotsGuard:
    """Verifica robots.txt con cache per origine.

    Uso:
        guard = RobotsGuard()
        if guard.can_fetch(url):
            client.get(url)
    """

    def __init__(
        self,
        user_agent: str = USER_AGENT,
        client_factory: Callable[..., Any] = HttpClient,
        timeout: int = 10,
    ) -> None:
        self._user_agent = user_agent
        self._client_factory = client_factory
        self._timeout = timeout
        self._cache: dict[str, list[_Rule] | None] = {}
        self._errors: set[str] = set()

    @property
    def errors(self) -> set[str]:
        """Origini con robots.txt illeggibile (fail-open applicato)."""
        return set(self._errors)

    def can_fetch(self, url: str) -> bool:
        """True se robots.txt consente il fetch dell'URL."""
        origin = _origin(url)
        if not origin:
            return True
        rules = self._rules(origin)
        if rules is None:
            return True
        return _allowed(rules, _url_path(url))

    def _rules(self, origin: str) -> list[_Rule] | None:
        if origin in self._cache:
            return self._cache[origin]
        rules = self._fetch_rules(origin)
        self._cache[origin] = rules
        return rules

    def _fetch_rules(self, origin: str) -> list[_Rule] | None:
        robots_url = f"{origin}/robots.txt"
        try:
            client = self._client_factory(timeout=self._timeout)
            result = client.get(robots_url)
        except Exception:
            self._errors.add(origin)
            return None
        if not result.is_ok or result.response is None:
            self._errors.add(origin)
            return None
        status = getattr(result.response, "status_code", 200)
        if status >= 400:
            # 4xx = robots assente (allow); 5xx = fail-open tracciato.
            if status >= 500:
                self._errors.add(origin)
            return None
        return _select_rules(_parse_rules(result.response.text), self._user_agent)
