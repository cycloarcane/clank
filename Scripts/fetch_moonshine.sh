#!/usr/bin/env bash
#
# Download the **exact** Moonshine ONNX weights we audited
# and record their SHA-256 hashes for reproducible installs.
#
set -euo pipefail

# Immutable commit on UsefulSensors/moonshine that contains
# the “float / merged / base” ONNX pair we use.
MOON_COMMIT=2501abf

MODEL_DIR="models/moonshine"
BASE_URL="https://huggingface.co/UsefulSensors/moonshine/resolve/$MOON_COMMIT/onnx/merged/base/float"
FILES=("encoder_model.onnx" "decoder_model_merged.onnx")

echo "→ Creating $MODEL_DIR"
mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

for f in "${FILES[@]}"; do
  echo "→ Downloading $f"
  curl -L -o "$f" "$BASE_URL/$f"
done

echo "→ Calculating checksums"
sha256sum "${FILES[@]}" > SHA256SUMS-$MOON_COMMIT

echo "All done.  Verify later with:"
echo "   sha256sum --quiet -c SHA256SUMS-$MOON_COMMIT-Tested && sha256sum --quiet -c SHA256SUMS-$MOON_COMMIT"
echo "Make sure they match"
