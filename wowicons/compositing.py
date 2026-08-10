"""Fit generated art into a WoW icon border template.

A port of the C# ``IconCompositor`` in ``WowIconForge/src/WowIconForge.Core``,
kept behaviourally identical so both front ends produce the same icons. The
steps run in this exact order, and the order is load-bearing:

1. Load the border template (RGBA, usually 64x64).
2. Derive the content mask once per template and cache it: flood-fill from the
   centre through transparent pixels with 4-connectivity, halting at opaque
   ones, then union that interior with the template's own opaque pixels.
3. Downscale the generated art to the template's size with Lanczos, then apply
   an optional unsharp mask.
4. Zero the alpha of every art pixel outside the content mask.
5. Alpha-composite the template over the masked art.

Unioning the interior with the opaque pixels is what lets art survive
underneath a semi-transparent border edge. Corners are in neither half of the
union - the ring blocks the flood fill and they are transparent in the template
- so they end up fully transparent, which is what an icon needs.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PIL import Image, ImageFilter

__all__ = [
    "ContentMask",
    "CompositeOptions",
    "derive_content_mask",
    "load_template",
    "composite_icon",
    "unsharp_mask",
]

#: Template alpha at or above this counts as border and blocks the flood fill.
DEFAULT_OPAQUE_THRESHOLD = 1

DEFAULT_SHARPEN_AMOUNT = 0.35
DEFAULT_SHARPEN_RADIUS = 1.0
MAX_SHARPEN_AMOUNT = 5.0


@dataclass(frozen=True)
class ContentMask:
    """Which pixels of a template generated art may occupy."""

    width: int
    height: int
    included: Tuple[bool, ...]
    interior_pixels: int
    opaque_pixels: int

    def includes(self, x: int, y: int) -> bool:
        return self.included[(y * self.width) + x]

    @property
    def has_empty_interior(self) -> bool:
        """True when the template's centre is opaque, so no art can show."""
        return self.interior_pixels == 0

    @property
    def included_pixels(self) -> int:
        return sum(self.included)


@dataclass(frozen=True)
class CompositeOptions:
    """Knobs for one compositing pass."""

    sharpen_amount: float = DEFAULT_SHARPEN_AMOUNT
    sharpen_radius: float = DEFAULT_SHARPEN_RADIUS
    opaque_threshold: int = DEFAULT_OPAQUE_THRESHOLD


def derive_content_mask(
    template: Image.Image, opaque_threshold: int = DEFAULT_OPAQUE_THRESHOLD
) -> ContentMask:
    """Derive the mask for a template (step 2)."""
    template = template.convert("RGBA")
    width, height = template.size
    alpha = template.getchannel("A").tobytes()

    is_opaque = [value >= opaque_threshold for value in alpha]
    opaque_count = sum(is_opaque)

    interior = [False] * (width * height)
    interior_count = 0
    centre = ((height // 2) * width) + (width // 2)

    if not is_opaque[centre]:
        queue = deque([centre])
        interior[centre] = True
        interior_count = 1

        while queue:
            index = queue.popleft()
            x = index % width
            y = index // width

            # 4-connectivity on purpose: an 8-connected fill leaks through the
            # diagonal joins in a border ring and floods the corners.
            neighbours = []
            if x > 0:
                neighbours.append(index - 1)
            if x < width - 1:
                neighbours.append(index + 1)
            if y > 0:
                neighbours.append(index - width)
            if y < height - 1:
                neighbours.append(index + width)

            for neighbour in neighbours:
                if not interior[neighbour] and not is_opaque[neighbour]:
                    interior[neighbour] = True
                    interior_count += 1
                    queue.append(neighbour)

    included = tuple(
        interior[i] or is_opaque[i] for i in range(width * height)
    )

    return ContentMask(
        width=width,
        height=height,
        included=included,
        interior_pixels=interior_count,
        opaque_pixels=opaque_count,
    )


_mask_cache: Dict[Tuple[str, int], ContentMask] = {}


def _template_key(template: Image.Image) -> str:
    """Content hash, so editing a template in place invalidates its mask."""
    rgba = template.convert("RGBA")
    digest = hashlib.sha256(rgba.tobytes()).hexdigest()
    return f"{rgba.width}x{rgba.height}:{digest}"


def content_mask_for(
    template: Image.Image, opaque_threshold: int = DEFAULT_OPAQUE_THRESHOLD
) -> ContentMask:
    """Cached :func:`derive_content_mask` - once per template, not per icon."""
    key = (_template_key(template), opaque_threshold)
    mask = _mask_cache.get(key)
    if mask is None:
        mask = derive_content_mask(template, opaque_threshold)
        _mask_cache[key] = mask
    return mask


def clear_mask_cache() -> None:
    _mask_cache.clear()


def load_template(path) -> Image.Image:
    """Load a border template as RGBA."""
    with Image.open(path) as image:
        return image.convert("RGBA")


def unsharp_mask(
    image: Image.Image,
    amount: float = DEFAULT_SHARPEN_AMOUNT,
    radius: float = DEFAULT_SHARPEN_RADIUS,
) -> Image.Image:
    """Sharpen the colour channels only, leaving alpha untouched.

    Alpha is deliberately excluded: sharpening it would chew into the content
    mask's edges, which the compositor depends on being exact.
    """
    if amount < 0 or amount > MAX_SHARPEN_AMOUNT:
        raise ValueError(f"amount must be within [0, {MAX_SHARPEN_AMOUNT}], got {amount}")
    if amount == 0:
        return image.copy()
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius}")

    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")

    # Pillow's percent is 0-500 where 100 means "no change beyond the blur
    # difference"; amount 1.0 maps to the usual 150% starting point.
    sharpened = rgb.filter(
        ImageFilter.UnsharpMask(radius=radius, percent=int(amount * 150), threshold=0)
    )

    result = sharpened.convert("RGBA")
    result.putalpha(alpha)
    return result


def composite_icon(
    art: Image.Image,
    template: Image.Image,
    options: Optional[CompositeOptions] = None,
) -> Image.Image:
    """Run the full pipeline and return the finished RGBA icon."""
    options = options or CompositeOptions()
    template = template.convert("RGBA")
    mask = content_mask_for(template, options.opaque_threshold)

    # Step 3: downscale, then sharpen.
    art = art.convert("RGBA")
    if art.size != template.size:
        art = art.resize(template.size, Image.LANCZOS)
    if options.sharpen_amount > 0:
        art = unsharp_mask(art, options.sharpen_amount, options.sharpen_radius)

    # Step 4: zero alpha outside the mask.
    alpha = bytearray(art.getchannel("A").tobytes())
    for i, included in enumerate(mask.included):
        if not included:
            alpha[i] = 0
    art.putalpha(Image.frombytes("L", art.size, bytes(alpha)))

    # Step 5: border over art.
    return Image.alpha_composite(art, template)
