"""The three things the GUI actually does, as background jobs.

Each function takes a :class:`~wowicons.gui.jobs.JobHandle` and reports through
it, so the UI layer is left with nothing but widgets. Kept separate from the Tk
code so all of it is testable headlessly.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PIL import Image

from .. import blp_writer, compositing, generate
from ..captions import load_overrides
from ..pipeline import DatasetOptions, build_dataset, format_category_counts
from . import assets
from .jobs import CancelledError, JobHandle

__all__ = [
    "DatasetSettings",
    "TrainingSettings",
    "GenerateSettings",
    "run_dataset_build",
    "build_training_command",
    "run_training",
    "run_generation",
    "save_icon",
]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass
class DatasetSettings:
    input_dir: str = ""
    output_dir: str = ""
    overrides_path: str = ""
    min_size: int = 64

    def validate(self) -> None:
        if not self.input_dir.strip():
            raise ValueError("Choose the folder holding your .blp icon files.")
        if not Path(self.input_dir).is_dir():
            raise ValueError(f"That icon folder does not exist:\n{self.input_dir}")
        if not self.output_dir.strip():
            raise ValueError("Choose where the dataset should be saved.")
        if self.overrides_path and not Path(self.overrides_path).is_file():
            raise ValueError(f"That caption corrections file does not exist:\n{self.overrides_path}")


@dataclass
class DatasetResult:
    written: int
    skipped: int
    failed: int
    categories: Dict[str, int] = field(default_factory=dict)
    output_dir: str = ""
    report: str = ""


def run_dataset_build(handle: JobHandle, settings: DatasetSettings) -> DatasetResult:
    """Convert a folder of .blp icons into a training dataset."""
    settings.validate()

    handle.log(f"Reading icons from {settings.input_dir}")
    handle.progress(0.0, "Looking for icons...")

    rules = load_overrides(settings.overrides_path) if settings.overrides_path else []
    if rules:
        handle.log(f"Loaded {len(rules)} caption corrections.")

    options = DatasetOptions(
        input_dir=Path(settings.input_dir),
        output_dir=Path(settings.output_dir),
        overrides_path=Path(settings.overrides_path) if settings.overrides_path else None,
        min_size=settings.min_size,
    )

    handle.raise_if_cancelled()
    handle.progress(None, "Converting icons - this can take a minute...")

    stats = build_dataset(options, rules=rules)
    handle.raise_if_cancelled()

    if stats.written == 0:
        raise ValueError(
            "No icons were converted. Check that the folder really holds .blp files, "
            "and that they are at least as large as the minimum size."
        )

    handle.progress(1.0, f"Done - {stats.written} icons ready.")
    handle.log(f"Wrote {stats.written} image and caption pairs.")
    if stats.skipped_small:
        handle.log(f"Skipped {len(stats.skipped_small)} icons smaller than {settings.min_size}px.")
    if stats.failures:
        handle.log(f"Could not read {len(stats.failures)} files:")
        for source, reason in stats.failures[:5]:
            handle.log(f"    {source.name}: {reason}")

    report = format_category_counts(stats.categories)
    handle.log("")
    handle.log(report)

    return DatasetResult(
        written=stats.written,
        skipped=len(stats.skipped_small),
        failed=len(stats.failures),
        categories=dict(stats.categories),
        output_dir=settings.output_dir,
        report=report,
    )


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


@dataclass
class TrainingSettings:
    sd_scripts_dir: str = ""
    dataset_dir: str = ""
    base_model: str = "runwayml/stable-diffusion-v1-5"
    epochs: int = 10
    batch_size: int = 4
    learning_rate: float = 1e-4
    network_dim: int = 32
    resolution: int = 512
    output_name: str = "wowicon_lora"

    def validate(self) -> None:
        script = Path(self.sd_scripts_dir) / "train_network.py"
        if not self.sd_scripts_dir.strip() or not script.is_file():
            raise ValueError(
                "sd-scripts was not found. Download it from\n"
                "https://github.com/kohya-ss/sd-scripts\n"
                "then point the sd-scripts box at the folder you unzipped."
            )
        image_root = Path(self.dataset_dir) / "img"
        if not image_root.is_dir() or not any(image_root.rglob("*.png")):
            raise ValueError("No dataset found. Build one on the Dataset tab first.")
        if self.epochs < 1:
            raise ValueError("Epochs must be at least 1.")
        if self.batch_size < 1:
            raise ValueError("Batch size must be at least 1.")

    @property
    def image_dir(self) -> Optional[Path]:
        """The single ``<repeats>_<token>`` folder kohya expects."""
        root = Path(self.dataset_dir) / "img"
        if not root.is_dir():
            return None
        subdirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
        return subdirs[0] if subdirs else None

    @property
    def model_dir(self) -> Path:
        return Path(self.dataset_dir) / "model"

    @property
    def log_dir(self) -> Path:
        return Path(self.dataset_dir) / "log"


def build_training_command(settings: TrainingSettings) -> List[str]:
    """The accelerate command line, built so the GUI can also show it."""
    image_dir = settings.image_dir
    if image_dir is None:
        raise ValueError("No dataset found. Build one on the Dataset tab first.")

    return [
        sys.executable, "-m", "accelerate.commands.launch",
        "--num_cpu_threads_per_process", "4",
        str(Path(settings.sd_scripts_dir) / "train_network.py"),
        "--pretrained_model_name_or_path", settings.base_model,
        "--train_data_dir", str(image_dir.parent),
        "--output_dir", str(settings.model_dir),
        "--logging_dir", str(settings.log_dir),
        "--output_name", settings.output_name,
        "--save_model_as", "safetensors",
        "--network_module", "networks.lora",
        "--network_dim", str(settings.network_dim),
        "--network_alpha", str(max(1, settings.network_dim // 2)),
        "--resolution", f"{settings.resolution},{settings.resolution}",
        "--train_batch_size", str(settings.batch_size),
        "--max_train_epochs", str(settings.epochs),
        "--learning_rate", str(settings.learning_rate),
        "--unet_lr", str(settings.learning_rate),
        "--text_encoder_lr", str(settings.learning_rate / 2),
        "--optimizer_type", "AdamW8bit",
        "--lr_scheduler", "cosine_with_restarts",
        "--lr_scheduler_num_cycles", "3",
        "--mixed_precision", "fp16",
        "--save_precision", "fp16",
        "--save_every_n_epochs", "1",
        "--caption_extension", ".txt",
        "--shuffle_caption",
        "--keep_tokens", "1",
        "--min_snr_gamma", "5",
        "--cache_latents",
        "--seed", "42",
        "--xformers",
    ]


def run_training(
    handle: JobHandle,
    settings: TrainingSettings,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    """Run sd-scripts as a subprocess, streaming its output to the log."""
    settings.validate()

    command = build_training_command(settings)
    settings.model_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    handle.log("Starting training. This takes a while - you can leave it running.")
    handle.log("")
    handle.log(" ".join(shlex.quote(part) for part in command))
    handle.log("")
    handle.progress(None, "Training...")

    process = popen(
        command,
        cwd=settings.sd_scripts_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    try:
        if process.stdout is not None:
            for line in process.stdout:
                handle.log(line.rstrip())
                if handle.cancelled:
                    process.terminate()
                    raise CancelledError("Training stopped.")
                fraction = _parse_epoch_progress(line, settings.epochs)
                if fraction is not None:
                    handle.progress(fraction, "Training...")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    code = process.wait()
    if code != 0:
        raise RuntimeError(
            f"Training stopped with an error (exit code {code}). "
            "The log above usually says why - a missing package or too little "
            "video memory are the common ones."
        )

    handle.progress(1.0, "Training finished.")
    handle.log("")
    handle.log(f"Trained files are in {settings.model_dir}")
    return code


def _parse_epoch_progress(line: str, total_epochs: int) -> Optional[float]:
    """Pull an ``epoch 3/10`` style marker out of sd-scripts' output."""
    lowered = line.lower()
    if "epoch" not in lowered or total_epochs <= 0:
        return None
    for token in lowered.replace(":", " ").split():
        if "/" in token:
            head, _, tail = token.partition("/")
            if head.strip().isdigit() and tail.strip().isdigit():
                done, total = int(head), int(tail)
                if total in (total_epochs,) and 0 <= done <= total:
                    return done / total
    return None


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


@dataclass
class GenerateSettings:
    prompt: str = ""
    negative_prompt: str = ""
    seed: int = 0
    steps: int = 24
    cfg_scale: float = 7.5
    batch_count: int = 4
    trigger_word: str = generate.DEFAULT_TRIGGER_WORD
    template_path: str = ""
    sharpen_amount: float = compositing.DEFAULT_SHARPEN_AMOUNT
    base_model: str = ""
    lora_path: str = ""
    force_stub: bool = False


@dataclass
class GeneratedResult:
    icon: Image.Image
    art: Image.Image
    seed: int
    prompt: str


def run_generation(
    handle: JobHandle,
    settings: GenerateSettings,
    backend: Optional[generate.IconBackend] = None,
) -> List[GeneratedResult]:
    """Generate art, then fit each piece into the border template."""
    request = generate.GenerationRequest(
        prompt=settings.prompt,
        negative_prompt=settings.negative_prompt,
        seed=settings.seed,
        steps=settings.steps,
        cfg_scale=settings.cfg_scale,
        batch_count=settings.batch_count,
        trigger_word=settings.trigger_word,
    )
    request.validate()

    backend = backend or generate.create_backend(
        base_model=settings.base_model,
        lora_path=settings.lora_path,
        force_stub=settings.force_stub,
    )
    handle.log(f"Using: {backend.name}")

    if settings.template_path:
        if not Path(settings.template_path).is_file():
            raise ValueError(f"Border template not found:\n{settings.template_path}")
        template = compositing.load_template(settings.template_path)
    else:
        # No template chosen: use the built-in gold frame rather than shipping
        # bare squares. A real template can be picked in Settings at any time.
        template = assets.default_border_template()
        handle.log("Using the built-in gold border. Pick your own in Settings if you like.")

    mask = compositing.content_mask_for(template)
    if mask.has_empty_interior:
        handle.log(
            "Warning: that border template has no transparent middle, so the "
            "artwork will be hidden behind it."
        )

    def on_progress(progress: generate.GenerationProgress) -> None:
        handle.progress(progress.fraction, str(progress))

    try:
        icons = backend.generate(
            request, on_progress=on_progress, should_cancel=lambda: handle.cancelled
        )
    except generate.CancelledError as exc:
        raise CancelledError(str(exc)) from exc

    handle.raise_if_cancelled()
    handle.progress(None, "Adding the border...")

    results: List[GeneratedResult] = []
    options = compositing.CompositeOptions(sharpen_amount=settings.sharpen_amount)

    for item in icons:
        handle.raise_if_cancelled()
        icon = compositing.composite_icon(item.image, template, options)
        results.append(
            GeneratedResult(icon=icon, art=item.image, seed=item.seed, prompt=item.prompt)
        )

    handle.progress(1.0, f"Made {len(results)} icons.")
    return results


def save_icon(icon: Image.Image, path: str) -> str:
    """Save as PNG or BLP, chosen by the file extension."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.suffix.lower() == ".blp":
        blp_writer.save_blp2(target, icon)
    else:
        icon.convert("RGBA").save(target, format="PNG")

    return str(target)


def suggest_file_name(prompt: str, seed: int, extension: str = "png") -> str:
    """A filename from the prompt that any filesystem will accept."""
    cleaned = "".join(c.lower() if c.isalnum() else "_" for c in (prompt or ""))
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_")[:48].strip("_") or "icon"
    return f"{cleaned}_{seed}.{extension}"
