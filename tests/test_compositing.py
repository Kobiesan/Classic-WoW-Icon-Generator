"""Tests for the icon compositor and the BLP2 writer."""

from __future__ import annotations

import pytest
from PIL import Image

from wowicons import blp, blp_writer, compositing

GOLD = (196, 160, 64, 255)
RED = (255, 0, 0, 255)
TRANSPARENT = (0, 0, 0, 0)


def border_template(size: int = 64, inset: int = 4, thickness: int = 3) -> Image.Image:
    """An icon-shaped frame: opaque ring, transparent middle, transparent corners."""
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    pixels = image.load()
    inner = inset + thickness
    for y in range(size):
        for x in range(size):
            inside_outer = inset <= x < size - inset and inset <= y < size - inset
            inside_inner = inner <= x < size - inner and inner <= y < size - inner
            if inside_outer and not inside_inner:
                pixels[x, y] = GOLD
    return image


def solid(size: int, colour=RED) -> Image.Image:
    return Image.new("RGBA", (size, size), colour)


@pytest.fixture(autouse=True)
def _clear_cache():
    compositing.clear_mask_cache()
    yield
    compositing.clear_mask_cache()


# ---------------------------------------------------------------------------
# Content mask
# ---------------------------------------------------------------------------


def test_interior_is_reached_from_the_centre():
    mask = compositing.derive_content_mask(border_template())
    assert mask.includes(32, 32)
    assert not mask.has_empty_interior


def test_border_ring_is_included_so_art_survives_under_it():
    mask = compositing.derive_content_mask(border_template())
    assert mask.includes(4, 32)


def test_corners_are_outside_the_mask():
    mask = compositing.derive_content_mask(border_template())
    for x, y in ((0, 0), (63, 0), (0, 63), (63, 63), (2, 2)):
        assert not mask.includes(x, y)


def test_flood_fill_is_four_connected():
    """An 8-connected fill would escape through this diagonal-only gap."""
    image = Image.new("RGBA", (9, 9), TRANSPARENT)
    pixels = image.load()
    for i in range(9):
        pixels[i, 2] = GOLD
        pixels[i, 6] = GOLD
        pixels[2, i] = GOLD
        pixels[6, i] = GOLD
    pixels[2, 2] = TRANSPARENT

    mask = compositing.derive_content_mask(image)

    assert mask.includes(4, 4)
    assert not mask.includes(1, 1)
    assert not mask.includes(0, 0)


def test_opaque_centre_is_reported():
    mask = compositing.derive_content_mask(solid(8, GOLD))
    assert mask.has_empty_interior
    assert mask.interior_pixels == 0


def test_mask_cache_reuses_identical_templates(monkeypatch):
    calls = []
    original = compositing.derive_content_mask

    def counting(template, threshold=compositing.DEFAULT_OPAQUE_THRESHOLD):
        calls.append(1)
        return original(template, threshold)

    monkeypatch.setattr(compositing, "derive_content_mask", counting)

    compositing.content_mask_for(border_template())
    compositing.content_mask_for(border_template())

    assert len(calls) == 1


def test_mask_cache_separates_different_templates():
    a = compositing.content_mask_for(border_template(inset=4))
    b = compositing.content_mask_for(border_template(inset=6))
    assert a.included != b.included


# ---------------------------------------------------------------------------
# Compositing
# ---------------------------------------------------------------------------


def test_corners_are_fully_transparent():
    icon = compositing.composite_icon(
        solid(512), border_template(), compositing.CompositeOptions(sharpen_amount=0)
    )
    for x, y in ((0, 0), (63, 0), (0, 63), (63, 63)):
        assert icon.getpixel((x, y))[3] == 0


def test_interior_shows_the_art():
    icon = compositing.composite_icon(
        solid(512), border_template(), compositing.CompositeOptions(sharpen_amount=0)
    )
    r, g, b, a = icon.getpixel((32, 32))
    assert a == 255
    assert r > 200 and g < 60


def test_border_is_drawn_over_the_art():
    icon = compositing.composite_icon(
        solid(512), border_template(), compositing.CompositeOptions(sharpen_amount=0)
    )
    assert icon.getpixel((5, 32))[:3] == GOLD[:3]


def test_output_matches_the_template_size():
    icon = compositing.composite_icon(solid(512), border_template(size=32))
    assert icon.size == (32, 32)


def test_sharpening_does_not_disturb_the_corners():
    icon = compositing.composite_icon(
        solid(512), border_template(), compositing.CompositeOptions(sharpen_amount=2.0)
    )
    assert icon.getpixel((0, 0))[3] == 0


def test_art_is_not_mutated():
    art = solid(64)
    before = art.tobytes()
    compositing.composite_icon(art, border_template())
    assert art.tobytes() == before


def test_unsharp_leaves_alpha_alone():
    art = Image.new("RGBA", (16, 16))
    pixels = art.load()
    for y in range(16):
        for x in range(16):
            pixels[x, y] = (200, 100, 50, (x + y * 16) % 256)

    sharpened = compositing.unsharp_mask(art, amount=2.0)

    assert sharpened.getchannel("A").tobytes() == art.getchannel("A").tobytes()


def test_zero_sharpen_returns_a_copy():
    art = solid(16)
    result = compositing.unsharp_mask(art, amount=0.0)
    assert result.tobytes() == art.tobytes()
    assert result is not art


@pytest.mark.parametrize("amount", [-0.1, 99.0])
def test_out_of_range_sharpen_is_rejected(amount):
    with pytest.raises(ValueError):
        compositing.unsharp_mask(solid(8), amount=amount)


# ---------------------------------------------------------------------------
# BLP writer
# ---------------------------------------------------------------------------


def gradient(size: int, alpha: int = 255) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            pixels[x, y] = (
                x * 255 // max(1, size - 1),
                y * 255 // max(1, size - 1),
                (x + y) * 255 // max(1, (size - 1) * 2),
                alpha,
            )
    return image


def few_colours(size: int = 64) -> Image.Image:
    palette = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), GOLD, (10, 20, 30, 255)]
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            pixels[x, y] = palette[(x + y) % len(palette)]
    return image


def test_blp_round_trips_within_tolerance():
    source = gradient(64)
    data = blp_writer.encode_blp2(source.tobytes(), 64, 64)

    decoded = blp.decode(data)

    assert decoded.width == 64 and decoded.height == 64
    raw = source.tobytes()
    errors = [
        abs(decoded.pixels[i + channel] - raw[i + channel])
        for i in range(0, len(decoded.pixels), 4)
        for channel in range(3)
    ]
    mean = sum(errors) / len(errors)

    # A 64x64 RGB gradient is 4096 distinct colours squeezed into 256, so some
    # error is inherent. Mean is the meaningful number; the worst-case bound is
    # loose because median cut's outcome depends on histogram iteration order,
    # which differs between this and the C# writer even though the algorithm is
    # the same.
    assert mean < 5.0, f"mean per-channel error {mean:.2f}"
    assert max(errors) <= 16, f"worst per-channel error {max(errors)}"


def test_few_colours_round_trip_exactly():
    source = few_colours()
    decoded = blp.decode(blp_writer.encode_blp2(source.tobytes(), 64, 64))
    assert bytes(decoded.pixels) == source.tobytes()


def test_alpha_is_preserved_exactly():
    source = Image.new("RGBA", (16, 16))
    pixels = source.load()
    for y in range(16):
        for x in range(16):
            pixels[x, y] = (200, 100, 50, (x + y * 16) % 256)

    decoded = blp.decode(blp_writer.encode_blp2(source.tobytes(), 16, 16))

    for i in range(0, len(decoded.pixels), 4):
        assert decoded.pixels[i + 3] == source.tobytes()[i + 3]


def test_full_mip_chain_is_written():
    data = blp_writer.encode_blp2(gradient(64).tobytes(), 64, 64)
    header = blp.read_header(data)

    assert header.mip_count == 7
    size = 64
    for level in range(7):
        mip = blp.decode(data, mip_level=level)
        assert mip.width == size
        size //= 2


def test_mipmaps_can_be_disabled():
    data = blp_writer.encode_blp2(gradient(64).tobytes(), 64, 64, generate_mipmaps=False)
    assert blp.read_header(data).mip_count == 1


def test_header_declares_palettized_with_eight_bit_alpha():
    header = blp.read_header(blp_writer.encode_blp2(gradient(64).tobytes(), 64, 64))
    assert header.version == 2
    assert header.encoding == blp.ENCODING_PALETTIZED
    assert header.alpha_depth == 8
    assert not header.alpha_ignored


def test_transparent_pixels_do_not_spend_palette_entries():
    image = Image.new("RGBA", (8, 8))
    pixels = image.load()
    for y in range(8):
        for x in range(8):
            pixels[x, y] = (255, 0, 255, 0) if y < 4 else (x * 30, 40, 50, 255)

    palette = blp_writer.build_palette(image.tobytes())

    assert (255, 0, 255) not in palette


def test_downsample_weights_colour_by_alpha():
    """A plain average would give grey; weighting by alpha keeps it white."""
    image = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    image.putpixel((0, 0), (255, 255, 255, 255))

    pixels, width, height = blp_writer.downsample(image.tobytes(), 2, 2)

    assert (width, height) == (1, 1)
    assert pixels[0] == 255
    assert pixels[3] == 64      # (255 + 0 + 0 + 0) / 4


def test_composited_icon_round_trips_with_transparent_corners():
    icon = compositing.composite_icon(
        gradient(512), border_template(), compositing.CompositeOptions(sharpen_amount=0)
    )
    decoded = blp.decode(blp_writer.encode_blp2(icon.tobytes(), 64, 64))

    assert decoded.getpixel(0, 0)[3] == 0
    assert decoded.getpixel(32, 32)[3] == 255


def test_oversized_image_is_rejected():
    with pytest.raises(ValueError, match="mip levels"):
        blp_writer.encode_blp2(bytes(4 * (1 << 16)), 1 << 16, 1)


def test_wrong_buffer_length_is_rejected():
    with pytest.raises(ValueError, match="expected"):
        blp_writer.encode_blp2(b"\x00" * 10, 8, 8)
