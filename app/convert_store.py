"""変換 PDF のサーバー保存。"""

from __future__ import annotations

import os
import re
from pathlib import Path

SAVED_PDF_NAME_RE = re.compile(r"^\d{14}\.pdf$")
DEFAULT_SAVE_DIR = "/var/lib/esmile009/convert"


def convert_save_enabled() -> bool:
    raw = os.environ.get("CONVERT_SAVE", "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def save_dir() -> Path:
    path = Path(os.environ.get("CONVERT_SAVE_DIR", DEFAULT_SAVE_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_saved_filename(filename: str) -> str:
    name = Path(filename).name
    if not SAVED_PDF_NAME_RE.fullmatch(name):
        raise ValueError("無効なファイル名です")
    return name


def save_pdf(body: bytes, filename: str) -> Path | None:
    if not convert_save_enabled():
        return None
    name = validate_saved_filename(filename)
    dest = save_dir() / name
    dest.write_bytes(body)
    return dest


def saved_pdf_path(filename: str) -> Path | None:
    if not convert_save_enabled():
        return None
    name = validate_saved_filename(filename)
    path = save_dir() / name
    return path if path.is_file() else None
