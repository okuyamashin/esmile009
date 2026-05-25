#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$ROOT/.githooks/pre-commit"
git -C "$ROOT" config core.hooksPath .githooks
echo "git hooks installed: core.hooksPath=.githooks"
