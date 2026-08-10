"""Desktop interface for building datasets, training, and generating icons.

``main`` is resolved lazily so that importing :mod:`wowicons.gui.workflows`,
:mod:`wowicons.gui.jobs` or :mod:`wowicons.gui.environment` works on an
interpreter with no tkinter - which is the whole point of keeping those layers
display free.
"""

from __future__ import annotations

__all__ = ["main"]


def __getattr__(name: str):
    if name == "main":
        from .app import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
