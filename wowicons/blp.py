"""Pure-Python decoder for Blizzard's BLP1 and BLP2 texture format.

This module is deliberately self-contained: it depends only on the standard
library, holds no state, and uses plain integer arithmetic over ``bytes`` /
``bytearray`` (no numpy, no Pillow) so it can be ported to C# more or less
line by line.  The only exception is :func:`_decode_jpeg`, which handles the
rare JPEG-compressed BLP1 variant and lazily imports Pillow -- a C# port would
swap that for ``System.Drawing`` / ``ImageSharp`` and can ignore the rest.

Everything decodes to a single, unambiguous output: top-down, non-premultiplied
8-bit RGBA.

Format reference
----------------
BLP1 header (156 bytes, little endian)::

    char     magic[4]        "BLP1"
    uint32   content         0 = JPEG, 1 = direct (palettized)
    uint32   alpha_depth     0, 1, 4 or 8 bits of alpha per pixel
    uint32   width
    uint32   height
    uint32   picture_type    3/4 = alpha honoured, 5 = alpha ignored
    uint32   has_mips
    uint32   mip_offsets[16]
    uint32   mip_sizes[16]

For ``content == 1`` a 256 entry BGRA palette follows the header.  For
``content == 0`` a ``uint32`` shared-JPEG-header length follows, then that many
bytes; each mip level is that shared header concatenated with the mip payload.

BLP2 header (148 bytes, little endian) followed by an always-present 256 entry
BGRA palette (1024 bytes)::

    char     magic[4]        "BLP2"
    uint32   content         0 = JPEG, 1 = direct
    uint8    encoding        1 = palettized, 2 = DXT, 3 = BGRA8888
    uint8    alpha_depth     0, 1, 4 or 8
    uint8    alpha_encoding  0 = DXT1, 1 = DXT3, 7 = DXT5
    uint8    has_mips
    uint32   width
    uint32   height
    uint32   mip_offsets[16]
    uint32   mip_sizes[16]

Usage::

    from wowicons.blp import open_blp
    image = open_blp("INV_Sword_04.blp")
    image.width, image.height, image.pixels   # RGBA bytes, len == w * h * 4
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

__all__ = [
    "BLPError",
    "UnsupportedBLPError",
    "BLPImage",
    "BLPHeader",
    "decode",
    "open_blp",
    "read_header",
]

MAGIC_BLP1 = b"BLP1"
MAGIC_BLP2 = b"BLP2"

CONTENT_JPEG = 0
CONTENT_DIRECT = 1

ENCODING_PALETTIZED = 1
ENCODING_DXT = 2
ENCODING_BGRA8888 = 3

ALPHA_ENCODING_DXT1 = 0
ALPHA_ENCODING_DXT3 = 1
ALPHA_ENCODING_DXT5 = 7

BLP1_HEADER_SIZE = 156
BLP2_HEADER_SIZE = 148
PALETTE_SIZE = 256 * 4
MAX_MIPS = 16

#: ``picture_type`` values on BLP1 that mean "ignore the alpha channel".
BLP1_OPAQUE_PICTURE_TYPES = frozenset({5})


class BLPError(Exception):
    """Raised when a file is not a readable BLP."""


class UnsupportedBLPError(BLPError):
    """Raised for well-formed BLPs using a variant this decoder cannot read."""


@dataclass
class BLPImage:
    """A decoded mip level: top-down, non-premultiplied 8-bit RGBA."""

    width: int
    height: int
    pixels: bytearray

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    def tobytes(self) -> bytes:
        return bytes(self.pixels)

    def getpixel(self, x: int, y: int) -> Tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        return (
            self.pixels[i],
            self.pixels[i + 1],
            self.pixels[i + 2],
            self.pixels[i + 3],
        )


@dataclass
class BLPHeader:
    """Parsed BLP header, normalised across BLP1 and BLP2."""

    version: int
    content: int
    encoding: int
    alpha_depth: int
    alpha_encoding: int
    has_mips: int
    width: int
    height: int
    mip_offsets: Tuple[int, ...]
    mip_sizes: Tuple[int, ...]
    palette: List[Tuple[int, int, int]] = field(default_factory=list)
    picture_type: int = 0
    jpeg_header: bytes = b""

    @property
    def mip_count(self) -> int:
        """Number of usable mip levels (offsets are zero-terminated)."""
        count = 0
        for offset, size in zip(self.mip_offsets, self.mip_sizes):
            if offset == 0 or size == 0:
                break
            count += 1
        return max(count, 1)

    @property
    def alpha_ignored(self) -> bool:
        """True when the file carries alpha bits that should not be used."""
        if self.alpha_depth == 0:
            return True
        if self.version == 1 and self.picture_type in BLP1_OPAQUE_PICTURE_TYPES:
            return True
        return False


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


def _read_palette(data: bytes, offset: int) -> List[Tuple[int, int, int]]:
    """Read a 256 entry BGRA palette, keeping only the colour channels.

    The palette's own alpha byte is unreliable in Blizzard's files; real alpha
    comes from the separate alpha bitmap sized by ``alpha_depth``.
    """
    if len(data) < offset + PALETTE_SIZE:
        raise BLPError("file truncated inside palette")
    palette: List[Tuple[int, int, int]] = []
    for i in range(offset, offset + PALETTE_SIZE, 4):
        palette.append((data[i + 2], data[i + 1], data[i]))
    return palette


def read_header(data: bytes) -> BLPHeader:
    """Parse the BLP header. Raises :class:`BLPError` on malformed input."""
    if len(data) < 8:
        raise BLPError("file too short to be a BLP")

    magic = data[:4]
    if magic == MAGIC_BLP2:
        return _read_header_blp2(data)
    if magic == MAGIC_BLP1:
        return _read_header_blp1(data)
    raise BLPError(f"not a BLP file (magic {magic!r})")


def _read_header_blp1(data: bytes) -> BLPHeader:
    if len(data) < BLP1_HEADER_SIZE:
        raise BLPError("file truncated inside BLP1 header")

    (
        _magic,
        content,
        alpha_depth,
        width,
        height,
        picture_type,
        has_mips,
    ) = struct.unpack_from("<4sIIIIII", data, 0)
    mip_offsets = struct.unpack_from("<16I", data, 28)
    mip_sizes = struct.unpack_from("<16I", data, 92)

    header = BLPHeader(
        version=1,
        content=content,
        # BLP1 has no encoding byte: direct content is always palettized.
        encoding=ENCODING_PALETTIZED if content == CONTENT_DIRECT else 0,
        alpha_depth=alpha_depth,
        alpha_encoding=0,
        has_mips=has_mips,
        width=width,
        height=height,
        mip_offsets=mip_offsets,
        mip_sizes=mip_sizes,
        picture_type=picture_type,
    )
    _validate_dimensions(header)

    if content == CONTENT_DIRECT:
        header.palette = _read_palette(data, BLP1_HEADER_SIZE)
    elif content == CONTENT_JPEG:
        if len(data) < BLP1_HEADER_SIZE + 4:
            raise BLPError("file truncated before JPEG header size")
        (jpeg_header_size,) = struct.unpack_from("<I", data, BLP1_HEADER_SIZE)
        start = BLP1_HEADER_SIZE + 4
        if len(data) < start + jpeg_header_size:
            raise BLPError("file truncated inside shared JPEG header")
        header.jpeg_header = bytes(data[start : start + jpeg_header_size])
    else:
        raise UnsupportedBLPError(f"unknown BLP1 content type {content}")

    return header


def _read_header_blp2(data: bytes) -> BLPHeader:
    if len(data) < BLP2_HEADER_SIZE + PALETTE_SIZE:
        raise BLPError("file truncated inside BLP2 header")

    (
        _magic,
        content,
        encoding,
        alpha_depth,
        alpha_encoding,
        has_mips,
    ) = struct.unpack_from("<4sIBBBB", data, 0)
    width, height = struct.unpack_from("<II", data, 12)
    mip_offsets = struct.unpack_from("<16I", data, 20)
    mip_sizes = struct.unpack_from("<16I", data, 84)

    header = BLPHeader(
        version=2,
        content=content,
        encoding=encoding,
        alpha_depth=alpha_depth,
        alpha_encoding=alpha_encoding,
        has_mips=has_mips,
        width=width,
        height=height,
        mip_offsets=mip_offsets,
        mip_sizes=mip_sizes,
    )
    _validate_dimensions(header)
    # BLP2 always reserves palette space, even for DXT and BGRA content.
    header.palette = _read_palette(data, BLP2_HEADER_SIZE)
    return header


def _validate_dimensions(header: BLPHeader) -> None:
    if header.width <= 0 or header.height <= 0:
        raise BLPError(f"invalid dimensions {header.width}x{header.height}")
    if header.width > 16384 or header.height > 16384:
        raise BLPError(f"implausible dimensions {header.width}x{header.height}")


def mip_dimensions(header: BLPHeader, level: int) -> Tuple[int, int]:
    """Dimensions of ``level``, halving (floor, min 1) per level."""
    width = max(header.width >> level, 1)
    height = max(header.height >> level, 1)
    return width, height


def _mip_data(data: bytes, header: BLPHeader, level: int) -> bytes:
    if not 0 <= level < MAX_MIPS:
        raise BLPError(f"mip level {level} out of range")
    offset = header.mip_offsets[level]
    size = header.mip_sizes[level]
    if offset == 0:
        raise BLPError(f"mip level {level} is not present")
    if offset >= len(data):
        raise BLPError(f"mip level {level} starts past end of file")
    if size == 0:
        # Some tools write a zero size for the last level; take the remainder.
        size = len(data) - offset
    return bytes(data[offset : offset + size])


# ---------------------------------------------------------------------------
# Pixel decoding
# ---------------------------------------------------------------------------


def _decode_alpha(
    payload: bytes,
    alpha_offset: int,
    pixel_count: int,
    alpha_depth: int,
) -> List[int]:
    """Expand the trailing alpha bitmap of a palettized image to 0-255 bytes."""
    if alpha_depth == 0:
        return [255] * pixel_count

    if alpha_depth == 1:
        needed = (pixel_count + 7) // 8
        if len(payload) < alpha_offset + needed:
            raise BLPError("truncated 1-bit alpha bitmap")
        out = [0] * pixel_count
        for i in range(pixel_count):
            byte = payload[alpha_offset + (i >> 3)]
            out[i] = 255 if (byte >> (i & 7)) & 1 else 0
        return out

    if alpha_depth == 4:
        needed = (pixel_count + 1) // 2
        if len(payload) < alpha_offset + needed:
            raise BLPError("truncated 4-bit alpha bitmap")
        out = [0] * pixel_count
        for i in range(pixel_count):
            byte = payload[alpha_offset + (i >> 1)]
            nibble = byte & 0x0F if (i & 1) == 0 else (byte >> 4) & 0x0F
            out[i] = nibble * 17  # 0x0->0, 0xF->255
        return out

    if alpha_depth == 8:
        if len(payload) < alpha_offset + pixel_count:
            raise BLPError("truncated 8-bit alpha bitmap")
        return list(payload[alpha_offset : alpha_offset + pixel_count])

    raise UnsupportedBLPError(f"unsupported alpha depth {alpha_depth}")


def decode_palettized(
    payload: bytes,
    width: int,
    height: int,
    palette: Sequence[Tuple[int, int, int]],
    alpha_depth: int,
) -> bytearray:
    """Decode ``width * height`` palette indices plus optional alpha bitmap."""
    pixel_count = width * height
    if len(palette) < 256:
        raise BLPError("palettized image without a full 256 entry palette")
    if len(payload) < pixel_count:
        raise BLPError("truncated palette index data")

    alpha = _decode_alpha(payload, pixel_count, pixel_count, alpha_depth)

    out = bytearray(pixel_count * 4)
    for i in range(pixel_count):
        r, g, b = palette[payload[i]]
        j = i * 4
        out[j] = r
        out[j + 1] = g
        out[j + 2] = b
        out[j + 3] = alpha[i]
    return out


def decode_bgra8888(payload: bytes, width: int, height: int) -> bytearray:
    """Decode BLP2 encoding 3: straight BGRA bytes."""
    pixel_count = width * height
    if len(payload) < pixel_count * 4:
        raise BLPError("truncated BGRA8888 data")
    out = bytearray(pixel_count * 4)
    for i in range(pixel_count):
        j = i * 4
        out[j] = payload[j + 2]
        out[j + 1] = payload[j + 1]
        out[j + 2] = payload[j]
        out[j + 3] = payload[j + 3]
    return out


def _rgb565(value: int) -> Tuple[int, int, int]:
    """Expand a 16-bit RGB565 colour to 8 bits per channel."""
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _dxt_colour_table(
    c0: int, c1: int, allow_punchthrough: bool
) -> List[Tuple[int, int, int, int]]:
    """Build the four-entry colour table for one DXT colour block."""
    r0, g0, b0 = _rgb565(c0)
    r1, g1, b1 = _rgb565(c1)
    table = [(r0, g0, b0, 255), (r1, g1, b1, 255), None, None]  # type: ignore[list-item]
    if c0 > c1 or not allow_punchthrough:
        # Four-colour block: two interpolated thirds.
        table[2] = (
            (2 * r0 + r1) // 3,
            (2 * g0 + g1) // 3,
            (2 * b0 + b1) // 3,
            255,
        )
        table[3] = (
            (r0 + 2 * r1) // 3,
            (g0 + 2 * g1) // 3,
            (b0 + 2 * b1) // 3,
            255,
        )
    else:
        # Three-colour block: one midpoint plus a transparent index.
        table[2] = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255)
        table[3] = (0, 0, 0, 0)
    return table  # type: ignore[return-value]


def decode_dxt(
    payload: bytes,
    width: int,
    height: int,
    flavour: str,
    punchthrough_alpha: bool = True,
) -> bytearray:
    """Decode DXT1/DXT3/DXT5 block-compressed data to RGBA.

    ``punchthrough_alpha`` only applies to DXT1: when the file declares no
    alpha bits, index 3 of a three-colour block is opaque black rather than
    transparent.
    """
    if flavour not in ("dxt1", "dxt3", "dxt5"):
        raise UnsupportedBLPError(f"unknown DXT flavour {flavour!r}")

    block_bytes = 8 if flavour == "dxt1" else 16
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    expected = blocks_x * blocks_y * block_bytes
    if len(payload) < expected:
        raise BLPError(
            f"truncated {flavour} data: got {len(payload)} bytes, need {expected}"
        )

    out = bytearray(width * height * 4)
    stride = width * 4
    pos = 0

    for by in range(blocks_y):
        for bx in range(blocks_x):
            alpha_values = None

            if flavour == "dxt3":
                alpha_values = [0] * 16
                for i in range(8):
                    byte = payload[pos + i]
                    alpha_values[i * 2] = (byte & 0x0F) * 17
                    alpha_values[i * 2 + 1] = ((byte >> 4) & 0x0F) * 17
                pos += 8
            elif flavour == "dxt5":
                a0 = payload[pos]
                a1 = payload[pos + 1]
                ramp = [a0, a1, 0, 0, 0, 0, 0, 0]
                if a0 > a1:
                    for i in range(1, 7):
                        ramp[i + 1] = ((7 - i) * a0 + i * a1) // 7
                else:
                    for i in range(1, 5):
                        ramp[i + 1] = ((5 - i) * a0 + i * a1) // 5
                    ramp[6] = 0
                    ramp[7] = 255
                bits = int.from_bytes(payload[pos + 2 : pos + 8], "little")
                alpha_values = [ramp[(bits >> (3 * i)) & 0x07] for i in range(16)]
                pos += 8

            c0 = payload[pos] | (payload[pos + 1] << 8)
            c1 = payload[pos + 2] | (payload[pos + 3] << 8)
            # Only DXT1 uses the c0 <= c1 encoding to signal transparency;
            # DXT3/DXT5 blocks are always four-colour.
            table = _dxt_colour_table(c0, c1, allow_punchthrough=(flavour == "dxt1"))
            indices = int.from_bytes(payload[pos + 4 : pos + 8], "little")
            pos += 8

            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    break
                row = y * stride
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    texel = py * 4 + px
                    r, g, b, a = table[(indices >> (2 * texel)) & 0x03]
                    if alpha_values is not None:
                        a = alpha_values[texel]
                    elif not punchthrough_alpha:
                        a = 255
                    j = row + x * 4
                    out[j] = r
                    out[j + 1] = g
                    out[j + 2] = b
                    out[j + 3] = a

    return out


def _decode_jpeg(
    jpeg_header: bytes, payload: bytes, width: int, height: int, opaque: bool
) -> bytearray:
    """Decode the JPEG-compressed BLP1 variant (best effort).

    Blizzard stores a four component JPEG whose channels are B, G, R, A.  This
    is the one path that needs a JPEG decoder; Pillow is imported lazily so the
    rest of the module stays dependency free.
    """
    try:
        from io import BytesIO

        from PIL import Image  # noqa: PLC0415 - optional, only for this variant
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise UnsupportedBLPError(
            "JPEG-compressed BLP requires Pillow to be installed"
        ) from exc

    try:
        image = Image.open(BytesIO(jpeg_header + payload))
        image.load()
    except Exception as exc:  # pragma: no cover - malformed embedded JPEG
        raise BLPError(f"embedded JPEG could not be decoded: {exc}") from exc

    if image.size != (width, height):
        image = image.resize((width, height))

    pixel_count = width * height
    out = bytearray(pixel_count * 4)

    if image.mode == "CMYK":
        raw = image.tobytes()
        if "adobe" in image.info:
            # Pillow inverts Adobe-marked CMYK on load; undo that so the raw
            # BGRA bytes Blizzard wrote come back unchanged.
            raw = bytes(255 - v for v in raw)
        for i in range(pixel_count):
            j = i * 4
            out[j] = raw[j + 2]
            out[j + 1] = raw[j + 1]
            out[j + 2] = raw[j]
            out[j + 3] = 255 if opaque else raw[j + 3]
    else:
        rgba = image.convert("RGBA").tobytes()
        out = bytearray(rgba)
        if opaque:
            for i in range(pixel_count):
                out[i * 4 + 3] = 255

    return out


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def decode(data: bytes, mip_level: int = 0) -> BLPImage:
    """Decode a BLP file held in memory and return its RGBA pixels.

    ``mip_level`` 0 is the full-size image.
    """
    header = read_header(data)
    width, height = mip_dimensions(header, mip_level)
    payload = _mip_data(data, header, mip_level)
    opaque = header.alpha_ignored
    effective_alpha_depth = 0 if opaque else header.alpha_depth

    if header.content == CONTENT_JPEG:
        pixels = _decode_jpeg(header.jpeg_header, payload, width, height, opaque)
    elif header.encoding == ENCODING_PALETTIZED:
        pixels = decode_palettized(
            payload, width, height, header.palette, effective_alpha_depth
        )
    elif header.encoding == ENCODING_DXT:
        flavour = _dxt_flavour(header)
        pixels = decode_dxt(
            payload,
            width,
            height,
            flavour,
            punchthrough_alpha=not opaque,
        )
    elif header.encoding == ENCODING_BGRA8888:
        pixels = decode_bgra8888(payload, width, height)
        if opaque:
            for i in range(width * height):
                pixels[i * 4 + 3] = 255
    else:
        raise UnsupportedBLPError(f"unsupported BLP encoding {header.encoding}")

    return BLPImage(width=width, height=height, pixels=pixels)


def _dxt_flavour(header: BLPHeader) -> str:
    if header.alpha_encoding == ALPHA_ENCODING_DXT1:
        return "dxt1"
    if header.alpha_encoding == ALPHA_ENCODING_DXT3:
        return "dxt3"
    if header.alpha_encoding == ALPHA_ENCODING_DXT5:
        return "dxt5"
    raise UnsupportedBLPError(
        f"unsupported DXT alpha encoding {header.alpha_encoding}"
    )


def open_blp(path, mip_level: int = 0) -> BLPImage:
    """Read ``path`` from disk and decode it to RGBA."""
    with open(path, "rb") as handle:
        data = handle.read()
    return decode(data, mip_level=mip_level)
