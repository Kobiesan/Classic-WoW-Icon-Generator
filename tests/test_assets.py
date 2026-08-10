"""Tests for the built-in gold border template.

These run on any interpreter - the asset is drawn with Pillow and never touches
tkinter, which is exactly why it lives apart from the theme.
"""

from __future__ import annotations

from PIL import Image

from wowicons import compositing
from wowicons.gui import assets


def test_default_template_is_64_rgba():
    template = assets.default_border_template()
    assert template.size == (64, 64)
    assert template.mode == "RGBA"


def test_corners_are_transparent_and_interior_is_open():
    template = assets.default_border_template()

    for x, y in ((0, 0), (63, 0), (0, 63), (63, 63)):
        assert template.getpixel((x, y))[3] == 0, f"corner ({x},{y}) must be transparent"

    assert template.getpixel((32, 32))[3] == 0, "the middle must be open for art"
    assert template.getpixel((1, 32))[3] == 255, "the frame ring must be opaque"


def test_template_satisfies_the_compositing_pipeline():
    """The frame must behave exactly like a user-supplied template."""
    template = assets.default_border_template()
    mask = compositing.content_mask_for(template)

    assert not mask.has_empty_interior
    assert mask.interior_pixels > 1000          # plenty of room for art
    assert not mask.includes(0, 0)              # corners excluded
    assert mask.includes(32, 32)                # centre included


def test_compositing_with_the_default_frame():
    art = Image.new("RGBA", (512, 512), (200, 40, 40, 255))
    icon = compositing.composite_icon(art, assets.default_border_template())

    assert icon.size == (64, 64)
    assert icon.getpixel((0, 0))[3] == 0        # transparent corner
    assert icon.getpixel((32, 32))[:3] == (200, 40, 40)   # art in the middle
    # gold frame drawn over the art at the edge
    r, g, b, a = icon.getpixel((3, 32))
    assert a == 255 and r > g > b


def test_template_is_deterministic():
    first = assets.default_border_template()
    second = assets.default_border_template()
    assert first.tobytes() == second.tobytes()


def test_callers_get_independent_copies():
    first = assets.default_border_template()
    first.putpixel((0, 0), (255, 255, 255, 255))

    second = assets.default_border_template()
    assert second.getpixel((0, 0))[3] == 0, "mutating one copy must not poison the cache"
