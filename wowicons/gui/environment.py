"""Work out what the user still needs, and say it in plain language.

The GUI is aimed at someone who has never opened a terminal, so every check
here returns a sentence they can act on rather than a stack trace or a package
name on its own.
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

__all__ = ["Check", "EnvironmentReport", "check_environment", "check_training", "check_generation"]


@dataclass(frozen=True)
class Check:
    """One requirement and whether it is met."""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    required: bool = True

    @property
    def icon(self) -> str:
        return "OK" if self.ok else ("MISSING" if self.required else "optional")


@dataclass(frozen=True)
class EnvironmentReport:
    checks: List[Check]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    @property
    def blocking(self) -> List[Check]:
        return [check for check in self.checks if check.required and not check.ok]

    def summary(self) -> str:
        if self.ready:
            return "Everything needed is installed."
        missing = self.blocking
        if len(missing) == 1:
            return missing[0].detail
        return f"{len(missing)} things still needed - see the list."


def _module_installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def check_environment() -> EnvironmentReport:
    """Checks for the dataset half, which needs almost nothing."""
    return EnvironmentReport([
        Check(
            name="Pillow",
            ok=_module_installed("PIL"),
            detail="Pillow is installed." if _module_installed("PIL")
                   else "Pillow is missing, so images cannot be written.",
            fix="Run: pip install -r requirements.txt",
        ),
    ])


def check_generation(lora_path: str = "", base_model: str = "") -> EnvironmentReport:
    """Checks for the generate tab."""
    has_torch = _module_installed("torch")
    has_diffusers = _module_installed("diffusers")

    checks = [
        Check(
            name="PyTorch",
            ok=has_torch,
            detail="PyTorch is installed." if has_torch
                   else "PyTorch is not installed, so only preview shapes can be produced.",
            fix="Install it from https://pytorch.org/get-started/locally/ - "
                "pick the CUDA version matching your graphics card.",
            required=False,
        ),
        Check(
            name="Diffusers",
            ok=has_diffusers,
            detail="Diffusers is installed." if has_diffusers
                   else "Diffusers is not installed, so real image generation is unavailable.",
            fix="Run: pip install diffusers transformers accelerate safetensors",
            required=False,
        ),
    ]

    if lora_path:
        exists = Path(lora_path).is_file()
        checks.append(Check(
            name="Trained LoRA",
            ok=exists,
            detail=f"Using LoRA: {Path(lora_path).name}" if exists
                   else f"No LoRA file at {lora_path}.",
            fix="Train one on the Train tab, then pick the .safetensors file it produces.",
            required=False,
        ))

    return EnvironmentReport(checks)


def check_training(sd_scripts_dir: str = "", dataset_dir: str = "") -> EnvironmentReport:
    """Checks for the train tab."""
    checks: List[Check] = []

    script = Path(sd_scripts_dir) / "train_network.py" if sd_scripts_dir else None
    has_scripts = bool(script and script.is_file())
    checks.append(Check(
        name="sd-scripts",
        ok=has_scripts,
        detail="Found sd-scripts." if has_scripts
               else "sd-scripts has not been set up yet. This is the trainer that does the work.",
        fix="Download it from https://github.com/kohya-ss/sd-scripts, then point the "
            "box above at the folder you unzipped.",
    ))

    images = 0
    if dataset_dir:
        image_root = Path(dataset_dir) / "img"
        if image_root.is_dir():
            images = len(list(image_root.rglob("*.png")))
    checks.append(Check(
        name="Dataset",
        ok=images > 0,
        detail=f"Dataset has {images} images." if images
               else "No dataset yet. Build one on the Dataset tab first.",
        fix="Go to the Dataset tab and press Build dataset.",
    ))

    has_python = shutil.which("accelerate") is not None or _module_installed("accelerate")
    checks.append(Check(
        name="Accelerate",
        ok=has_python,
        detail="Accelerate is installed." if has_python
               else "Accelerate is missing; sd-scripts uses it to launch training.",
        fix="Run: pip install accelerate",
    ))

    return EnvironmentReport(checks)


def find_latest_samples(model_dir: str, limit: int = 8) -> List[Path]:
    """Newest sample images written by training, most recent first."""
    root = Path(model_dir) / "sample"
    if not root.is_dir():
        return []
    samples = sorted(root.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return samples[:limit]


def find_trained_loras(model_dir: str) -> List[Path]:
    """Checkpoints training has produced, newest first."""
    root = Path(model_dir)
    if not root.is_dir():
        return []
    return sorted(root.glob("*.safetensors"), key=lambda p: p.stat().st_mtime, reverse=True)


def suggest_default_directory(name: str) -> Optional[str]:
    """A writable default under the user's home, so nobody has to invent one."""
    home = Path.home()
    for candidate in (home / "Documents" / "WowIconForge", home / "WowIconForge"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return str(candidate / name)
    return None
