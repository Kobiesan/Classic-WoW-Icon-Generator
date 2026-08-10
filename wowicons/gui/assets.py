"""Art the app draws for itself.

The one asset that matters is the built-in border template: a bevelled gold
frame with a transparent interior and transparent rounded corners, drawn with
Pillow at runtime. It exists so that the Generate tab produces framed,
game-shaped icons out of the box - before the user has found or made a
template of their own - and so the repository ships no copied game art.

The frame is a valid input to the same compositing pipeline as any
user-supplied template: the ring blocks the flood fill, the interior is open,
and the corners fall outside the mask, exactly as the pipeline expects.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

__all__ = ["default_border_template", "DEFAULT_TEMPLATE_SIZE"]

DEFAULT_TEMPLATE_SIZE = 64

# The bevel, outermost ring first: dark bronze edge, the gold body, a bright
# top-facing line, then a shadow line against the interior. Same palette
# family as the window theme.
_RINGS = (
    ("#2b2013", 2),   # outer edge
    ("#c8aa6e", 3),   # gold body
    ("#f0d078", 1),   # highlight
    ("#5c4a28", 1),   # inner shadow
)


@lru_cache(maxsize=None)
def _build(size: int) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = max(size // 10, 3)
    inset = 0
    for colour, width in _RINGS:
        draw.rounded_rectangle(
            (inset, inset, size - 1 - inset, size - 1 - inset),
            radius=max(radius - inset, 1),
            outline=colour,
            width=width,
        )
        inset += width

    return image.tobytes()


def default_border_template(size: int = DEFAULT_TEMPLATE_SIZE) -> Image.Image:
    """The built-in gold frame, as a fresh RGBA image each call.

    Returned as a copy so no caller can mutate the cached original.
    """
    return Image.frombytes("RGBA", (size, size), _build(size))
