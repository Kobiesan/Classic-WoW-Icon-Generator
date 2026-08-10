"""Turn prompts into icon art.

Two backends behind one interface:

* :class:`StubBackend` needs nothing installed and produces deterministic
  placeholder art. It exists so the whole application - compositing, export, the
  results grid, cancellation - works and can be exercised before anyone has
  downloaded a model.
* :class:`DiffusersBackend` runs real Stable Diffusion with your trained LoRA
  applied. It imports ``torch`` and ``diffusers`` lazily, so the tool starts
  instantly and runs fine without them.

:func:`create_backend` picks whichever is usable and says why, which is what the
GUI shows in its status strip.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Sequence

from PIL import Image

__all__ = [
    "GenerationRequest",
    "GeneratedIcon",
    "GenerationProgress",
    "IconBackend",
    "StubBackend",
    "DiffusersBackend",
    "create_backend",
    "build_prompt",
    "DEFAULT_TRIGGER_WORD",
]

DEFAULT_TRIGGER_WORD = "wowicon"
OUTPUT_SIZE = 512
MAX_BATCH = 8


def build_prompt(prompt: str, trigger_word: str = DEFAULT_TRIGGER_WORD) -> str:
    """Prepend the LoRA trigger word unless it is already the leading term.

    The LoRA is trained on captions of the form
    ``"wowicon, <category>, <subject terms>"``, so the trigger has to lead or
    the style does not fire.
    """
    body = (prompt or "").strip().lstrip(",").strip()
    trigger = (trigger_word or "").strip().rstrip(",").strip()

    if not trigger:
        return body
    if not body:
        return trigger

    first_term = body.split(",", 1)[0].strip()
    if first_term.casefold() == trigger.casefold():
        return body
    return f"{trigger}, {body}"


@dataclass(frozen=True)
class GenerationRequest:
    """One batch of icons to produce."""

    prompt: str
    negative_prompt: str = ""
    seed: int = 0
    steps: int = 24
    cfg_scale: float = 7.5
    batch_count: int = 1
    trigger_word: str = DEFAULT_TRIGGER_WORD

    def validate(self) -> None:
        if not self.prompt or not self.prompt.strip():
            raise ValueError("Enter a prompt describing the icon you want.")
        if not 1 <= self.steps <= 150:
            raise ValueError("Steps must be between 1 and 150.")
        if not 1.0 <= self.cfg_scale <= 30.0:
            raise ValueError("Guidance (CFG) must be between 1 and 30.")
        if not 1 <= self.batch_count <= MAX_BATCH:
            raise ValueError(f"Number of icons must be between 1 and {MAX_BATCH}.")

    def seed_for(self, index: int) -> int:
        return self.seed + index

    @property
    def resolved_prompt(self) -> str:
        return build_prompt(self.prompt, self.trigger_word)


@dataclass
class GeneratedIcon:
    """Raw 512x512 art plus what produced it."""

    image: Image.Image
    seed: int
    prompt: str
    negative_prompt: str = ""


@dataclass(frozen=True)
class GenerationProgress:
    """Progress across a whole batch."""

    image_index: int
    batch_count: int
    step: int
    total_steps: int
    stage: str

    @property
    def fraction(self) -> float:
        if self.batch_count <= 0 or self.total_steps <= 0:
            return 0.0
        per_image = 1.0 / self.batch_count
        within = min(max(self.step / self.total_steps, 0.0), 1.0)
        return min(max((self.image_index * per_image) + (within * per_image), 0.0), 1.0)

    def __str__(self) -> str:
        return (
            f"{self.stage} - icon {self.image_index + 1}/{self.batch_count}, "
            f"step {self.step}/{self.total_steps}"
        )


class CancelledError(Exception):
    """Raised when a generation is cancelled part way through."""


class IconBackend(Protocol):
    name: str
    description: str

    def generate(
        self,
        request: GenerationRequest,
        on_progress: Optional[Callable[[GenerationProgress], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[GeneratedIcon]:
        ...


def _check_cancelled(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel is not None and should_cancel():
        raise CancelledError("Generation cancelled.")


class StubBackend:
    """Deterministic placeholder art, so the app works with nothing installed."""

    name = "Preview mode"
    description = (
        "No model loaded, so these are placeholder shapes rather than real art. "
        "Everything else - the border, saving, the icon format - is real."
    )

    def __init__(self, delay_per_step: float = 0.0):
        self._delay = delay_per_step

    def generate(
        self,
        request: GenerationRequest,
        on_progress: Optional[Callable[[GenerationProgress], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[GeneratedIcon]:
        request.validate()
        results: List[GeneratedIcon] = []

        for index in range(request.batch_count):
            seed = request.seed_for(index)

            for step in range(1, request.steps + 1):
                _check_cancelled(should_cancel)
                if self._delay:
                    import time

                    time.sleep(self._delay)
                if on_progress:
                    on_progress(
                        GenerationProgress(
                            index, request.batch_count, step, request.steps, "Drawing preview"
                        )
                    )

            _check_cancelled(should_cancel)
            results.append(
                GeneratedIcon(
                    image=render_stub_art(seed, request.resolved_prompt),
                    seed=seed,
                    prompt=request.resolved_prompt,
                    negative_prompt=request.negative_prompt,
                )
            )

        return results


def render_stub_art(seed: int, prompt: str, size: int = OUTPUT_SIZE) -> Image.Image:
    """Seeded blob art: same seed and prompt always give the same pixels."""
    rng = random.Random(f"{seed}:{prompt}")

    background = (rng.randrange(20, 70), rng.randrange(20, 70), rng.randrange(25, 80), 255)
    foreground = (rng.randrange(90, 256), rng.randrange(90, 256), rng.randrange(90, 256))

    image = Image.new("RGBA", (size, size), background)
    pixels = image.load()

    centre = size / 2
    radius = size * (0.22 + (rng.random() * 0.16))
    lobes = rng.randrange(3, 8)
    phase = rng.random() * math.tau

    for y in range(size):
        dy = y - centre
        for x in range(size):
            dx = x - centre
            distance = math.hypot(dx, dy)
            angle = math.atan2(dy, dx)
            edge = radius * (1.0 + (0.18 * math.sin((lobes * angle) + phase)))
            if distance > edge:
                continue
            # Fake a top-left light source, the way real icon art is lit.
            shade = min(max(1.15 - (distance / edge) - ((dx + dy) / (size * 1.5)), 0.15), 1.35)
            pixels[x, y] = (
                min(255, int(foreground[0] * shade)),
                min(255, int(foreground[1] * shade)),
                min(255, int(foreground[2] * shade)),
                255,
            )

    return image


@dataclass
class DiffusersBackend:
    """Real Stable Diffusion with your trained LoRA applied.

    Uses ``diffusers`` directly rather than an ONNX export: the LoRA that
    ``training/`` produces can be loaded straight onto a base checkpoint, which
    removes the whole export step from the user's path.
    """

    base_model: str = "runwayml/stable-diffusion-v1-5"
    lora_path: Optional[str] = None
    device: Optional[str] = None
    name: str = field(default="Stable Diffusion", init=False)
    description: str = field(default="", init=False)

    _pipeline: object = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.description = (
            f"{self.base_model}"
            + (f" with LoRA {Path(self.lora_path).name}" if self.lora_path else " (no LoRA)")
        )

    @staticmethod
    def is_available() -> bool:
        """True when torch and diffusers can be imported."""
        try:
            import diffusers  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def _resolve_device(self) -> str:
        if self.device:
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline

        import torch
        from diffusers import StableDiffusionPipeline

        device = self._resolve_device()
        dtype = torch.float16 if device == "cuda" else torch.float32

        pipeline = StableDiffusionPipeline.from_pretrained(
            self.base_model, torch_dtype=dtype, safety_checker=None
        )
        if self.lora_path:
            pipeline.load_lora_weights(self.lora_path)
        pipeline = pipeline.to(device)
        pipeline.set_progress_bar_config(disable=True)

        self._pipeline = pipeline
        return pipeline

    def generate(
        self,
        request: GenerationRequest,
        on_progress: Optional[Callable[[GenerationProgress], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> List[GeneratedIcon]:
        request.validate()

        import torch

        pipeline = self._load()
        device = self._resolve_device()
        results: List[GeneratedIcon] = []

        for index in range(request.batch_count):
            _check_cancelled(should_cancel)
            seed = request.seed_for(index)
            generator = torch.Generator(device=device).manual_seed(seed)

            def callback(_pipe, step, _timestep, kwargs, _index=index):
                _check_cancelled(should_cancel)
                if on_progress:
                    on_progress(
                        GenerationProgress(
                            _index, request.batch_count, step + 1, request.steps, "Generating"
                        )
                    )
                return kwargs

            image = pipeline(
                prompt=request.resolved_prompt,
                negative_prompt=request.negative_prompt or None,
                num_inference_steps=request.steps,
                guidance_scale=request.cfg_scale,
                width=OUTPUT_SIZE,
                height=OUTPUT_SIZE,
                generator=generator,
                callback_on_step_end=callback,
            ).images[0]

            results.append(
                GeneratedIcon(
                    image=image.convert("RGBA"),
                    seed=seed,
                    prompt=request.resolved_prompt,
                    negative_prompt=request.negative_prompt,
                )
            )

        return results


def create_backend(
    base_model: str = "",
    lora_path: str = "",
    force_stub: bool = False,
) -> IconBackend:
    """Pick the best usable backend.

    Falls back to the stub rather than failing, so the application always
    starts and can explain what is missing.
    """
    if force_stub or not DiffusersBackend.is_available():
        return StubBackend()

    if lora_path and not Path(lora_path).is_file():
        return StubBackend()

    return DiffusersBackend(
        base_model=base_model or "runwayml/stable-diffusion-v1-5",
        lora_path=lora_path or None,
    )
