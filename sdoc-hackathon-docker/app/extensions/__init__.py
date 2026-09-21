"""Extensions package (plan 05).

Hard rule (plan 00 F7): this package is **never imported when
``SCORED_RUN=1``**. Every module here must be side-effect free and expose
``is_enabled()`` so ``run.py`` can gate it.
"""
from __future__ import annotations

from .. import state


def extensions_enabled() -> bool:
    """Extensions are default-OFF on the frozen run (G1)."""
    return not state.SCORED_RUN


def is_enabled() -> bool:
    return extensions_enabled()
