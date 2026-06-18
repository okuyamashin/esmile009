"""変換入出力のサーバー保存。"""

from __future__ import annotations

import os
import re
from pathlib import Path

SAVED_FILE_NAME_RE = re.compile(r"^\d{14}\.(pdf|xlsx|xls)$")
DEFAULT_SAVE_DIR = "/var/lib/esmile009/convert"

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def convert_save_enabled() -> bool:
    raw = os.environ.get("CONVERT_SAVE", "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def save_dir() -> Path:
    path = Path(os.environ.get("CONVERT_SAVE_DIR", DEFAULT_SAVE_DIR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_saved_filename(filename: str) -> str:
    name = Path(filename).name
    if not SAVED_FILE_NAME_RE.fullmatch(name):
        raise ValueError("無効なファイル名です")
    return name


def saved_filename_for_key(save_key: str, suffix: str) -> str:
    ext = suffix.lower()
    if ext not in (".pdf", ".xlsx", ".xls"):
        raise ValueError("無効な拡張子です")
    if not re.fullmatch(r"\d{14}", save_key):
        raise ValueError("無効な保存キーです")
    return f"{save_key}{ext}"


def save_file(body: bytes, filename: str) -> Path | None:
    if not convert_save_enabled():
        return None
    name = validate_saved_filename(filename)
    dest = save_dir() / name
    dest.write_bytes(body)
    return dest


def saved_file_path(filename: str) -> Path | None:
    if not convert_save_enabled():
        return None
    name = validate_saved_filename(filename)
    path = save_dir() / name
    return path if path.is_file() else None


def media_type_for_filename(filename: str) -> str:
    name = validate_saved_filename(filename)
    ext = Path(name).suffix.lower()
    return MEDIA_TYPES[ext]
