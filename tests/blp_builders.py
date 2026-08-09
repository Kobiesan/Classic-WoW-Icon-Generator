"""Builders that synthesize valid BLP1/BLP2 byte streams for the tests.

Keeping these in the test suite means the decoder is exercised against real
header layouts and real block-compressed payloads without committing binary
fixtures (or client files) to the repository.
"""

from __future__ import annotations

import struct
from typing import Iterable, List, Optional, Sequence, Tuple

from wowicons import blp

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# RGB565 encodings used by the DXT builders.
C_RED_565 = 0xF800
C_BLUE_565 = 0x001F


def _palette_bytes(colours: Sequence[Tuple[int, int, int]]) -> bytes:
    """Pack up to 256 RGB colours into the BGRA palette block."""
    out = bytearray(blp.PALETTE_SIZE)
    for i, (r, g, b) in enumerate(colours):
        out[i * 4 + 0] = b
        out[i * 4 + 1] = g
        out[i * 4 + 2] = r
        out[i * 4 + 3] = 0
    return bytes(out)


def _mip_tables(first_offset: int, first_size: int) -> Tuple[bytes, bytes]:
    offsets = [first_offset] + [0] * 15
    sizes = [first_size] + [0] * 15
    return struct.pack("<16I", *offsets), struct.pack("<16I", *sizes)


def build_blp1_palettized(
    width: int,
    height: int,
    indices: Iterable[int],
    palette: Sequence[Tuple[int, int, int]],
    alpha_depth: int = 0,
    alpha_payload: bytes = b"",
    picture_type: int = 4,
) -> bytes:
    """Build an uncompressed (palettized) BLP1."""
    payload = bytes(bytearray(indices)) + alpha_payload
    data_offset = blp.BLP1_HEADER_SIZE + blp.PALETTE_SIZE
    mip_offsets, mip_sizes = _mip_tables(data_offset, len(payload))

    header = struct.pack(
        "<4sIIIIII",
        blp.MAGIC_BLP1,
        blp.CONTENT_DIRECT,
        alpha_depth,
        width,
        height,
        picture_type,
        0,
    )
    return header + mip_offsets + mip_sizes + _palette_bytes(palette) + payload


def build_blp1_jpeg(
    width: int,
    height: int,
    jpeg_bytes: bytes,
    shared_header_len: int = 0,
    alpha_depth: int = 8,
    picture_type: int = 4,
) -> bytes:
    """Build a JPEG-compressed BLP1.

    Blizzard splits every mip's JPEG stream into a shared header stored once
    after the BLP header, plus a per-mip tail; ``shared_header_len`` chooses
    where to cut so the decoder's re-concatenation is actually exercised.
    """
    shared_header = jpeg_bytes[:shared_header_len]
    payload = jpeg_bytes[shared_header_len:]
    data_offset = blp.BLP1_HEADER_SIZE + 4 + len(shared_header)
    mip_offsets, mip_sizes = _mip_tables(data_offset, len(payload))

    header = struct.pack(
        "<4sIIIIII",
        blp.MAGIC_BLP1,
        blp.CONTENT_JPEG,
        alpha_depth,
        width,
        height,
        picture_type,
        0,
    )
    return (
        header
        + mip_offsets
        + mip_sizes
        + struct.pack("<I", len(shared_header))
        + shared_header
        + payload
    )


def build_blp2(
    width: int,
    height: int,
    payload: bytes,
    encoding: int,
    alpha_depth: int = 0,
    alpha_encoding: int = 0,
    palette: Optional[Sequence[Tuple[int, int, int]]] = None,
) -> bytes:
    """Build a BLP2 with a single mip level."""
    data_offset = blp.BLP2_HEADER_SIZE + blp.PALETTE_SIZE
    mip_offsets, mip_sizes = _mip_tables(data_offset, len(payload))

    header = struct.pack(
        "<4sIBBBB",
        blp.MAGIC_BLP2,
        blp.CONTENT_DIRECT,
        encoding,
        alpha_depth,
        alpha_encoding,
        0,
    )
    header += struct.pack("<II", width, height)
    return (
        header
        + mip_offsets
        + mip_sizes
        + _palette_bytes(palette or [])
        + payload
    )


def dxt1_block(c0: int = C_RED_565, c1: int = C_BLUE_565, indices: int = 0) -> bytes:
    """One 4x4 DXT1 block: two RGB565 endpoints plus 16 2-bit indices."""
    return struct.pack("<HHI", c0, c1, indices)


def dxt3_block(
    alpha_nibbles: int = 0xFFFFFFFFFFFFFFFF,
    c0: int = C_RED_565,
    c1: int = C_BLUE_565,
    indices: int = 0,
) -> bytes:
    """One 4x4 DXT3 block: 64 bits of 4-bit alpha, then a colour block."""
    return struct.pack("<Q", alpha_nibbles) + dxt1_block(c0, c1, indices)


def dxt5_block(
    a0: int = 255,
    a1: int = 0,
    alpha_indices: int = 0,
    c0: int = C_RED_565,
    c1: int = C_BLUE_565,
    indices: int = 0,
) -> bytes:
    """One 4x4 DXT5 block: interpolated alpha ramp, then a colour block."""
    alpha = bytes([a0, a1]) + alpha_indices.to_bytes(6, "little")
    return alpha + dxt1_block(c0, c1, indices)


def solid_blp1_icon(
    size: int = 64, colour: Tuple[int, int, int] = RED, name_hint: str = ""
) -> bytes:
    """A ``size`` x ``size`` opaque single-colour BLP1, like a real icon."""
    del name_hint  # documentation only
    indices = [0] * (size * size)
    return build_blp1_palettized(size, size, indices, [colour], alpha_depth=0)


def solid_blp2_dxt1_icon(size: int = 64) -> bytes:
    """A ``size`` x ``size`` DXT1 BLP2 filled with the first endpoint colour."""
    blocks = (size // 4) * (size // 4)
    payload = dxt1_block() * blocks
    return build_blp2(
        size,
        size,
        payload,
        encoding=blp.ENCODING_DXT,
        alpha_depth=0,
        alpha_encoding=blp.ALPHA_ENCODING_DXT1,
    )


def flatten_rgba(image: blp.BLPImage) -> List[Tuple[int, int, int, int]]:
    """All pixels as RGBA tuples, for easy assertions."""
    return [
        tuple(image.pixels[i : i + 4]) for i in range(0, len(image.pixels), 4)
    ]
