"""robots.txt guard per i fetch HTML diretti del collector.

Il collector HTML fetcha pagine di portali pubblici senza passare da una
discovery che legga robots.txt (``area_pages``, ``page_url_template``,
``homepage``). Questa guardia rende esplicito il rispetto delle regole del
sito prima di ogni fetch, con cache per origine (una sola richiesta a
``robots.txt`` per host).

Politica di fallback:
  - robots.txt assente o 4xx → nessuna regola: fetch consentito
  - robots.txt illeggibile / 5xx / errore di rete → fail-open: fetch
    consentito, ma la condizione resta visibile nel summary (``robots_error``)

Il fail-open è deliberato: un robots.txt temporaneamente rotto non deve
bloccare l'intero osservatorio. Se in futuro serve fail-closed, basta
cambiare ``_fetch_parser``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from lab_connectors.http import HttpClient

USER_AGENT = "DataCivicLab-SourceObservatory/1.0"


def _origin(url: str) -> str:
    """Origine (scheme://netloc) di un URL, o stringa vuota se non valido."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


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
        self._cache: dict[str, RobotFileParser | None] = {}
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
        parser = self._parser(origin)
        if parser is None:
            return True
        return bool(parser.can_fetch(self._user_agent, url))

    def _parser(self, origin: str) -> RobotFileParser | None:
        if origin in self._cache:
            return self._cache[origin]
        parser = self._fetch_parser(origin)
        self._cache[origin] = parser
        return parser

    def _fetch_parser(self, origin: str) -> RobotFileParser | None:
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
        parser = RobotFileParser()
        parser.parse(result.response.text.splitlines())
        return parser
