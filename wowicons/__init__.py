"""Dataset pipeline for training a Stable Diffusion LoRA on WoW icon art.

Modules:

* :mod:`wowicons.blp` -- standard-library-only BLP1/BLP2 decoder (portable).
* :mod:`wowicons.captions` -- filename to caption parser plus overrides.
* :mod:`wowicons.pipeline` -- decode, upscale, caption, manifest.
* :mod:`wowicons.cli` -- argparse front end.
"""

__version__ = "0.1.0"

__all__ = ["blp", "captions", "cli", "pipeline"]
