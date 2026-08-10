"""WoW-flavoured styling for the Tk window.

Dark oiled-wood panels, parchment text, and the classic UI gold for headings
and primary actions - the palette Blizzard's own interface art built its look
around. Everything here is drawn with colours and fonts only; no game assets
are copied or shipped.

Kept in one module so the widgets never hard-code a colour: the window calls
:func:`apply` once, and uses the returned :class:`Palette` plus the named ttk
styles (``Heading.TLabel``, ``Subtle.TLabel``, ``Accent.TButton``) everywhere
else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

__all__ = ["Palette", "PALETTE", "apply", "style_text"]


@dataclass(frozen=True)
class Palette:
    """The colour scheme, WoW-UI flavoured but hand-picked."""

    background: str = "#14100a"     # dark oiled wood
    panel: str = "#1e1710"          # slightly raised panels
    field: str = "#2a2115"          # input wells
    trough: str = "#0c0906"         # progress/scroll troughs
    border: str = "#5c4a28"         # dull bronze edging
    gold: str = "#c8aa6e"           # the classic UI gold
    gold_bright: str = "#f0d078"    # headings and highlights
    text: str = "#e8dcc8"           # parchment
    muted: str = "#a08c62"          # hints and secondary text
    on_gold: str = "#1c1408"        # text set on gold buttons


PALETTE = Palette()

#: Serif families tried for headings, most WoW-ish first. Whatever the system
#: has wins; a missing family falls back to the default face.
HEADING_FAMILIES: Tuple[str, ...] = ("Palatino Linotype", "Palatino", "Georgia", "Times New Roman")


def _pick_family(root: tk.Misc) -> str:
    available = {name.casefold() for name in tkfont.families(root)}
    for name in HEADING_FAMILIES:
        if name.casefold() in available:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def apply(root: tk.Tk) -> Palette:
    """Apply the theme to a window. Call once, before building widgets."""
    p = PALETTE
    root.configure(background=p.background)

    serif = _pick_family(root)
    heading_font = (serif, 13, "bold")
    tab_font = (serif, 11, "bold")

    style = ttk.Style(root)
    # clam is the one built-in theme whose every element takes custom colours.
    style.theme_use("clam")

    style.configure(
        ".",
        background=p.background,
        foreground=p.text,
        bordercolor=p.border,
        darkcolor=p.background,
        lightcolor=p.background,
        troughcolor=p.trough,
        fieldbackground=p.field,
        selectbackground=p.gold,
        selectforeground=p.on_gold,
        insertcolor=p.text,
        focuscolor=p.gold,
    )

    style.configure("TFrame", background=p.background)
    style.configure("TLabel", background=p.background, foreground=p.text)
    style.configure("Heading.TLabel", foreground=p.gold_bright, font=heading_font)
    style.configure("Subtle.TLabel", foreground=p.muted)

    style.configure("TNotebook", background=p.background, borderwidth=0, tabmargins=(8, 6, 8, 0))
    style.configure(
        "TNotebook.Tab",
        background=p.panel,
        foreground=p.muted,
        padding=(16, 8),
        font=tab_font,
        bordercolor=p.border,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p.background)],
        foreground=[("selected", p.gold_bright), ("active", p.gold)],
    )

    style.configure(
        "TButton",
        background=p.panel,
        foreground=p.text,
        bordercolor=p.border,
        padding=(10, 5),
    )
    style.map(
        "TButton",
        background=[("active", "#2c2214"), ("disabled", p.panel)],
        foreground=[("disabled", "#6b5f49")],
        bordercolor=[("active", p.gold)],
    )

    # The three primary actions: gold, so the eye lands on the right button.
    style.configure(
        "Accent.TButton",
        background=p.gold,
        foreground=p.on_gold,
        bordercolor=p.gold_bright,
        font=(serif, 11, "bold"),
        padding=(12, 6),
    )
    style.map(
        "Accent.TButton",
        background=[("active", p.gold_bright), ("disabled", "#57503f")],
        foreground=[("disabled", "#2c2820")],
    )

    for entry_like in ("TEntry", "TSpinbox"):
        style.configure(
            entry_like,
            fieldbackground=p.field,
            foreground=p.text,
            bordercolor=p.border,
            insertcolor=p.text,
            arrowcolor=p.muted,
            padding=3,
        )
        style.map(
            entry_like,
            bordercolor=[("focus", p.gold)],
            lightcolor=[("focus", p.gold)],
            arrowcolor=[("active", p.gold)],
        )

    style.configure(
        "Horizontal.TProgressbar",
        background=p.gold,
        troughcolor=p.trough,
        bordercolor=p.border,
        lightcolor=p.gold_bright,
        darkcolor=p.gold,
    )

    style.configure(
        "TScrollbar",
        background=p.panel,
        troughcolor=p.trough,
        bordercolor=p.border,
        arrowcolor=p.muted,
    )
    style.map("TScrollbar", background=[("active", p.border)])

    style.configure(
        "Horizontal.TScale",
        background=p.gold,
        troughcolor=p.trough,
        bordercolor=p.border,
        lightcolor=p.gold_bright,
        darkcolor=p.gold,
    )

    return p


def style_text(widget: tk.Text) -> None:
    """Dress a plain tk.Text (prompt boxes, logs) to match the ttk theme.

    tk.Text is not a ttk widget, so it takes none of the style map above and
    has to be configured directly.
    """
    p = PALETTE
    widget.configure(
        background=p.field,
        foreground=p.text,
        insertbackground=p.text,
        selectbackground=p.gold,
        selectforeground=p.on_gold,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=p.border,
        highlightcolor=p.gold,
        padx=8,
        pady=6,
    )
