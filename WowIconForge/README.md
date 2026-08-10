# WoW Icon Forge

A Windows desktop app (C# / .NET 8 / WPF) that generates World of Warcraft-style
icons from text prompts with a local ONNX Stable Diffusion model, composites them
against a border template, and exports PNG or BLP.

Open `WowIconForge.sln` in Visual Studio 2022.

| Project | Target | What it is |
| --- | --- | --- |
| `src/WowIconForge.Core` | `net8.0` | Inference, compositing, BLP I/O. No UI dependencies. |
| `src/WowIconForge.App` | `net8.0-windows` | WPF UI. |
| `tests/WowIconForge.Core.Tests` | `net8.0` | xUnit. 148 tests. |

## Status

**Core is implemented and tested. The UI is scaffolded, not built, and ONNX
inference is stubbed** — which is the agreed starting scope: get compositing and
BLP export testable before any model files exist.

| Area | State |
| --- | --- |
| Compositing pipeline and content mask | Implemented, 30 tests |
| BLP2 writer + BLP1/BLP2 reader | Implemented, 33 tests |
| Median-cut quantizer, mipmaps | Implemented, 18 tests |
| Generation, export, settings | Implemented, 67 tests |
| ONNX denoise loop | **Not implemented** — `OnnxIconGenerator` throws |
| WPF window | **Scaffold only** — layout is the next phase |

Everything downstream of generation already works end to end against
`StubIconGenerator`, which produces deterministic seeded art with no model files.

## Compositing

Implemented in the exact order specified, in `IconCompositor.Composite`:

1. Load the border template (`BorderTemplate.Load`, any format ImageSharp reads).
2. Derive the content mask **once per template** and cache it
   (`ContentMaskCache`, keyed on a hash of the template's pixels so editing a
   template in place invalidates it).
3. Downscale the 512×512 art to the template's size with Lanczos3, then apply an
   optional unsharp mask at a configurable strength.
4. Zero the alpha of every art pixel outside the content mask.
5. Alpha-composite the border template over the masked art.

**The mask** is the flood fill from the template's centre — 4-connected, through
transparent pixels, halting at opaque ones — *unioned with the template's own
opaque pixels*. That union matters: art beneath a semi-transparent border edge
has to survive masking so it can show through when the border is composited over
it.

**Corners** sit outside the flood region, because the border ring blocks the
fill, and they are transparent in the template, so they are in neither half of
the union. Their alpha is zeroed in step 4 and the template adds nothing over
them, so they stay fully transparent. `IconCompositorTests.Corners_AreFullyTransparent`
asserts exactly this against a synthetic template with known-transparent corners,
and `ContentMaskTests.FloodFill_IsFourConnectedAndDoesNotLeakDiagonally` pins the
4-connectivity that makes it true.

Two ordering details worth knowing, because they are easy to get backwards:

- **Sharpening runs before masking**, so it can never resurrect alpha outside the
  mask. There is a test for that at maximum strength.
- **The unsharp mask never touches alpha.** Sharpening it would chew into the
  mask's edges, which the compositor depends on being exact.

## BLP export

`BlpWriter` produces BLP2: palettized, 256 colours, with a full 8-bit alpha
plane, and the whole mip chain from 64×64 down to 1×1 (7 levels).

- **Palette**: median cut (`MedianCutQuantizer`). Under 256 distinct colours, the
  palette holds them all and colour round-trips losslessly. Fully transparent
  pixels are excluded from the histogram — their RGB is arbitrary padding, and
  letting it vote spends palette entries on colour nobody can see.
- **Alpha is never quantized.** It is written verbatim as its own plane, so it
  survives the round trip exactly. Asserted per pixel over all 256 alpha values.
- **One palette for the whole chain**, which is how the format works — it is
  built from the full-resolution image and reused as the chain shrinks.
- **Mip downsampling weights RGB by alpha.** A plain average pulls the colour of
  transparent padding into visible pixels, and the symptom is a dark halo
  creeping inward around icon edges as the mips get smaller.

`BlpReader` is a port of the Python decoder in `wowicons/blp.py`, kept
behaviourally identical: BLP1 and BLP2, palettized with 1/4/8-bit alpha,
DXT1/DXT3/DXT5, and BGRA8888. It is tested against synthesized byte streams
mirroring the Python suite, so no binary fixtures or client files are committed.

The JPEG-compressed BLP1 variant is **rejected with a clear message** rather than
guessed at — vanilla `Interface/Icons` does not use it, and its channel order was
never verified against a real Blizzard file.

The round-trip test writes a BLP, reads it back with that decoder, and asserts
RGBA matches within tolerance (exact for small palettes, ≤12 per channel for a
full gradient; alpha exact in both cases).

## Inference

`IIconGenerator` takes prompt, negative prompt, seed, steps, CFG and batch count,
and reports progress per step via `IProgress<GenerationProgress>`.

The trigger word is applied by `TriggerWordGenerator`, a decorator around any
generator. That makes "every prompt gets the trigger" true by construction rather
than by remembering to do it in each implementation, and it reads the word
through a delegate so changing it in settings takes effect on the next
generation. It will not double-prefix a prompt the user already typed it into.

`ModelLayout.Probe` checks a model directory without loading anything, and drives
the first-run wizard. The expected layout is the standard
`optimum-cli export onnx` output, which is what any online guide produces:

```
models/
  unet/model.onnx            required
  vae_decoder/model.onnx     required
  text_encoder/model.onnx    required
  tokenizer/vocab.json       required
  tokenizer/merges.txt       required
  vae_encoder/model.onnx     optional (image-to-image only)
```

`ModelDirectoryStatus.ToUserMessage()` returns wizard copy written for someone
who has never opened a terminal — it names the missing files and says where they
go, with no jargon.

`ExecutionProviderSelector` chooses DirectML or the CPU fallback. It is
deliberately free of ONNX Runtime types so both branches are unit tested on a
machine with no GPU; `OnnxSessionFactory` turns a plan into real session options
and additionally falls back if session creation itself fails, since a driver can
refuse the device after the probe says yes.

**What the denoise loop still needs**: a CLIP tokenizer over the vocab/merges
files; text-encoder inference for both prompts; a scheduler (Euler ancestral or
DPM++ 2M); the per-step U-Net loop applying classifier-free guidance; and a VAE
decode to 512×512. Until then `OnnxIconGenerator.GenerateAsync` throws rather
than pretending.

## Verification

```bash
dotnet test tests/WowIconForge.Core.Tests     # 148 passed
```

**Not verified here**: `WowIconForge.App` has never been compiled. This container
runs Linux, WPF requires the WindowsDesktop SDK targets, and the Ubuntu-packaged
.NET SDK omits them (`Microsoft.NET.Sdk.WindowsDesktop` is absent from the SDK
layout, so even `dotnet sln add` rejects the project). The official SDK download
is blocked by this environment's egress policy. The solution file therefore lists
all three projects but was hand-written rather than generated, and the App
project's first real build will be on your machine. Core and the tests are built
and run in both Debug and Release.

## Dependency note

`SixLabors.ImageSharp` 3.1.12 provides Lanczos resampling and the PNG codec.
**ImageSharp 3.x is licensed under the Six Labors Split License** — free for open
source and for companies under $1M revenue, paid otherwise. If that is a problem,
2.1.x is Apache-2.0 and has the APIs used here, or the Lanczos path could be
written by hand as the unsharp mask already is.

`Microsoft.ML.OnnxRuntime.DirectML` 1.24.4 supplies the DirectML provider and the
CPU fallback. It is a Windows-native package; Core compiles against its managed
API, so the library still builds anywhere.
