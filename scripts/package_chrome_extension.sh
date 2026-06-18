#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXT_DIR="$ROOT_DIR/chrome-extension"
OUT_DIR="$ROOT_DIR/dist"
VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
ZIP_NAME="esmile009-chrome-extension-${VERSION}.zip"
ZIP_PATH="$OUT_DIR/$ZIP_NAME"

mkdir -p "$OUT_DIR"
rm -f "$ZIP_PATH"

(
  cd "$EXT_DIR"
  zip -r "$ZIP_PATH" \
    manifest.json \
    content-script.js \
    service-worker.js \
    popup.html \
    popup.js \
    options.html \
    options.js \
    README.md
)

echo "created: $ZIP_PATH"
