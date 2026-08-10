"""Tests for the sample-prompt generator."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from wowicons.prompts import (
    GENERALISATION_PROMPTS,
    SampleSettings,
    build_prompt_lines,
    category_terms,
    main,
    read_manifest,
    render_prompt_file,
)

ROWS = [
    ("wowicon, weapon, sword", "weapon"),
    ("wowicon, weapon, sword", "weapon"),
    ("wowicon, weapon, axe", "weapon"),
    ("wowicon, armor, chest, cloth", "armor"),
    ("wowicon, armor, boots", "armor"),
    ("wowicon, fire spell, fireball, flames", "fire spell"),
    ("wowicon, profession, alchemy", "profession"),
]


@pytest.fixture()
def manifest(tmp_path: Path) -> Path:
    path = tmp_path / "manifest.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_path", "output_path", "caption", "category"])
        for index, (caption, category) in enumerate(ROWS):
            writer.writerow([f"src/{index}.blp", f"out/{index}.png", caption, category])
    return path


def rows_as_dicts():
    return [{"caption": caption, "category": category} for caption, category in ROWS]


def prompt_lines(lines):
    return [line for line in lines if line and not line.startswith("#")]


# ---------------------------------------------------------------------------
# Manifest reading
# ---------------------------------------------------------------------------


def test_read_manifest(manifest):
    rows = read_manifest(manifest)
    assert len(rows) == len(ROWS)
    assert rows[0]["category"] == "weapon"


def test_read_manifest_rejects_empty(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("source_path,output_path,caption,category\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no rows"):
        read_manifest(path)


def test_read_manifest_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("source_path,output_path\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        read_manifest(path)


# ---------------------------------------------------------------------------
# Term counting
# ---------------------------------------------------------------------------


def test_category_terms_counts_within_each_category():
    terms = category_terms(rows_as_dicts())
    assert terms["weapon"]["sword"] == 2
    assert terms["weapon"]["axe"] == 1
    assert terms["armor"]["cloth"] == 1
    assert "weapon" not in terms["armor"]


def test_category_terms_keeps_multi_word_terms_intact():
    rows = [{"caption": "wowicon, holy spell, power word shield", "category": "holy spell"}]
    assert category_terms(rows)["holy spell"]["power word shield"] == 1


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def test_prompts_cover_the_largest_categories_first():
    lines = prompt_lines(build_prompt_lines(rows_as_dicts(), top_categories=2))
    assert lines[0].startswith("wowicon, weapon, sword ")
    assert lines[1].startswith("wowicon, armor, ")


def test_most_common_term_is_chosen():
    lines = prompt_lines(build_prompt_lines(rows_as_dicts(), top_categories=1))
    assert lines[0].startswith("wowicon, weapon, sword ")  # sword 2, axe 1


def test_every_prompt_has_a_distinct_seed():
    lines = prompt_lines(build_prompt_lines(rows_as_dicts()))
    seeds = [line.split("--d ")[1] for line in lines]
    assert len(seeds) == len(set(seeds))
    assert seeds[0] == "101"


def test_seeds_are_stable_across_runs():
    """Epoch comparisons are meaningless if the seeds move between runs."""
    first = build_prompt_lines(rows_as_dicts())
    second = build_prompt_lines(rows_as_dicts())
    assert first == second


def test_generation_settings_are_rendered():
    settings = SampleSettings(
        width=768, height=768, steps=30, cfg=6.0, negative="ugly", first_seed=7
    )
    line = prompt_lines(build_prompt_lines(rows_as_dicts(), settings, top_categories=1))[0]
    assert line == (
        "wowicon, weapon, sword --n ugly --w 768 --h 768 --l 6.0 --s 30 --d 7"
    )


def test_generalisation_prompts_are_appended():
    lines = prompt_lines(build_prompt_lines(rows_as_dicts()))
    for prompt in GENERALISATION_PROMPTS:
        assert any(line.startswith(prompt + " ") for line in lines)


def test_generalisation_prompts_can_be_disabled():
    lines = prompt_lines(
        build_prompt_lines(rows_as_dicts(), generalisation_prompts=())
    )
    assert all(not line.startswith("wowicon, weapon, sword, glowing") for line in lines)


def test_terms_per_category():
    lines = prompt_lines(
        build_prompt_lines(
            rows_as_dicts(),
            top_categories=1,
            terms_per_category=2,
            generalisation_prompts=(),
        )
    )
    assert len(lines) == 2
    assert lines[0].startswith("wowicon, weapon, sword ")
    assert lines[1].startswith("wowicon, weapon, axe ")


def test_category_without_terms_still_gets_a_prompt():
    rows = [{"caption": "wowicon, weapon", "category": "weapon"}]
    lines = prompt_lines(
        build_prompt_lines(rows, top_categories=1, generalisation_prompts=())
    )
    assert lines == ["wowicon, weapon --n " + SampleSettings().negative
                     + " --w 512 --h 512 --l 7.5 --s 24 --d 101"]


def test_instance_token_is_configurable():
    lines = prompt_lines(
        build_prompt_lines(rows_as_dicts(), top_categories=1, instance_token="wowicon2")
    )
    assert lines[0].startswith("wowicon2, weapon, sword ")


def test_comment_lines_are_sd_scripts_safe():
    """sd-scripts skips blank lines and lines starting with '#'."""
    text = render_prompt_file(rows_as_dicts())
    for line in text.splitlines():
        assert line == "" or line.startswith("#") or line.startswith("wowicon")


def test_header_reports_dataset_size():
    text = render_prompt_file(rows_as_dicts())
    assert "7 images across 4 categories" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_writes_a_file(manifest, tmp_path, capsys):
    output = tmp_path / "nested" / "sample_prompts.txt"
    code = main(["--manifest", str(manifest), "--output", str(output)])
    assert code == 0
    assert "sample prompts" in capsys.readouterr().out
    assert output.read_text(encoding="utf-8").count("--d ") == len(
        prompt_lines(build_prompt_lines(read_manifest(manifest)))
    )


def test_cli_prints_to_stdout_without_output(manifest, capsys):
    assert main(["--manifest", str(manifest)]) == 0
    assert "wowicon, weapon, sword" in capsys.readouterr().out


def test_cli_reports_a_missing_manifest(tmp_path, capsys):
    code = main(["--manifest", str(tmp_path / "nope.csv")])
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_passes_through_generation_settings(manifest, capsys):
    main(["--manifest", str(manifest), "--steps", "40", "--cfg", "5", "--seed", "9"])
    out = capsys.readouterr().out
    assert "--s 40" in out and "--l 5.0" in out and "--d 9" in out


def test_shipped_sample_prompts_file_is_valid():
    """The committed starter file must stay parseable by sd-scripts."""
    path = Path(__file__).resolve().parent.parent / "training" / "sample_prompts.txt"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()]
    prompts = prompt_lines(lines)
    assert len(prompts) >= 8
    seeds = [line.split("--d ")[1] for line in prompts]
    assert len(seeds) == len(set(seeds))
    for line in prompts:
        assert line.startswith("wowicon, ")
        for flag in ("--n ", "--w ", "--h ", "--l ", "--s ", "--d "):
            assert flag in line
