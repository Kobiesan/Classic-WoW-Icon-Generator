# Training the icon LoRA

Config for [kohya_ss / sd-scripts](https://github.com/kohya-ss/sd-scripts),
targeting **SD 1.5 at 512×512** — which is what the dataset pipeline already
produces, so nothing needs regenerating.

| File | What it is |
| --- | --- |
| `lora_sd15.toml` | Training arguments. Every knob is commented with why it's set. |
| `dataset_sd15.toml` | Dataset definition: resolution, batch size, caption handling. |
| `sample_prompts.txt` | Prompts rendered after every epoch. Regenerate from your manifest. |
| `train_lora.sh` | Launcher with pre-flight checks. Extra args pass through to sd-scripts. |

## Running it

```bash
# 1. Build the dataset (phase 1)
python -m wowicons --input /path/to/Interface/Icons --output ./dataset \
                   --overrides overrides.json

# 2. Point the sample prompts at your actual caption distribution
python -m wowicons.prompts --manifest dataset/manifest.csv \
                           --output training/sample_prompts.txt

# 3. Train
SD_SCRIPTS=~/src/sd-scripts ./training/train_lora.sh
```

Sweeping one knob doesn't need a config edit — anything on the command line
overrides the TOML:

```bash
./training/train_lora.sh --network_dim 64 --output_name wowicon_dim64
```

## Watching quality per epoch

`sample_every_n_epochs = 1` plus `sample_prompts` is sd-scripts' native
per-epoch sampling, so it needs no custom callback code. After each epoch it
renders every prompt into `dataset/model/sample/` with the epoch and step in
the filename:

```
dataset/model/sample/wowicon_lora_v1_e000003_00_20260809123045.png
```

Two things make those images actually comparable:

- **Each prompt pins its own seed** (`--d 101`, `--d 102`, …). Without fixed
  seeds you are comparing noise draws, not training progress, and every epoch
  looks arbitrarily different.
- **The prompts come from `manifest.csv`**, so they match the caption
  distribution the model trains on. Sampling prompts the dataset never
  contains tells you very little about whether training is working.

The last four prompts in the generated file are deliberately *not* in the
dataset (`wowicon, weapon, sword, glowing blue runes`). Those are the
overfitting tripwire: while they still render as plausible new icons, the LoRA
is generalising; once they collapse into near-copies of specific training
icons, you have gone too far and should fall back to an earlier epoch.

Because `save_every_n_epochs = 1`, every epoch is on disk (~18 MB each at
dim 32), so picking epoch 6 after the run is a normal outcome, not a redo.

## Tuning order

Roughly in the order worth trying. Change one thing at a time and compare the
same seeded sample grid.

| Symptom in the epoch samples | Knob | Direction |
| --- | --- | --- |
| Nothing icon-like by epoch 3-4 | `unet_lr` | Up to `2e-4` |
| Sharp early, then degrades into mush | `unet_lr` | Down to `5e-5`, or just use an earlier epoch |
| Style is right, shapes are vague | `network_dim` / `network_alpha` | Up to 64 / 32 |
| Copies training icons verbatim | `network_dim`, epochs | Down to 16 / 8, fewer epochs |
| LoRA hijacks words like "sword" in unrelated prompts | `text_encoder_lr` | Down to `2.5e-5`, or `network_train_unet_only = true` |
| Only fires on exact training captions | `caption_tag_dropout_rate` | On, `0.1` (in `dataset_sd15.toml`) |
| Washed out / milky vs. the training art | `noise_offset` | On, `0.0357` |
| Noisy loss, unstable early epochs | `min_snr_gamma` | Already on at 5; try 1 |

**Number of epochs is the knob to reach for last.** With per-epoch checkpoints
you don't tune it — you train 10 and pick the best one.

### Step budget

With ~4,000 icons, `num_repeats = 1`, and `batch_size = 4`, an epoch is about
1,000 steps, so the default 10 epochs is roughly 10,000 steps. That is a
sensible range for a style LoRA of this size.

Note that `num_repeats = 1` deliberately contradicts most LoRA tutorials, which
use 10-40. Those numbers exist to make a 20-image character set fill an epoch.
Here, a repeat count of 10 would mean 40,000 samples per epoch for no benefit.
**When you pass `--dataset_config`, sd-scripts ignores the `10_` prefix in the
folder name entirely** — that prefix is only read by the kohya_ss GUI's
folder-scan mode, so the pipeline's `--repeats` default is harmless here. If
you ever train through the GUI instead, regenerate with `--repeats 1`.

If you cut the set down (say, weapons only), raise `num_repeats` so that
images × repeats lands near 1,500-2,500 per epoch.

### Class imbalance

The pipeline prints category counts for a reason. On a full icon set, `armor`
and `weapon` dominate, and the LoRA will be correspondingly better at them.
Two ways to deal with it, both cheap:

- Split the imbalanced categories into their own subsets in
  `dataset_sd15.toml`, each with its own `num_repeats`, to level them up.
- Or accept it, and lean on the caption category term at generation time.

## VRAM

The defaults target roughly 12 GB. If you have less:

1. `gradient_checkpointing = true` (already in the config, commented) — costs
   20-30% speed.
2. `batch_size = 2` in `dataset_sd15.toml`.
3. `--network_train_unet_only` — a real quality tradeoff given these captions
   carry vocabulary, so try it last.

`cache_latents_to_disk = true` writes about 1.5 GB for 4,000 icons and is the
biggest single speedup available, since no augmentation changes the images
between epochs.

## If you'd rather use SDXL

Not shipped as a second config, because the deltas are small but the dataset
work isn't:

- Regenerate at 1024: `python -m wowicons ... --size 1024`. Be aware this
  upscales 64px source art 16×, so the training images are mostly interpolation
  — the reason SD 1.5 is the recommendation here.
- Train with `sdxl_train_network.py` instead of `train_network.py`.
- `resolution = 1024` in the dataset config, and drop `batch_size` to 1-2.
- Remove `clip_skip` (SDXL ignores it) and set
  `no_half_vae = true`, which avoids the known fp16 VAE NaN.
- Expect to lower `unet_lr` to about `4e-5`.

## Diffusers instead?

The pipeline output is a plain folder of `image.png` / `image.txt` pairs, so a
diffusers `train_text_to_image_lora.py` run reads it with only a small dataset
shim. The reason this phase went to sd-scripts is that per-epoch sampling,
per-epoch checkpoints and the caption handling (`keep_tokens`, tag shuffling)
are all built in, where diffusers would need each of them written and
maintained by hand.
