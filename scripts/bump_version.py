#!/usr/bin/env python3
"""VERSION を日付付きで更新する（pre-commit から呼ぶ）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"


def next_version(current: str, today: str) -> str:
    parts = current.split(".")
    if len(parts) >= 3 and parts[-1] == today:
        try:
            minor = int(parts[-2]) + 1
        except ValueError:
            minor = 1
        return f"{parts[0]}.{minor}.{today}"
    return f"0.1.{today}"


def main() -> None:
    today = date.today().strftime("%Y%m%d")
    current = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else ""
    new_version = next_version(current, today)
    VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")
    print(new_version)


if __name__ == "__main__":
    main()
