#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-xlsx2pdf-libreoffice:local}"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/samples/out}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
API_URL="${API_URL:-http://127.0.0.1:18083}"

usage() {
  cat <<'EOF'
使い方:
  ./convert.sh <入力.xlsx>

環境変数:
  IMAGE_NAME     イメージ名 (既定: xlsx2pdf-libreoffice:local) ※ docker run 経路のみ
  OUT_DIR         PDFの出力先ディレクトリ (既定: このリポジトリの samples/out)
  COMPOSE_FILE    docker compose のファイルパス
  API_URL         API のベース URL (既定: http://127.0.0.1:18083。compose は 127.0.0.1:18083→8080)

docker compose で `api` が起動中なら HTTP で /convert を呼び出します。
それ以外は docker run で LibreOffice を直接実行します。

例:
  docker compose up -d --build
  cp ~/Desktop/sample.xlsx samples/in/
  ./convert.sh samples/in/sample.xlsx
  open samples/out/sample.pdf
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

INPUT_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
if [[ ! -f "$INPUT_PATH" ]]; then
  echo "ファイルが見つかりません: $INPUT_PATH" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

FILENAME="$(basename "$INPUT_PATH")"
PDF_NAME="${FILENAME%.*}.pdf"
INPUT_DIR="$(dirname "$INPUT_PATH")"

compose_api_running() {
  [[ -f "$COMPOSE_FILE" ]] || return 1
  docker compose -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null | grep -qx api
}

if compose_api_running; then
  echo "変換 (HTTP $API_URL/convert): $INPUT_PATH -> $OUT_DIR/"
  curl -fsS -X POST "$API_URL/convert" \
    -H "Accept: application/pdf" \
    -F "file=@${INPUT_PATH};filename=${FILENAME}" \
    -o "$OUT_DIR/$PDF_NAME"
else
  if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "イメージをビルドします: $IMAGE_NAME"
    docker build -t "$IMAGE_NAME" "$ROOT_DIR"
  fi

  echo "変換 (docker run): $INPUT_PATH -> $OUT_DIR/"
  docker run --rm \
    --entrypoint /bin/bash \
    -v "$INPUT_DIR:/work/in:ro" \
    -v "$OUT_DIR:/work/out" \
    "$IMAGE_NAME" \
    -c "exec libreoffice --headless --norestore --nologo --nofirststartwizard \
      --convert-to pdf --outdir /work/out \"/work/in/$FILENAME\""
fi

echo "完了: $OUT_DIR/$PDF_NAME"
