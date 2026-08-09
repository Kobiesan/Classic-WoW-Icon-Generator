"""End-to-end tests for the dataset pipeline and CLI."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PIL import Image

from wowicons.cli import main
from wowicons.pipeline import (
    DatasetOptions,
    build_dataset,
    find_blp_files,
    format_category_counts,
)

from .blp_builders import BLUE, GREEN, RED, solid_blp1_icon, solid_blp2_dxt1_icon


@pytest.fixture()
def icon_dir(tmp_path: Path) -> Path:
    """A miniature Interface/Icons tree, including a sub-directory."""
    root = tmp_path / "Icons"
    (root / "Spell").mkdir(parents=True)
    (root / "INV_Sword_04.blp").write_bytes(solid_blp1_icon(64, RED))
    (root / "INV_Potion_51.blp").write_bytes(solid_blp1_icon(64, GREEN))
    (root / "Trade_Alchemy.blp").write_bytes(solid_blp2_dxt1_icon(64))
    (root / "Spell" / "Spell_Fire_Fireball02.blp").write_bytes(
        solid_blp1_icon(64, BLUE)
    )
    (root / "notes.txt").write_text("ignored", encoding="utf-8")
    return root


def make_options(icon_dir: Path, tmp_path: Path, **kwargs) -> DatasetOptions:
    defaults = dict(input_dir=icon_dir, output_dir=tmp_path / "dataset")
    defaults.update(kwargs)
    return DatasetOptions(**defaults)


def test_find_blp_files_is_recursive_and_ignores_other_files(icon_dir):
    found = list(find_blp_files(icon_dir))
    assert len(found) == 4
    assert all(path.suffix == ".blp" for path in found)
    assert any(path.parent.name == "Spell" for path in found)


def test_build_dataset_writes_kohya_layout(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path)
    stats = build_dataset(options)

    assert stats.total_found == 4
    assert stats.written == 4
    assert not stats.failures

    image_dir = options.output_dir / "img" / "10_wowicon icon"
    assert image_dir.is_dir()
    assert (options.output_dir / "model").is_dir()
    assert (options.output_dir / "log").is_dir()

    pngs = sorted(path.name for path in image_dir.glob("*.png"))
    assert pngs == [
        "INV_Potion_51.png",
        "INV_Sword_04.png",
        "Spell_Fire_Fireball02.png",
        "Trade_Alchemy.png",
    ]
    for png in image_dir.glob("*.png"):
        assert png.with_suffix(".txt").is_file()


def test_images_are_upscaled_to_512_rgb(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path)
    build_dataset(options)
    with Image.open(options.image_dir / "INV_Sword_04.png") as image:
        assert image.size == (512, 512)
        assert image.mode == "RGB"
        assert image.getpixel((256, 256)) == (255, 0, 0)


def test_transparent_pixels_are_flattened_onto_the_background(icon_dir, tmp_path):
    """Trainers want RGB; transparent icon borders must become the background,
    not a grey halo left over from resizing unpremultiplied alpha."""
    from .blp_builders import build_blp1_palettized

    half = bytes([255] * 2048 + [0] * 2048)
    (icon_dir / "INV_Sword_39.blp").write_bytes(
        build_blp1_palettized(
            64, 64, [0] * 4096, [RED], alpha_depth=8, alpha_payload=half
        )
    )
    options = make_options(icon_dir, tmp_path)
    build_dataset(options)

    with Image.open(options.image_dir / "INV_Sword_39.png") as image:
        assert image.mode == "RGB"
        assert image.getpixel((256, 100)) == (255, 0, 0)  # opaque top half
        assert image.getpixel((256, 400)) == (0, 0, 0)  # transparent bottom


def test_size_flag_changes_output_resolution(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path, size=256)
    build_dataset(options)
    with Image.open(options.image_dir / "INV_Sword_04.png") as image:
        assert image.size == (256, 256)


def test_caption_files_hold_the_parsed_caption(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path)
    build_dataset(options)
    caption = (options.image_dir / "Spell_Fire_Fireball02.txt").read_text(
        encoding="utf-8"
    )
    assert caption.strip() == "wowicon, fire spell, fireball"


def test_overrides_reach_the_caption_files(icon_dir, tmp_path):
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        '{"Spell_Fire_*": {"add_terms": ["flames"]}}', encoding="utf-8"
    )
    options = make_options(icon_dir, tmp_path, overrides_path=overrides)
    build_dataset(options)
    caption = (options.image_dir / "Spell_Fire_Fireball02.txt").read_text(
        encoding="utf-8"
    )
    assert caption.strip() == "wowicon, fire spell, fireball, flames"


def test_manifest_columns_and_rows(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path)
    build_dataset(options)

    with open(options.output_dir / "manifest.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert list(rows[0]) == ["source_path", "output_path", "caption", "category"]
    assert len(rows) == 4

    by_caption = {Path(row["source_path"]).name: row for row in rows}
    sword = by_caption["INV_Sword_04.blp"]
    assert sword["category"] == "weapon"
    assert sword["caption"] == "wowicon, weapon, sword"
    assert Path(sword["output_path"]).is_file()


def test_min_size_skips_small_icons(icon_dir, tmp_path):
    (icon_dir / "INV_Misc_Rune_01.blp").write_bytes(solid_blp1_icon(32, RED))
    options = make_options(icon_dir, tmp_path, min_size=64)
    stats = build_dataset(options)

    assert stats.written == 4
    assert [path.name for path, _ in stats.skipped_small] == ["INV_Misc_Rune_01.blp"]
    assert stats.skipped_small[0][1] == (32, 32)
    assert not (options.image_dir / "INV_Misc_Rune_01.png").exists()


def test_lower_min_size_keeps_small_icons(icon_dir, tmp_path):
    (icon_dir / "INV_Misc_Rune_01.blp").write_bytes(solid_blp1_icon(32, RED))
    stats = build_dataset(make_options(icon_dir, tmp_path, min_size=16))
    assert stats.written == 5
    assert not stats.skipped_small


def test_undecodable_files_are_recorded_not_fatal(icon_dir, tmp_path):
    (icon_dir / "INV_Broken_01.blp").write_bytes(b"not a blp at all")
    stats = build_dataset(make_options(icon_dir, tmp_path))

    assert stats.written == 4
    assert len(stats.failures) == 1
    source, reason = stats.failures[0]
    assert source.name == "INV_Broken_01.blp"
    assert "BLPError" in reason


def test_duplicate_stems_in_different_folders_do_not_collide(icon_dir, tmp_path):
    (icon_dir / "Spell" / "INV_Sword_04.blp").write_bytes(solid_blp1_icon(64, BLUE))
    options = make_options(icon_dir, tmp_path)
    stats = build_dataset(options)

    assert stats.written == 5
    names = sorted(path.name for path in options.image_dir.glob("*.png"))
    assert "INV_Sword_04.png" in names
    assert "INV_Sword_04__2.png" in names


def test_dry_run_writes_nothing_but_still_counts(icon_dir, tmp_path):
    options = make_options(icon_dir, tmp_path, dry_run=True)
    stats = build_dataset(options)

    assert stats.written == 4
    assert not options.output_dir.exists()


def test_category_counts(icon_dir, tmp_path):
    stats = build_dataset(make_options(icon_dir, tmp_path))
    assert dict(stats.categories) == {
        "weapon": 1,
        "consumable": 1,
        "profession": 1,
        "fire spell": 1,
    }


def test_repeats_and_tokens_shape_the_folder_name(icon_dir, tmp_path):
    options = make_options(
        icon_dir,
        tmp_path,
        repeats=25,
        instance_token="wowicon2",
        class_token="game icon",
    )
    build_dataset(options)
    assert options.image_dir.name == "25_wowicon2 game icon"
    assert options.image_dir.is_dir()
    caption = (options.image_dir / "INV_Sword_04.txt").read_text(encoding="utf-8")
    assert caption.startswith("wowicon2, ")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_format_category_counts_sorts_by_frequency():
    from collections import Counter

    report = format_category_counts(Counter({"weapon": 3, "armor": 10, "spell": 1}))
    lines = report.splitlines()
    assert "3 categories" in lines[0]
    assert lines[1].strip().startswith("armor")
    assert lines[2].strip().startswith("weapon")
    assert "71.4%" in lines[1]


def test_format_category_counts_handles_empty():
    from collections import Counter

    assert "no categories" in format_category_counts(Counter())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_happy_path(icon_dir, tmp_path, capsys):
    output = tmp_path / "out"
    code = main(["--input", str(icon_dir), "--output", str(output)])
    captured = capsys.readouterr()

    assert code == 0
    assert "Category counts" in captured.out
    assert (output / "manifest.csv").is_file()
    assert (output / "img" / "10_wowicon icon" / "INV_Sword_04.png").is_file()


def test_cli_accepts_overrides_file(icon_dir, tmp_path, capsys):
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"INV_Sword_*": "longsword"}', encoding="utf-8")
    output = tmp_path / "out"
    code = main(
        [
            "--input",
            str(icon_dir),
            "--output",
            str(output),
            "--overrides",
            str(overrides),
            "--min-size",
            "64",
        ]
    )
    assert code == 0
    assert "Loaded 1 caption overrides" in capsys.readouterr().out
    caption = (output / "img" / "10_wowicon icon" / "INV_Sword_04.txt").read_text(
        encoding="utf-8"
    )
    assert caption.strip() == "wowicon, weapon, longsword"


def test_cli_rejects_missing_input(tmp_path, capsys):
    code = main(["--input", str(tmp_path / "nope"), "--output", str(tmp_path / "o")])
    assert code == 2
    assert "not a directory" in capsys.readouterr().err


def test_cli_rejects_missing_overrides(icon_dir, tmp_path, capsys):
    code = main(
        [
            "--input",
            str(icon_dir),
            "--output",
            str(tmp_path / "o"),
            "--overrides",
            str(tmp_path / "missing.json"),
        ]
    )
    assert code == 2
    assert "does not exist" in capsys.readouterr().err


def test_cli_reports_invalid_overrides(icon_dir, tmp_path, capsys):
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"INV_*": {"catagory": "weapon"}}', encoding="utf-8")
    code = main(
        [
            "--input",
            str(icon_dir),
            "--output",
            str(tmp_path / "o"),
            "--overrides",
            str(overrides),
        ]
    )
    assert code == 2
    assert "could not read" in capsys.readouterr().err


def test_cli_returns_1_when_nothing_matches(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main(["--input", str(empty), "--output", str(tmp_path / "o")])
    assert code == 1
    assert "Nothing was written" in capsys.readouterr().err
