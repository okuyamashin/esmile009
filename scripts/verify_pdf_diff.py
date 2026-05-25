#!/usr/bin/env python3
"""Excel 出力 PDF と LibreOffice 変換 PDF の差分を検証する。"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = ROOT / "samples" / "in" / "完了報告書_2544094.xlsx"
DEFAULT_LO = ROOT / "samples" / "out" / "完了報告書_2544094.pdf"
DEFAULT_EXCEL = ROOT / "samples" / "out" / "完了報告書_2544094_excel.pdf"


@dataclass
class PdfReport:
    path: Path
    pages: int
    size: int
    creator: str
    producer: str
    page1_head: list[str]
    page2_text: str

    def summary(self) -> str:
        return (
            f"{self.path.name}: pages={self.pages}, size={self.size}, "
            f"creator={self.creator or '-'}, producer={self.producer or '-'}"
        )


def _pdfinfo(path: Path) -> dict[str, str]:
    proc = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, check=True)
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def analyze_pdf(path: Path) -> PdfReport:
    info = _pdfinfo(path)
    pages = int(info.get("Pages", "0"))
    page1 = subprocess.run(
        ["pdftotext", "-f", "1", "-l", "1", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    page1_head = [line.strip() for line in page1.splitlines() if line.strip()][:10]
    page2_text = ""
    if pages >= 2:
        page2_text = subprocess.run(
            ["pdftotext", "-f", "2", "-l", "2", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    return PdfReport(
        path=path,
        pages=pages,
        size=path.stat().st_size,
        creator=info.get("Creator", ""),
        producer=info.get("Producer", ""),
        page1_head=page1_head,
        page2_text=page2_text,
    )


def read_page_setup(xlsx: Path) -> str:
    with zipfile.ZipFile(xlsx) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    match = re.search(r"<pageSetup[^>]*/>", sheet)
    return match.group(0) if match else "(none)"


def convert_with_scale(xlsx: Path, scale: int, out_dir: Path) -> Path:
    page_setup = (
        f'<pageSetup paperSize="9" scale="{scale}" fitToHeight="0" '
        f'orientation="portrait" r:id="rId1"/>'
    )
    patched = out_dir / f"scale{scale}.xlsx"
    with zipfile.ZipFile(xlsx, "r") as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                sheet = content.decode("utf-8")
                sheet = re.sub(r"<pageSetup[^>]*/>", page_setup, sheet)
                content = sheet.encode("utf-8")
            zout.writestr(item, content)

    subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--norestore",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(patched),
        ],
        check=True,
        capture_output=True,
    )
    return next(out_dir.glob("scale*.pdf"))


def find_lo_scale_threshold(xlsx: Path, start: int = 85, min_scale: int = 65) -> tuple[int | None, int | None]:
    """LibreOffice で 1 ページになる最大 scale を探す。"""
    last_two = None
    first_one = None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for scale in range(start, min_scale - 1, -1):
            pdf = convert_with_scale(xlsx, scale, tmp_dir)
            pages = analyze_pdf(pdf).pages
            if pages >= 2:
                last_two = scale
            if pages == 1 and first_one is None:
                first_one = scale
    return first_one, last_two


def print_report(label: str, report: PdfReport) -> None:
    print(f"[{label}] {report.summary()}")
    print("  page1 head:")
    for line in report.page1_head:
        print(f"    - {line}")
    if report.pages >= 2:
        snippet = report.page2_text.replace("\n", "\\n")[:80]
        print(f"  page2: {snippet!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--lo-pdf", type=Path, default=DEFAULT_LO)
    parser.add_argument("--excel-pdf", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--scan-scale", action="store_true", help="LibreOffice 用 scale 閾値を探索")
    args = parser.parse_args(argv)

    for tool in ("pdfinfo", "pdftotext", "libreoffice"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            print(f"必要コマンドが見つかりません: {tool}", file=sys.stderr)
            return 1

    if not args.xlsx.is_file():
        print(f"xlsx がありません: {args.xlsx}", file=sys.stderr)
        return 1

    print("=== Excel 印刷設定 ===")
    print(read_page_setup(args.xlsx))
    print()

    if args.excel_pdf.is_file():
        print_report("excel", analyze_pdf(args.excel_pdf))
    else:
        print(f"[excel] 参照 PDF なし: {args.excel_pdf}")

    if args.lo_pdf.is_file():
        print_report("libreoffice", analyze_pdf(args.lo_pdf))
    else:
        print(f"[libreoffice] PDF なし: {args.lo_pdf}")

    if args.scan_scale:
        print()
        print("=== LibreOffice scale 閾値 (xlsx の scale を書き換え) ===")
        one, two = find_lo_scale_threshold(args.xlsx)
        print(f"  1 ページになる scale (最大): {one}")
        print(f"  2 ページになる scale (最小): {two}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
