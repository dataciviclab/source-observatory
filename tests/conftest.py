"""Conftest per source-observatory.

Aggiunge scripts/ a sys.path in modo che i test possano importare
i moduli direttamente senza importlib.util boilerplate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
