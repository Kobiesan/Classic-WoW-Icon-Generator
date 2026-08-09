"""Tests for the pure-Python BLP1/BLP2 decoder."""

from __future__ import annotations

import struct

import pytest

from wowicons import blp

from .blp_builders import (
    BLUE,
    GREEN,
    RED,
    build_blp1_jpeg,
    build_blp1_palettized,
    build_blp2,
    dxt1_block,
    dxt3_block,
    dxt5_block,
    flatten_rgba,
    solid_blp1_icon,
    solid_blp2_dxt1_icon,
)


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


def test_rejects_non_blp_data():
    with pytest.raises(blp.BLPError, match="not a BLP"):
        blp.decode(b"PNG\x00" + b"\x00" * 400)


def test_rejects_short_file():
    with pytest.raises(blp.BLPError, match="too short"):
        blp.decode(b"BLP")


def test_rejects_truncated_header():
    data = solid_blp1_icon(4)
    with pytest.raises(blp.BLPError, match="truncated"):
        blp.decode(data[:100])


def test_rejects_absurd_dimensions():
    data = bytearray(solid_blp1_icon(4))
    struct.pack_into("<I", data, 12, 999999)  # width
    with pytest.raises(blp.BLPError, match="implausible"):
        blp.decode(bytes(data))


def test_blp1_header_fields():
    header = blp.read_header(solid_blp1_icon(64))
    assert header.version == 1
    assert header.width == 64 and header.height == 64
    assert header.encoding == blp.ENCODING_PALETTIZED
    assert header.mip_count == 1


def test_blp2_header_fields():
    header = blp.read_header(solid_blp2_dxt1_icon(64))
    assert header.version == 2
    assert header.encoding == blp.ENCODING_DXT
    assert header.alpha_encoding == blp.ALPHA_ENCODING_DXT1
    assert len(header.palette) == 256


def test_mip_dimensions_halve():
    header = blp.read_header(solid_blp1_icon(64))
    assert blp.mip_dimensions(header, 0) == (64, 64)
    assert blp.mip_dimensions(header, 2) == (16, 16)


# ---------------------------------------------------------------------------
# BLP1 palettized
# ---------------------------------------------------------------------------


def test_blp1_palettized_opaque():
    data = build_blp1_palettized(2, 2, [0, 1, 2, 0], [RED, GREEN, BLUE])
    image = blp.decode(data)
    assert image.size == (2, 2)
    assert flatten_rgba(image) == [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 0, 0, 255),
    ]


def test_blp1_palette_is_read_as_bgra():
    """A palette entry written B,G,R must come back as R,G,B."""
    data = build_blp1_palettized(1, 1, [0], [(10, 20, 30)])
    assert blp.decode(data).getpixel(0, 0) == (10, 20, 30, 255)


def test_blp1_alpha_depth_8():
    data = build_blp1_palettized(
        2, 1, [0, 0], [RED], alpha_depth=8, alpha_payload=bytes([0, 128])
    )
    image = blp.decode(data)
    assert image.getpixel(0, 0)[3] == 0
    assert image.getpixel(1, 0)[3] == 128


def test_blp1_alpha_depth_1_is_bit_packed_lsb_first():
    # Pixels 0 and 2 opaque, 1 and 3 transparent -> 0b0101 == 0x05.
    data = build_blp1_palettized(
        4, 1, [0] * 4, [RED], alpha_depth=1, alpha_payload=bytes([0x05])
    )
    alphas = [pixel[3] for pixel in flatten_rgba(blp.decode(data))]
    assert alphas == [255, 0, 255, 0]


def test_blp1_alpha_depth_4_low_nibble_first():
    data = build_blp1_palettized(
        2, 1, [0, 0], [RED], alpha_depth=4, alpha_payload=bytes([0xF0])
    )
    alphas = [pixel[3] for pixel in flatten_rgba(blp.decode(data))]
    assert alphas == [0, 255]


def test_blp1_picture_type_5_ignores_alpha():
    """picture_type 5 means the alpha bits present in the file are unused."""
    data = build_blp1_palettized(
        2,
        1,
        [0, 0],
        [RED],
        alpha_depth=8,
        alpha_payload=bytes([0, 0]),
        picture_type=5,
    )
    alphas = [pixel[3] for pixel in flatten_rgba(blp.decode(data))]
    assert alphas == [255, 255]


def test_blp1_truncated_alpha_is_reported():
    data = build_blp1_palettized(
        4, 4, [0] * 16, [RED], alpha_depth=8, alpha_payload=b"\x00"
    )
    with pytest.raises(blp.BLPError, match="truncated 8-bit alpha"):
        blp.decode(data)


def test_blp1_truncated_indices_are_reported():
    data = build_blp1_palettized(4, 4, [0] * 4, [RED])
    with pytest.raises(blp.BLPError, match="truncated palette index"):
        blp.decode(data)


def test_unknown_blp1_content_type_is_unsupported():
    data = bytearray(solid_blp1_icon(4))
    struct.pack_into("<I", data, 4, 9)
    with pytest.raises(blp.UnsupportedBLPError):
        blp.decode(bytes(data))


# ---------------------------------------------------------------------------
# BLP2 palettized / BGRA
# ---------------------------------------------------------------------------


def test_blp2_palettized():
    payload = bytes([0, 1, 1, 0])
    data = build_blp2(
        2,
        2,
        payload,
        encoding=blp.ENCODING_PALETTIZED,
        palette=[RED, GREEN],
    )
    assert flatten_rgba(blp.decode(data)) == [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 255, 0, 255),
        (255, 0, 0, 255),
    ]


def test_blp2_palettized_with_8_bit_alpha():
    payload = bytes([0, 0]) + bytes([255, 64])
    data = build_blp2(
        2,
        1,
        payload,
        encoding=blp.ENCODING_PALETTIZED,
        alpha_depth=8,
        palette=[BLUE],
    )
    assert flatten_rgba(blp.decode(data)) == [(0, 0, 255, 255), (0, 0, 255, 64)]


def test_blp2_bgra8888():
    payload = bytes([30, 20, 10, 200])  # B, G, R, A
    data = build_blp2(
        1, 1, payload, encoding=blp.ENCODING_BGRA8888, alpha_depth=8
    )
    assert blp.decode(data).getpixel(0, 0) == (10, 20, 30, 200)


def test_blp2_bgra8888_without_alpha_bits_is_opaque():
    payload = bytes([30, 20, 10, 3])
    data = build_blp2(
        1, 1, payload, encoding=blp.ENCODING_BGRA8888, alpha_depth=0
    )
    assert blp.decode(data).getpixel(0, 0) == (10, 20, 30, 255)


def test_unknown_blp2_encoding_is_unsupported():
    data = build_blp2(1, 1, b"\x00" * 4, encoding=7)
    with pytest.raises(blp.UnsupportedBLPError, match="encoding 7"):
        blp.decode(data)


# ---------------------------------------------------------------------------
# DXT
# ---------------------------------------------------------------------------


def _decode_single_dxt_block(payload: bytes, alpha_encoding: int, alpha_depth=0):
    data = build_blp2(
        4,
        4,
        payload,
        encoding=blp.ENCODING_DXT,
        alpha_depth=alpha_depth,
        alpha_encoding=alpha_encoding,
    )
    return blp.decode(data)


def test_dxt1_endpoint_colours():
    # indices: texel 0 -> c0, texel 1 -> c1, texel 2 -> 2/3 c0, texel 3 -> 1/3 c0
    indices = 0b11100100
    image = _decode_single_dxt_block(
        dxt1_block(indices=indices), blp.ALPHA_ENCODING_DXT1
    )
    pixels = flatten_rgba(image)
    assert pixels[0] == (255, 0, 0, 255)
    assert pixels[1] == (0, 0, 255, 255)
    assert pixels[2] == (170, 0, 85, 255)
    assert pixels[3] == (85, 0, 170, 255)


def test_dxt1_punchthrough_alpha_when_c0_le_c1():
    # c0 <= c1 selects the three-colour block, where index 3 is transparent.
    block = dxt1_block(c0=0x001F, c1=0xF800, indices=0b11 << 6)
    image = _decode_single_dxt_block(
        block, blp.ALPHA_ENCODING_DXT1, alpha_depth=1
    )
    assert image.getpixel(3, 0) == (0, 0, 0, 0)


def test_dxt1_index_3_is_opaque_black_without_alpha_bits():
    block = dxt1_block(c0=0x001F, c1=0xF800, indices=0b11 << 6)
    image = _decode_single_dxt_block(
        block, blp.ALPHA_ENCODING_DXT1, alpha_depth=0
    )
    assert image.getpixel(3, 0) == (0, 0, 0, 255)


def test_dxt3_explicit_alpha_nibbles():
    # texel 0 -> 0x0, texel 1 -> 0xF, rest 0x8.
    nibbles = 0x8888888888888888
    nibbles = (nibbles & ~0xFF) | 0xF0
    image = _decode_single_dxt_block(
        dxt3_block(alpha_nibbles=nibbles),
        blp.ALPHA_ENCODING_DXT3,
        alpha_depth=8,
    )
    alphas = [pixel[3] for pixel in flatten_rgba(image)]
    assert alphas[0] == 0
    assert alphas[1] == 255
    assert alphas[2] == 8 * 17


def test_dxt5_interpolated_alpha_ramp():
    # a0 > a1 -> eight-step ramp; index 0 == a0, index 1 == a1.
    image = _decode_single_dxt_block(
        dxt5_block(a0=255, a1=0, alpha_indices=0b001),
        blp.ALPHA_ENCODING_DXT5,
        alpha_depth=8,
    )
    alphas = [pixel[3] for pixel in flatten_rgba(image)]
    assert alphas[0] == 0
    assert alphas[1] == 255


def test_dxt3_and_dxt5_colour_blocks_never_punch_through():
    """c0 <= c1 must still mean four opaque colours for DXT3/DXT5."""
    block = dxt5_block(a0=255, a1=255, c0=0x001F, c1=0xF800, indices=0b11 << 6)
    image = _decode_single_dxt_block(
        block, blp.ALPHA_ENCODING_DXT5, alpha_depth=8
    )
    r, g, b, a = image.getpixel(3, 0)
    assert a == 255
    assert (r, g, b) != (0, 0, 0)


def test_dxt_handles_dimensions_not_divisible_by_four():
    data = build_blp2(
        3,
        2,
        dxt1_block(),
        encoding=blp.ENCODING_DXT,
        alpha_encoding=blp.ALPHA_ENCODING_DXT1,
    )
    image = blp.decode(data)
    assert image.size == (3, 2)
    assert all(pixel == (255, 0, 0, 255) for pixel in flatten_rgba(image))


def test_truncated_dxt_payload_is_reported():
    data = build_blp2(
        8,
        8,
        dxt1_block(),
        encoding=blp.ENCODING_DXT,
        alpha_encoding=blp.ALPHA_ENCODING_DXT1,
    )
    with pytest.raises(blp.BLPError, match="truncated dxt1"):
        blp.decode(data)


def test_unsupported_dxt_alpha_encoding():
    data = build_blp2(
        4,
        4,
        dxt1_block(),
        encoding=blp.ENCODING_DXT,
        alpha_encoding=4,
    )
    with pytest.raises(blp.UnsupportedBLPError, match="alpha encoding 4"):
        blp.decode(data)


# ---------------------------------------------------------------------------
# JPEG-compressed BLP1
# ---------------------------------------------------------------------------


def _cmyk_jpeg(size, bgra):
    """A four-channel JPEG whose *stored* samples are the given BGRA values.

    Pillow writes CMYK JPEGs with an Adobe marker and inverts the samples on
    the way out, so the source pixel has to be inverted here for the bytes
    libjpeg actually stores to be the BGRA quad we want back.
    """
    from io import BytesIO

    from PIL import Image

    source = Image.new("CMYK", size, tuple(255 - value for value in bgra))
    buffer = BytesIO()
    source.save(buffer, format="JPEG", quality=100, subsampling=0)
    return buffer.getvalue()


@pytest.mark.parametrize("shared_header_len", [0, 200], ids=["whole", "split"])
def test_blp1_jpeg_variant(shared_header_len):
    jpeg = _cmyk_jpeg((8, 8), (30, 20, 10, 255))  # B, G, R, A
    data = build_blp1_jpeg(8, 8, jpeg, shared_header_len=shared_header_len)

    image = blp.decode(data)
    assert image.size == (8, 8)

    r, g, b, a = image.getpixel(4, 4)
    assert abs(r - 10) <= 6 and abs(g - 20) <= 6 and abs(b - 30) <= 6
    assert a >= 249


def test_blp1_jpeg_picture_type_5_forces_opaque():
    jpeg = _cmyk_jpeg((8, 8), (30, 20, 10, 0))
    data = build_blp1_jpeg(8, 8, jpeg, picture_type=5)
    assert blp.decode(data).getpixel(4, 4)[3] == 255


def test_blp1_jpeg_truncated_shared_header_is_reported():
    jpeg = _cmyk_jpeg((8, 8), (30, 20, 10, 255))
    data = build_blp1_jpeg(8, 8, jpeg, shared_header_len=200)
    with pytest.raises(blp.BLPError, match="truncated"):
        blp.decode(data[: blp.BLP1_HEADER_SIZE + 40])


def test_blp1_jpeg_garbage_payload_is_reported():
    data = build_blp1_jpeg(8, 8, b"\xff\xd8not-a-jpeg")
    with pytest.raises(blp.BLPError, match="JPEG"):
        blp.decode(data)


# ---------------------------------------------------------------------------
# Whole-icon sanity checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder", [solid_blp1_icon, solid_blp2_dxt1_icon], ids=["blp1", "blp2-dxt1"]
)
def test_full_size_icon_decodes(builder):
    image = blp.decode(builder(64))
    assert image.size == (64, 64)
    assert len(image.pixels) == 64 * 64 * 4
    assert all(pixel == (255, 0, 0, 255) for pixel in flatten_rgba(image))


def test_open_blp_reads_from_disk(tmp_path):
    path = tmp_path / "INV_Sword_04.blp"
    path.write_bytes(solid_blp1_icon(64, GREEN))
    image = blp.open_blp(path)
    assert image.getpixel(0, 0) == (0, 255, 0, 255)


def test_decoder_needs_no_third_party_imports():
    """blp.py must stay portable: stdlib only at module import time."""
    import ast
    from pathlib import Path

    source = Path(blp.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_imports = set()
    for node in tree.body:  # module level only; the JPEG path imports lazily
        if isinstance(node, ast.Import):
            top_level_imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_imports.add(node.module.split(".")[0])

    assert top_level_imports <= {"__future__", "struct", "dataclasses", "typing"}
