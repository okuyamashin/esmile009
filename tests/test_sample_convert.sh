#!/usr/bin/env bash
# サンプル xlsx を 1 ページ PDF に変換できることを確認する。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"
SAMPLE_XLSX="$ROOT_DIR/samples/in/完了報告書_2544094.xlsx"
OUT_DIR="$ROOT_DIR/samples/out"
IMAGE_NAME="${IMAGE_NAME:-xlsx2pdf-libreoffice:local}"

if [[ ! -f "$SAMPLE_XLSX" ]]; then
  echo "SKIP: sample xlsx not found: $SAMPLE_XLSX"
  exit 0
fi

mkdir -p "$OUT_DIR"

if command -v libreoffice >/dev/null 2>&1 && command -v "$PYTHON" >/dev/null 2>&1; then
  echo "テスト (local python): $SAMPLE_XLSX"
  cd "$ROOT_DIR"
  PYTHONPATH="$ROOT_DIR" "$PYTHON" -m unittest -v tests.test_converter
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "SKIP: libreoffice も Docker も利用できません" >&2
  exit 0
fi

if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  echo "イメージをビルドします: $IMAGE_NAME"
  docker build -t "$IMAGE_NAME" "$ROOT_DIR"
fi

echo "テスト (docker): $SAMPLE_XLSX"
docker run --rm \
  -v "$ROOT_DIR:/app" \
  -w /app \
  -e PYTHON=/venv/bin/python \
  "$IMAGE_NAME" \
  python -m unittest -v tests.test_converter

echo "OK: 1 ページ PDF を生成しました"
