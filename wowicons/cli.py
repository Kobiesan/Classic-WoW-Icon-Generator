"""Command line entry point: ``python -m wowicons --input ... --output ...``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .captions import DEFAULT_INSTANCE_TOKEN, load_overrides
from .pipeline import (
    DEFAULT_CLASS_TOKEN,
    DEFAULT_MIN_SIZE,
    DEFAULT_REPEATS,
    DEFAULT_SIZE,
    DatasetOptions,
    build_dataset,
    format_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wowicons",
        description=(
            "Convert a directory of WoW .blp icons into a kohya_ss training "
            "folder: 512x512 PNGs, one .txt caption each, plus manifest.csv."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Directory of .blp files (e.g. an extracted Interface/Icons), searched recursively.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Directory to write the kohya_ss training folder into.",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=None,
        help="Path to overrides.json with hand-written caption corrections.",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=DEFAULT_MIN_SIZE,
        help="Skip source icons whose shorter side is below this many pixels.",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=DEFAULT_SIZE,
        help="Edge length of the upscaled training images.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Repeat count baked into the kohya_ss image folder name.",
    )
    parser.add_argument(
        "--instance-token",
        default=DEFAULT_INSTANCE_TOKEN,
        help="Trigger word that starts every caption and names the image folder.",
    )
    parser.add_argument(
        "--class-token",
        default=DEFAULT_CLASS_TOKEN,
        help="Class word in the kohya_ss image folder name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and decode everything but write no files.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.is_dir():
        print(f"error: --input {args.input} is not a directory", file=sys.stderr)
        return 2
    if args.min_size < 1 or args.size < 1:
        print("error: --min-size and --size must be positive", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("error: --repeats must be positive", file=sys.stderr)
        return 2

    rules = []
    if args.overrides is not None:
        if not args.overrides.is_file():
            print(
                f"error: --overrides {args.overrides} does not exist",
                file=sys.stderr,
            )
            return 2
        try:
            rules = load_overrides(args.overrides)
        except (ValueError, OSError) as exc:
            print(f"error: could not read {args.overrides}: {exc}", file=sys.stderr)
            return 2
        print(f"Loaded {len(rules)} caption overrides from {args.overrides}")

    options = DatasetOptions(
        input_dir=args.input,
        output_dir=args.output,
        overrides_path=args.overrides,
        min_size=args.min_size,
        size=args.size,
        repeats=args.repeats,
        instance_token=args.instance_token,
        class_token=args.class_token,
        dry_run=args.dry_run,
    )

    stats = build_dataset(options, rules=rules)
    print(format_summary(stats, options))

    if stats.written == 0:
        print("\nNothing was written -- check --input and --min-size.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
