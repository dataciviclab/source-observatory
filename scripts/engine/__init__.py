"""Engine del Source Observatory — primitive condivise, senza dipendenze dal centrale.

Questo package è il **confine del motore**: contiene le primitive che il
catalog engine per-repo (``so-catalog``) condivide con il centrale, ma in
direzione invertita rispetto a prima — è il centrale a importare da qui, non
viceversa.

Regola (verificata da ``tests/test_engine_boundary.py``):

  - ``scripts/engine``, ``scripts/collectors``, ``scripts/catalog`` e
    ``scripts/pipeline`` importano solo da questi quattro prefissi: qualsiasi
    altro modulo ``scripts.*`` è centrale (``scripts._constants``,
    ``scripts.radar_check``, ``scripts.build_source_reports``, …) e non è
    ammesso;
  - non importano ``so_mcp`` né librerie pesanti (``duckdb``, ``pandas``,
    ``pyarrow``, ``ddgs``, ``mcp``).

Moduli:
    formats   → scoring dei formati (usato dai collector e dai validatori)
    probe     → probe HTTP di una fonte (radar + catalog)
    portal    → profiling di portali HTML (sitemap, RSS, JSON API)
    report    → aggregazioni e build del report di fonte (funzione pura)

Nessun import eager qui dentro: i moduli si importano per nome
(``scripts.engine.probe``) per non creare cicli con ``scripts.collectors``.
"""
