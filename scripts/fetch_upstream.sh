#!/usr/bin/env bash
set -euo pipefail
# Download only the two original Kotlin files; verify content against pinned Git blob IDs.
REPO="https://raw.githubusercontent.com/OpenMOSS/MOSS-TTS-Nano"
REF="31f42bae0a181849864c7ee39e8b88990909065f"
BASE="examples/android_onnx_runtime/app/src/main/java/com/openmoss/ttsnano/onnxruntime"
DEST="app/src/main/java/com/openmoss/ttsnano/onnxruntime"
mkdir -p "$DEST"
for entry in 'MossOnnxDemoEngine.kt:6f1602a68b743051c264a580754e1a07739b27bc' 'DemoPrompts.kt:44282636b7c58d8c32fcaa239571d82c49088fc0'; do
  name="${entry%%:*}"
  sha="${entry##*:}"
  curl --fail --location --retry 3 --silent --show-error "$REPO/$REF/$BASE/$name" -o "$DEST/$name.tmp"
  actual="$(git hash-object "$DEST/$name.tmp")"
  if [ "$actual" != "$sha" ]; then
    echo "UPSTREAM HASH MISMATCH for $name: expected=$sha actual=$actual" >&2
    exit 1
  fi
  mv "$DEST/$name.tmp" "$DEST/$name"
  echo "UPSTREAM OK $name $sha"
done
