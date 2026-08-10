"""Write BLP2 textures: palettized, 256 colours, 8-bit alpha, full mip chain.

The counterpart to :mod:`wowicons.blp`, and a port of the C# ``BlpWriter``.
Kept in its own module for the same reason the decoder is: the format code
stays independent of whatever imaging library the rest of the tool uses.

The two writers implement the same algorithm but are not bit-identical: median
cut's result depends on the order the colour histogram is walked, and Python's
dict and .NET's Dictionary do not agree on that. Both land within a couple of
levels of each other, and either output reads correctly in the other's decoder.

Two details that matter for icon quality:

* **Alpha is never quantized.** It is written verbatim as its own 8-bit plane
  after each level's index plane, so it survives a round trip exactly. Only the
  colour channels go through the palette.
* **Mip downsampling weights RGB by alpha.** A plain average drags the colour of
  fully transparent padding into visible pixels, and the symptom is a dark halo
  creeping inward around the icon as the mips shrink.
"""

from __future__ import annotations

import struct
from typing import Iterable, List, Optional, Sequence, Tuple

from . import blp

__all__ = ["build_palette", "build_mipmaps", "downsample", "encode_blp2", "save_blp2"]

RgbColor = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


def build_palette(
    pixels: bytes, max_colors: int = 256, alpha_threshold: int = 1
) -> List[RgbColor]:
    """Median-cut palette over the visible pixels of an RGBA buffer.

    Fully transparent pixels are excluded: their RGB is arbitrary padding, and
    letting it vote spends palette entries on colour nobody can see.
    """
    if not 1 <= max_colors <= 256:
        raise ValueError(f"max_colors must be within [1, 256], got {max_colors}")

    histogram: dict = {}
    for i in range(0, len(pixels), 4):
        if pixels[i + 3] < alpha_threshold:
            continue
        key = (pixels[i], pixels[i + 1], pixels[i + 2])
        histogram[key] = histogram.get(key, 0) + 1

    if not histogram:
        return [(0, 0, 0)]

    if len(histogram) <= max_colors:
        # Exact palette: colour round-trips losslessly.
        return sorted(histogram)

    boxes = [list(histogram.items())]

    while len(boxes) < max_colors:
        target = -1
        widest = -1
        largest_population = -1
        for index, box in enumerate(boxes):
            if len(box) < 2:
                continue
            side = max(
                max(c[channel] for c, _ in box) - min(c[channel] for c, _ in box)
                for channel in range(3)
            )
            population = sum(count for _, count in box)
            # Widest box wins; among equally wide boxes the busiest one does.
            # Matching the C# writer here keeps the two ports interchangeable.
            if side > widest or (side == widest and population > largest_population):
                widest = side
                largest_population = population
                target = index

        if target < 0:
            break  # every box holds a single colour

        box = boxes[target]
        ranges = [
            (
                max(c[channel] for c, _ in box) - min(c[channel] for c, _ in box),
                channel,
            )
            for channel in range(3)
        ]
        _, channel = max(ranges)
        box.sort(key=lambda entry: entry[0][channel])

        # Cut where the running pixel count passes half the box population, so
        # both halves stay similarly busy rather than similarly wide.
        half = sum(count for _, count in box) // 2
        running = 0
        split = 1
        for i in range(len(box) - 1):
            running += box[i][1]
            split = i + 1
            if running >= half:
                break

        boxes[target] = box[:split]
        boxes.append(box[split:])

    palette = []
    for box in boxes:
        total = sum(count for _, count in box) or 1
        palette.append(
            tuple(
                (sum(c[channel] * count for c, count in box) + (total // 2)) // total
                for channel in range(3)
            )
        )
    return palette


class _PaletteMapper:
    """Nearest-colour lookup with memoisation."""

    def __init__(self, palette: Sequence[RgbColor]):
        self._palette = list(palette)
        self._cache = {colour: index for index, colour in enumerate(self._palette)}

    def index_of(self, colour: RgbColor) -> int:
        cached = self._cache.get(colour)
        if cached is not None:
            return cached

        best = 0
        best_distance = 1 << 30
        r, g, b = colour
        for index, (pr, pg, pb) in enumerate(self._palette):
            distance = (pr - r) ** 2 + (pg - g) ** 2 + (pb - b) ** 2
            if distance < best_distance:
                best_distance = distance
                best = index
                if distance == 0:
                    break

        self._cache[colour] = best
        return best


# ---------------------------------------------------------------------------
# Mipmaps
# ---------------------------------------------------------------------------


def downsample(pixels: bytes, width: int, height: int) -> Tuple[bytes, int, int]:
    """Halve an RGBA buffer with an alpha-weighted 2x2 box filter."""
    new_width = max(1, width // 2)
    new_height = max(1, height // 2)
    out = bytearray(new_width * new_height * 4)

    for y in range(new_height):
        for x in range(new_width):
            x0 = min((x * 2), width - 1)
            x1 = min((x * 2) + 1, width - 1)
            y0 = min((y * 2), height - 1)
            y1 = min((y * 2) + 1, height - 1)

            offsets = [
                ((y0 * width) + x0) * 4,
                ((y0 * width) + x1) * 4,
                ((y1 * width) + x0) * 4,
                ((y1 * width) + x1) * 4,
            ]

            alpha_sum = sum(pixels[o + 3] for o in offsets)
            target = ((y * new_width) + x) * 4

            if alpha_sum == 0:
                for channel in range(3):
                    out[target + channel] = (
                        sum(pixels[o + channel] for o in offsets) + 2
                    ) // 4
                out[target + 3] = 0
            else:
                for channel in range(3):
                    weighted = sum(
                        pixels[o + channel] * pixels[o + 3] for o in offsets
                    )
                    out[target + channel] = min(
                        255, (weighted + (alpha_sum // 2)) // alpha_sum
                    )
                out[target + 3] = (alpha_sum + 2) // 4

    return bytes(out), new_width, new_height


def build_mipmaps(pixels: bytes, width: int, height: int):
    """Full chain from the source size down to 1x1."""
    levels = [(pixels, width, height)]
    while width > 1 or height > 1:
        pixels, width, height = downsample(pixels, width, height)
        levels.append((pixels, width, height))
    return levels


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def encode_blp2(
    pixels: bytes,
    width: int,
    height: int,
    generate_mipmaps: bool = True,
    max_colors: int = 256,
) -> bytes:
    """Encode a top-down RGBA buffer as a BLP2 file."""
    expected = width * height * 4
    if len(pixels) != expected:
        raise ValueError(
            f"expected {expected} bytes for {width}x{height} RGBA, got {len(pixels)}"
        )

    levels = (
        build_mipmaps(pixels, width, height)
        if generate_mipmaps
        else [(pixels, width, height)]
    )

    if len(levels) > blp.MAX_MIPS:
        raise ValueError(
            f"a {width}x{height} image needs {len(levels)} mip levels, "
            f"but BLP stores at most {blp.MAX_MIPS}"
        )

    # One palette for the whole chain, built from the full-resolution image.
    palette = build_palette(pixels, max_colors)
    mapper = _PaletteMapper(palette)

    encoded = []
    for level_pixels, level_width, level_height in levels:
        count = level_width * level_height
        indices = bytearray(count)
        alpha = bytearray(count)
        for i in range(count):
            p = i * 4
            indices[i] = mapper.index_of(
                (level_pixels[p], level_pixels[p + 1], level_pixels[p + 2])
            )
            alpha[i] = level_pixels[p + 3]
        encoded.append(bytes(indices) + bytes(alpha))

    data_offset = blp.BLP2_HEADER_SIZE + blp.PALETTE_SIZE
    mip_offsets = [0] * blp.MAX_MIPS
    mip_sizes = [0] * blp.MAX_MIPS
    offset = data_offset
    for i, payload in enumerate(encoded):
        mip_offsets[i] = offset
        mip_sizes[i] = len(payload)
        offset += len(payload)

    header = struct.pack(
        "<4sIBBBB",
        blp.MAGIC_BLP2,
        blp.CONTENT_DIRECT,
        blp.ENCODING_PALETTIZED,
        8,                                  # alpha depth: full 8-bit plane
        0,                                  # alpha encoding: unused here
        1 if len(encoded) > 1 else 0,
    )
    header += struct.pack("<II", width, height)
    header += struct.pack("<16I", *mip_offsets)
    header += struct.pack("<16I", *mip_sizes)

    palette_bytes = bytearray(blp.PALETTE_SIZE)
    for i, (r, g, b) in enumerate(palette):
        palette_bytes[i * 4 + 0] = b
        palette_bytes[i * 4 + 1] = g
        palette_bytes[i * 4 + 2] = r

    return header + bytes(palette_bytes) + b"".join(encoded)


def save_blp2(path, image, **kwargs) -> None:
    """Save a Pillow image (or raw RGBA tuple) as BLP2."""
    if hasattr(image, "convert"):
        rgba = image.convert("RGBA")
        pixels, width, height = rgba.tobytes(), rgba.width, rgba.height
    else:
        pixels, width, height = image

    with open(path, "wb") as handle:
        handle.write(encode_blp2(pixels, width, height, **kwargs))
