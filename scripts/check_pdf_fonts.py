#!/usr/bin/env python3
"""Excel 出力 PDF と LibreOffice 変換 PDF のフォント差分を確認する。"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = ROOT / "samples" / "in" / "完了報告書_2544094.xlsx"
DEFAULT_LO = ROOT / "samples" / "out" / "完了報告書_2544094.pdf"
DEFAULT_EXCEL = ROOT / "samples" / "out" / "完了報告書_2544094_excel.pdf"


@dataclass
class PdfFont:
    name: str
    font_type: str
    embedded: str
    subset: str


@dataclass
class XlsxFont:
    font_id: int
    name: str
    size: str


def require_pdffonts() -> None:
    if subprocess.run(["which", "pdffonts"], capture_output=True).returncode != 0:
        raise SystemExit("pdffonts が必要です (poppler-utils)")


def read_pdffonts(path: Path) -> list[PdfFont]:
    proc = subprocess.run(["pdffonts", str(path)], capture_output=True, text=True, check=True)
    fonts: list[PdfFont] = []
    for line in proc.stdout.splitlines()[2:]:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        fonts.append(
            PdfFont(
                name=parts[0],
                font_type=parts[1],
                embedded=parts[4],
                subset=parts[5],
            )
        )
    return fonts


def read_xlsx_fonts(path: Path) -> list[XlsxFont]:
    with zipfile.ZipFile(path) as zf:
        styles = zf.read("xl/styles.xml").decode("utf-8")
    fonts: list[XlsxFont] = []
    for i, match in enumerate(re.finditer(r"<font>(.*?)</font>", styles, re.S)):
        name = re.search(r'<name val="([^"]+)"', match.group(1))
        size = re.search(r'<sz val="([^"]+)"', match.group(1))
        fonts.append(
            XlsxFont(
                font_id=i,
                name=name.group(1) if name else "?",
                size=size.group(1) if size else "?",
            )
        )
    return fonts


def normalize_pdf_font_name(name: str) -> str:
    base = re.sub(r"^[A-Z]{6}\+", "", name)
    return base.replace("-", " ").strip().lower()


def font_families(fonts: list[PdfFont]) -> set[str]:
    return {normalize_pdf_font_name(f.name) for f in fonts}


def fc_match(pattern: str) -> str:
    proc = subprocess.run(["fc-match", pattern], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def print_pdf_fonts(label: str, path: Path) -> list[PdfFont]:
    fonts = read_pdffonts(path)
    print(f"[{label}] {path.name}")
    for font in fonts:
        print(
            f"  - {font.name} ({font.font_type}, emb={font.embedded}, sub={font.subset})"
        )
    print(f"  families: {', '.join(sorted(font_families(fonts)))}")
    print()
    return fonts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--lo-pdf", type=Path, default=DEFAULT_LO)
    parser.add_argument("--excel-pdf", type=Path, default=DEFAULT_EXCEL)
    args = parser.parse_args(argv)

    require_pdffonts()

    if args.xlsx.is_file():
        print("=== xlsx で指定されている主なフォント ===")
        used = {}
        for font in read_xlsx_fonts(args.xlsx):
            used[font.name] = font
        for name in sorted(used):
            print(f"  - {name} (例: size={used[name].size})")
        print()

    excel_fonts: list[PdfFont] = []
    lo_fonts: list[PdfFont] = []

    if args.excel_pdf.is_file():
        excel_fonts = print_pdf_fonts("excel pdf", args.excel_pdf)
    else:
        print(f"[excel pdf] なし: {args.excel_pdf}\n")

    if args.lo_pdf.is_file():
        lo_fonts = print_pdf_fonts("libreoffice pdf", args.lo_pdf)
    else:
        print(f"[libreoffice pdf] なし: {args.lo_pdf}\n")

    if excel_fonts and lo_fonts:
        excel_set = font_families(excel_fonts)
        lo_set = font_families(lo_fonts)
        common = excel_set & lo_set
        print("=== 判定 ===")
        print(f"  共通フォント: {', '.join(sorted(common)) if common else '(なし)'}")
        print(f"  Excel のみ: {', '.join(sorted(excel_set - lo_set))}")
        print(f"  LibreOffice のみ: {', '.join(sorted(lo_set - excel_set))}")
        if excel_set == lo_set:
            print("  結果: PDF 埋め込みフォントは一致")
        else:
            print("  結果: PDF 埋め込みフォントは一致しません")
        print()

    if subprocess.run(["which", "fc-match"], capture_output=True).returncode == 0:
        print("=== コンテナ内フォント置換 (fc-match) ===")
        for pattern in ("MS PGothic", "ＭＳ Ｐゴシック", "游ゴシック", "Yu Gothic"):
            print(f"  {pattern}: {fc_match(pattern)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
