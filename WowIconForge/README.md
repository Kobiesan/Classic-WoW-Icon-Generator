# WoW Icon Forge

A Windows desktop app (C# / .NET 8 / WPF) that generates World of Warcraft-style
icons from text prompts with a local ONNX Stable Diffusion model, composites them
against a border template, and exports PNG or BLP.

Open `WowIconForge.sln` in Visual Studio 2022.

| Project | Target | What it is |
| --- | --- | --- |
| `src/WowIconForge.Core` | `net8.0` | Inference, compositing, BLP I/O. No UI dependencies. |
| `src/WowIconForge.App` | `net8.0-windows` | WPF UI. |
| `tests/WowIconForge.Core.Tests` | `net8.0` | xUnit. 191 tests. |

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
| Model download + verify, resolution | Implemented, 43 tests |
| Publish + Inno Setup installer | Implemented, not compiled here |
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

## Packaging

```powershell
.\publish.ps1                                          # app only, small installer
.\publish.ps1 -ModelsDirectory C:\sd15-onnx -Installer # models baked in, several GB
.\publish.ps1 -Installer                               # small installer + Inno Setup
```

`publish.ps1` runs the tests, then publishes **self-contained win-x64** so the
user needs no .NET install, and optionally compiles
`installer/WowIconForge.iss` with Inno Setup 6.

Deliberately **not** `PublishSingleFile`: ONNX Runtime and DirectML load native
libraries by name, and single-file publishing forces an extract-to-temp step
that is slower and breaks GPU enumeration on some drivers. Trimming is off for
the same family of reasons — both ONNX Runtime and WPF resolve types by
reflection, so a trimmed build fails at runtime rather than at publish.

### The models, both ways

The models are several gigabytes and cannot live in the executable. Both routes
are supported, and the app does not care which one you used —
`ModelDirectoryResolver` decides at startup:

1. the directory configured in Settings, if complete;
2. `<app folder>\models`, if the installer bundled one;
3. `%LOCALAPPDATA%\WowIconForge\models`, which is what the wizard downloads into.

The installer follows the same fork automatically. If the publish folder
contains a `models` sub-folder, Inno packages it and installs it beside the exe,
and first run is instant. If it does not, the installer stays small, tells the
user at the end of setup what will happen, and the first-run wizard downloads
instead.

The download target is under LocalAppData rather than Program Files on purpose:
the app installs per-machine, so writing gigabytes into its own folder would
need elevation every time.

### Downloading and verifying

`ModelDownloader` reads `model-sources.json`, fetches each file to a `.part`
name, checks its SHA-256, and only then moves it into place — so an interrupted
download can never masquerade as a good one. Files already present and verified
are skipped, which makes a failed install resumable rather than a 3 GB do-over.

Two deliberate refusals:

- **Unpinned entries are rejected by default.** An entry with no `sha256` cannot
  be verified, and downloading gigabytes you cannot check is what the hash
  exists to prevent. `allowUnpinned` overrides it explicitly.
- **Paths that escape the model folder are rejected**, at parse time and again
  at write time. A manifest is untrusted input that names files written to disk;
  `../../Startup/evil.exe` must never be honoured.

**`model-sources.json` ships as a template and will not download anything as
shipped.** Its URLs are placeholders and every hash is empty, so the downloader
refuses it outright. That is deliberate — I had no way to verify real URLs or
compute real checksums, and a manifest with plausible-looking but unverified
hashes is worse than one that obviously needs filling in. Two ways forward, both
documented in the file itself: point the app at an export you already have, or
fill in the URLs and hashes. `ModelDownloader.ComputeManifestAsync` generates a
fully pinned manifest from a folder on disk, so you never have to hash by hand.

## Verification

```bash
dotnet test tests/WowIconForge.Core.Tests     # 191 passed
```

**Verified on Linux**, despite the Windows target: the publish flag combination
(`-r win-x64 --self-contained -p:PublishReadyToRun=true`) produces a real
187-file native output, Core publishes for win-x64 with its ImageSharp and ONNX
Runtime assets intact, and the `VerifyDirectMLWasPublished` guard was exercised
in both directions — it fails the publish when `DirectML.dll` is absent and
passes when it is there.

**Not verified here**: `WowIconForge.App` has never been compiled, and neither
has the Inno Setup script. This container runs Linux; WPF requires the
WindowsDesktop SDK targets, and the Ubuntu-packaged .NET SDK omits them
(`Microsoft.NET.Sdk.WindowsDesktop` is absent from the SDK layout, so even
`dotnet sln add` rejects the project), while the official SDK download is
blocked by this environment's egress policy. PowerShell is not installed either,
so `publish.ps1` has not been parsed. The solution file lists all three projects
but was hand-written rather than generated. Core and the tests build and run in
both Debug and Release.

### One packaging bug this caught

`DirectML.dll` was silently missing from the publish output. `Microsoft.AI.DirectML`
ships it under `bin\x64-win\` rather than `runtimes\<rid>\native\`, so NuGet's
automatic native-asset copying does not see it; the copy lives in the package's
`build\*.targets`, and NuGet imports those only for **direct** references. Since
the package arrives transitively through `Microsoft.ML.OnnxRuntime.DirectML`,
nothing in the graph ever copied it, and the failure would only have surfaced as
"DirectML doesn't work" on a user's machine.

Fixed with a direct `PackageReference` in the App project, and the
`VerifyDirectMLWasPublished` target now fails the publish if either
`DirectML.dll` or `onnxruntime.dll` goes missing again.

## Dependency note

`SixLabors.ImageSharp` 3.1.12 provides Lanczos resampling and the PNG codec.
**ImageSharp 3.x is licensed under the Six Labors Split License** — free for open
source and for companies under $1M revenue, paid otherwise. If that is a problem,
2.1.x is Apache-2.0 and has the APIs used here, or the Lanczos path could be
written by hand as the unsharp mask already is.

`Microsoft.ML.OnnxRuntime.DirectML` 1.24.4 supplies the DirectML provider and the
CPU fallback. It is a Windows-native package; Core compiles against its managed
API, so the library still builds anywhere.
