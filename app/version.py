"""アプリのバージョン情報。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT_DIR / "VERSION"


def read_version() -> str:
    if VERSION_FILE.is_file():
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "0.0.0"


def read_git_commit() -> str:
    commit = os.environ.get("GIT_COMMIT", "").strip()
    return commit or "unknown"


APP_VERSION = read_version()
GIT_COMMIT = read_git_commit()


def health_payload() -> dict[str, str]:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "git_commit": GIT_COMMIT,
    }
