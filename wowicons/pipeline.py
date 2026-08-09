"""Turn a directory of ``.blp`` icons into a kohya_ss training folder.

Output layout (what kohya_ss / sd-scripts expects)::

    <output>/
        img/
            <repeats>_<instance token> <class token>/
                INV_Sword_04.png     512x512 RGB
                INV_Sword_04.txt     "wowicon, weapon, sword"
        model/
        log/
        manifest.csv

Images are flattened onto a solid background before upscaling: BLP icons carry
an alpha channel, trainers do not, and compositing before the Lanczos pass
avoids dark halos bleeding out of the transparent border.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from PIL import Image

from . import blp
from .captions import (
    DEFAULT_INSTANCE_TOKEN,
    Caption,
    OverrideRule,
    caption_for,
    load_overrides,
)

__all__ = [
    "DatasetOptions",
    "IconRecord",
    "PipelineStats",
    "build_dataset",
    "find_blp_files",
    "format_category_counts",
    "render_icon",
    "write_manifest",
]

DEFAULT_SIZE = 512
DEFAULT_MIN_SIZE = 64
DEFAULT_REPEATS = 10
DEFAULT_CLASS_TOKEN = "icon"
BACKGROUND = (0, 0, 0)

MANIFEST_COLUMNS = ("source_path", "output_path", "caption", "category")


@dataclass
class DatasetOptions:
    """Everything the pipeline needs to know, resolved from the CLI."""

    input_dir: Path
    output_dir: Path
    overrides_path: Optional[Path] = None
    min_size: int = DEFAULT_MIN_SIZE
    size: int = DEFAULT_SIZE
    repeats: int = DEFAULT_REPEATS
    instance_token: str = DEFAULT_INSTANCE_TOKEN
    class_token: str = DEFAULT_CLASS_TOKEN
    dry_run: bool = False

    @property
    def image_dir(self) -> Path:
        """The ``<repeats>_<instance> <class>`` folder kohya_ss reads."""
        name = f"{self.repeats}_{self.instance_token} {self.class_token}".strip()
        return self.output_dir / "img" / name


@dataclass
class IconRecord:
    """One successfully converted icon, as written to the manifest."""

    source_path: Path
    output_path: Path
    caption: Caption
    source_size: Tuple[int, int]

    @property
    def category(self) -> str:
        return self.caption.category


@dataclass
class PipelineStats:
    """Counts and problems collected over a run."""

    records: List[IconRecord] = field(default_factory=list)
    skipped_small: List[Tuple[Path, Tuple[int, int]]] = field(default_factory=list)
    failures: List[Tuple[Path, str]] = field(default_factory=list)
    total_found: int = 0

    @property
    def categories(self) -> Counter:
        return Counter(record.category for record in self.records)

    @property
    def written(self) -> int:
        return len(self.records)


def find_blp_files(root: Path) -> Iterator[Path]:
    """Yield every ``.blp`` under ``root``, recursively, in a stable order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(".blp"):
                yield Path(dirpath) / filename


def _fit_square(image: Image.Image, size: int) -> Image.Image:
    """Flatten onto the background and scale to ``size`` x ``size``.

    Square sources (every real icon) scale straight up; anything else keeps its
    aspect ratio and is centred, rather than being stretched.
    """
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    flat = Image.new("RGB", image.size, BACKGROUND)
    flat.paste(image, mask=image.getchannel("A"))

    width, height = flat.size
    if width == height:
        return flat.resize((size, size), Image.LANCZOS)

    scale = min(size / width, size / height)
    new_size = (max(round(width * scale), 1), max(round(height * scale), 1))
    scaled = flat.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), BACKGROUND)
    canvas.paste(
        scaled, ((size - new_size[0]) // 2, (size - new_size[1]) // 2)
    )
    return canvas


def _unique_stem(stem: str, taken: set) -> str:
    """Keep output names unique when the same icon name appears in two dirs."""
    candidate = stem
    counter = 2
    while candidate.lower() in taken:
        candidate = f"{stem}__{counter}"
        counter += 1
    taken.add(candidate.lower())
    return candidate


def render_icon(decoded: blp.BLPImage, size: int) -> Image.Image:
    """Turn decoded BLP pixels into the square RGB image we train on."""
    image = Image.frombytes(
        "RGBA", (decoded.width, decoded.height), decoded.tobytes()
    )
    return _fit_square(image, size)


def build_dataset(
    options: DatasetOptions, rules: Optional[Sequence[OverrideRule]] = None
) -> PipelineStats:
    """Convert every icon under ``options.input_dir`` and write the manifest."""
    if rules is None:
        rules = (
            load_overrides(options.overrides_path) if options.overrides_path else []
        )

    stats = PipelineStats()
    image_dir = options.image_dir

    if not options.dry_run:
        image_dir.mkdir(parents=True, exist_ok=True)
        (options.output_dir / "model").mkdir(parents=True, exist_ok=True)
        (options.output_dir / "log").mkdir(parents=True, exist_ok=True)

    taken: set = set()
    for source in find_blp_files(options.input_dir):
        stats.total_found += 1
        try:
            decoded = blp.open_blp(source)
        except Exception as exc:
            stats.failures.append((source, f"{type(exc).__name__}: {exc}"))
            continue

        source_size = (decoded.width, decoded.height)
        if min(source_size) < options.min_size:
            stats.skipped_small.append((source, source_size))
            continue

        caption = caption_for(
            source.name, rules, instance_token=options.instance_token
        )
        stem = _unique_stem(source.stem, taken)
        image_path = image_dir / f"{stem}.png"
        caption_path = image_dir / f"{stem}.txt"

        if not options.dry_run:
            try:
                render_icon(decoded, options.size).save(image_path, format="PNG")
                caption_path.write_text(caption.text + "\n", encoding="utf-8")
            except Exception as exc:
                stats.failures.append((source, f"{type(exc).__name__}: {exc}"))
                continue

        stats.records.append(
            IconRecord(
                source_path=source,
                output_path=image_path,
                caption=caption,
                source_size=source_size,
            )
        )

    if not options.dry_run:
        write_manifest(options.output_dir / "manifest.csv", stats.records)

    return stats


def write_manifest(path: Path, records: Iterable[IconRecord]) -> None:
    """Write the CSV audit trail: source, output, caption, detected category."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MANIFEST_COLUMNS)
        for record in records:
            writer.writerow(
                [
                    str(record.source_path),
                    str(record.output_path),
                    record.caption.text,
                    record.category,
                ]
            )


def format_category_counts(counts: Counter, bar_width: int = 30) -> str:
    """Render category counts as a sorted table, for spotting imbalance."""
    total = sum(counts.values())
    if not total:
        return "No images were written, so there are no categories to count."

    lines = [f"Category counts ({total} images, {len(counts)} categories)"]
    label_width = max(len(name) for name in counts)
    largest = max(counts.values())
    for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        share = count / total * 100
        bar = "#" * max(round(count / largest * bar_width), 1)
        lines.append(
            f"  {name:<{label_width}}  {count:>6}  {share:>5.1f}%  {bar}"
        )
    return "\n".join(lines)


def format_summary(stats: PipelineStats, options: DatasetOptions) -> str:
    """Human-readable run report, printed after the conversion finishes."""
    lines = [
        "",
        f"Found     {stats.total_found} .blp files under {options.input_dir}",
        f"Written   {stats.written} image/caption pairs -> {options.image_dir}",
    ]
    if stats.skipped_small:
        lines.append(
            f"Skipped   {len(stats.skipped_small)} below --min-size "
            f"{options.min_size}"
        )
        for source, size in stats.skipped_small[:5]:
            lines.append(f"            {source.name} ({size[0]}x{size[1]})")
        if len(stats.skipped_small) > 5:
            lines.append(f"            ... and {len(stats.skipped_small) - 5} more")
    if stats.failures:
        lines.append(f"Failed    {len(stats.failures)} could not be decoded")
        for source, reason in stats.failures[:5]:
            lines.append(f"            {source.name}: {reason}")
        if len(stats.failures) > 5:
            lines.append(f"            ... and {len(stats.failures) - 5} more")
    if options.dry_run:
        lines.append("Dry run   no files were written")
    lines.append("")
    lines.append(format_category_counts(stats.categories))
    return "\n".join(lines)
