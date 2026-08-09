#!/usr/bin/env bash
#
# Launch the WoW icon LoRA training run against kohya_ss/sd-scripts.
#
#   SD_SCRIPTS=~/src/sd-scripts ./training/train_lora.sh
#
# Any extra arguments are forwarded to train_network.py and override the TOML,
# which is the quickest way to sweep a single knob:
#
#   ./training/train_lora.sh --network_dim 64 --output_name wowicon_dim64
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SD_SCRIPTS="${SD_SCRIPTS:-$HOME/src/sd-scripts}"

CONFIG="$REPO_ROOT/training/lora_sd15.toml"
DATASET_CONFIG="$REPO_ROOT/training/dataset_sd15.toml"

die() { echo "error: $*" >&2; exit 1; }

# Read a top-level string setting out of a TOML file, so the paths live in the
# configs only and this script never disagrees with them.
toml_str() { sed -n "s/^[[:space:]]*$2 = \"\\(.*\\)\"/\\1/p" "$1" | head -1; }

[ -d "$SD_SCRIPTS" ] || die "sd-scripts not found at $SD_SCRIPTS (set SD_SCRIPTS=...)"
[ -f "$SD_SCRIPTS/train_network.py" ] || die "$SD_SCRIPTS has no train_network.py"
[ -f "$CONFIG" ] || die "missing $CONFIG"
[ -f "$DATASET_CONFIG" ] || die "missing $DATASET_CONFIG"

# Relative paths in both TOMLs resolve against the working directory.
cd "$REPO_ROOT"

SUBSET_DIR="$(toml_str "$DATASET_CONFIG" image_dir)"
OUTPUT_DIR="$(toml_str "$CONFIG" output_dir)"
LOGGING_DIR="$(toml_str "$CONFIG" logging_dir)"
SAMPLE_PROMPTS="$(toml_str "$CONFIG" sample_prompts)"

[ -n "$SUBSET_DIR" ] || die "no image_dir found in $DATASET_CONFIG"
[ -d "$SUBSET_DIR" ] \
    || die "dataset_sd15.toml points at '$SUBSET_DIR', which does not exist -- run python -m wowicons first"
[ -f "$SAMPLE_PROMPTS" ] \
    || die "missing $SAMPLE_PROMPTS -- run python -m wowicons.prompts"

IMAGE_COUNT="$(find "$SUBSET_DIR" -maxdepth 1 -name '*.png' | wc -l)"
CAPTION_COUNT="$(find "$SUBSET_DIR" -maxdepth 1 -name '*.txt' | wc -l)"
[ "$IMAGE_COUNT" -gt 0 ] || die "no PNGs in $SUBSET_DIR"
[ "$IMAGE_COUNT" -eq "$CAPTION_COUNT" ] \
    || die "$IMAGE_COUNT images but $CAPTION_COUNT captions in $SUBSET_DIR"

echo "sd-scripts:  $SD_SCRIPTS"
echo "dataset:     $SUBSET_DIR ($IMAGE_COUNT image/caption pairs)"
echo "output:      $OUTPUT_DIR"
echo "samples:     $OUTPUT_DIR/sample (one set per epoch)"
echo

mkdir -p "$OUTPUT_DIR" "$LOGGING_DIR"

accelerate launch \
    --num_cpu_threads_per_process 4 \
    "$SD_SCRIPTS/train_network.py" \
    --config_file "$CONFIG" \
    --dataset_config "$DATASET_CONFIG" \
    "$@"
