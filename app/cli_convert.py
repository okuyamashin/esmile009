"""convert.sh から呼ぶ CLI。"""

from __future__ import annotations

import sys
from pathlib import Path

from app.converter import convert_xlsx_to_pdf


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("使い方: python -m app.cli_convert <入力.xlsx> <出力ディレクトリ>", file=sys.stderr)
        return 1

    src = Path(args[0])
    out_dir = Path(args[1])
    if not src.is_file():
        print(f"ファイルが見つかりません: {src}", file=sys.stderr)
        return 1

    try:
        pdf_path = convert_xlsx_to_pdf(src, out_dir)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
