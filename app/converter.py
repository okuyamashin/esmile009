"""LibreOffice を使った Excel → PDF 変換。"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

CONVERT_TIMEOUT_SEC = int(os.environ.get("CONVERT_TIMEOUT_SEC", "120"))
PDF_MIN_SCALE = int(os.environ.get("PDF_MIN_SCALE", "65"))
PDF_SCALE_ADJUST = os.environ.get("PDF_SCALE_ADJUST", "0").lower() not in (
    "0",
    "false",
    "no",
)

# Excel の印刷設定（余白・倍率など）を尊重する既定の PDF 出力
CALC_PDF_EXPORT = "pdf"

PAGE_SETUP_RE = re.compile(
    r"<pageSetup\b([^>]*?)(?:/>|>\s*</pageSetup>)",
    re.S,
)
SCALE_ATTR_RE = re.compile(r'\bscale="(\d+)"')
PAGE_MARGINS_RE = re.compile(
    r"<pageMargins\b([^>]*?)(?:/>|>\s*</pageMargins>)",
    re.S,
)
MARGIN_LEFT_ATTR_RE = re.compile(r'\bleft="([^"]+)"')
MARGIN_RIGHT_ATTR_RE = re.compile(r'\bright="([^"]+)"')

DEFAULT_PAGE_MARGINS_XML = (
    '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
    'header="0.3" footer="0.3"/>'
)
DEFAULT_PAGE_SETUP_XML = (
    '<pageSetup paperSize="9" scale="85" fitToHeight="0" '
    'orientation="portrait" r:id="rId1"/>'
)

# LibreOffice は xlsx の左余白をそのまま使うが、Excel 本体の PDF 出力より左寄りになる。
# 完了報告書サンプルでは left=0.7 → 1.0 で Excel 出力に近づく。
DEFAULT_PAGE_MARGIN_LEFT = "1.0"
DEFAULT_PAGE_MARGIN_RIGHT = "0"
# 完了報告書サンプルでは 88% で 1 ページに収まる（xlsx 原本は 85%）。
DEFAULT_PAGE_SETUP_SCALE = 88
SZ_VAL_RE = re.compile(r'(<sz val=")(\d+(?:\.\d+)?)(")')

# ロゴ直下の会社情報（3 行）。セル単位でフォントだけ縮小する。
DEFAULT_LOGO_FOOTER_CELLS = ("N6", "N7", "N8")
FONT_BLOCK_RE = re.compile(r"<fonts count=\"(\d+)\">(.*?)</fonts>", re.S)
FONT_ENTRY_RE = re.compile(r"<font>.*?</font>", re.S)
CELLXFS_BLOCK_RE = re.compile(r"<cellXfs count=\"(\d+)\">(.*?)</cellXfs>", re.S)
XF_ENTRY_RE = re.compile(r"<xf\b.*?(?:/>|>.*?</xf>)", re.S)
SHEET_CELL_RE = re.compile(r'(<c r="([A-Z]+\d+)"[^>]*\ss=")(\d+)(")')


def _insert_print_block(sheet: str, block: str) -> str:
    for anchor in ("<drawing ", "<drawing>", "</worksheet>"):
        idx = sheet.find(anchor)
        if idx != -1:
            return sheet[:idx] + block + sheet[idx:]
    return sheet + block


def _ensure_page_margins(sheet: str) -> str:
    if PAGE_MARGINS_RE.search(sheet):
        return sheet
    return _insert_print_block(sheet, DEFAULT_PAGE_MARGINS_XML)


def _ensure_page_setup(sheet: str) -> str:
    if PAGE_SETUP_RE.search(sheet):
        return sheet
    return _insert_print_block(sheet, DEFAULT_PAGE_SETUP_XML)


def _patch_sheet1_xml(xlsx_bytes: bytes, mutator) -> bytes:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin, zipfile.ZipFile(
        out_buf, "w"
    ) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                sheet = content.decode("utf-8")
                sheet = mutator(sheet)
                content = sheet.encode("utf-8")
            zout.writestr(item, content)
    return out_buf.getvalue()


def _normalized_page_margins(
    attrs: str,
    *,
    left: str | None = None,
    right: str | None = None,
) -> str:
    left_match = MARGIN_LEFT_ATTR_RE.search(attrs)
    right_match = MARGIN_RIGHT_ATTR_RE.search(attrs)
    left_val = left if left is not None else (left_match.group(1) if left_match else "0.7")
    right_val = right if right is not None else (right_match.group(1) if right_match else "0.7")

    def _attr(name: str, default: str) -> str:
        match = re.search(rf'\b{name}="([^"]+)"', attrs)
        return match.group(1) if match else default

    return (
        f'<pageMargins left="{left_val}" right="{right_val}" '
        f'top="{_attr("top", "0.75")}" bottom="{_attr("bottom", "0.75")}" '
        f'header="{_attr("header", "0.3")}" footer="{_attr("footer", "0.3")}"/>'
    )


def build_libreoffice_cmd(src: Path, out_dir: Path) -> list[str]:
    return [
        "libreoffice",
        "--headless",
        "--norestore",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        CALC_PDF_EXPORT,
        "--outdir",
        str(out_dir),
        str(src),
    ]


def read_page_setup_scale(xlsx_bytes: bytes) -> int | None:
    """xlsx 内 sheet1 の pageSetup scale を返す。無ければ None。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        if "xl/worksheets/sheet1.xml" not in zf.namelist():
            return None
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    match = PAGE_SETUP_RE.search(sheet)
    if not match:
        return None
    scale_match = SCALE_ATTR_RE.search(match.group(1))
    if not scale_match:
        return None
    return int(scale_match.group(1))


def _page_setup_scale() -> int | None:
    raw = os.environ.get("PAGE_SETUP_SCALE", str(DEFAULT_PAGE_SETUP_SCALE)).strip()
    if raw.lower() in ("", "off", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PAGE_SETUP_SCALE


def patch_page_setup_scale(xlsx_bytes: bytes, scale: int) -> bytes:
    """sheet1 の pageSetup に scale を設定して xlsx バイト列を返す。"""

    def mutator(sheet: str) -> str:
        sheet = _ensure_page_setup(sheet)

        def repl(match: re.Match[str]) -> str:
            attrs = match.group(1)
            if SCALE_ATTR_RE.search(attrs):
                attrs = SCALE_ATTR_RE.sub(f'scale="{scale}"', attrs)
            else:
                attrs = f' scale="{scale}"{attrs}'
            return (
                f'<pageSetup paperSize="9" scale="{scale}" fitToHeight="0" '
                f'orientation="portrait" r:id="rId1"/>'
            )

        return PAGE_SETUP_RE.sub(repl, sheet, count=1)

    return _patch_sheet1_xml(xlsx_bytes, mutator)


def _page_margin_left() -> str | None:
    raw = os.environ.get("PAGE_MARGIN_LEFT", DEFAULT_PAGE_MARGIN_LEFT).strip()
    if raw.lower() in ("", "off", "none"):
        return None
    return raw


def read_page_margins_left(xlsx_bytes: bytes) -> str | None:
    """xlsx 内 sheet1 の pageMargins left を返す。無ければ None。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        if "xl/worksheets/sheet1.xml" not in zf.namelist():
            return None
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    match = PAGE_MARGINS_RE.search(sheet)
    if not match:
        return None
    left_match = MARGIN_LEFT_ATTR_RE.search(match.group(1))
    if not left_match:
        return None
    return left_match.group(1)


def patch_page_margins_left(xlsx_bytes: bytes, left: str) -> bytes:
    """sheet1 の pageMargins left を設定して xlsx バイト列を返す。"""

    def mutator(sheet: str) -> str:
        sheet = _ensure_page_margins(sheet)
        return PAGE_MARGINS_RE.sub(
            lambda match: _normalized_page_margins(match.group(1), left=left),
            sheet,
            count=1,
        )

    return _patch_sheet1_xml(xlsx_bytes, mutator)


def _page_margin_right() -> str | None:
    raw = os.environ.get("PAGE_MARGIN_RIGHT", DEFAULT_PAGE_MARGIN_RIGHT).strip()
    if raw.lower() in ("", "off", "none"):
        return None
    return raw


def read_page_margins_right(xlsx_bytes: bytes) -> str | None:
    """xlsx 内 sheet1 の pageMargins right を返す。無ければ None。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        if "xl/worksheets/sheet1.xml" not in zf.namelist():
            return None
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    match = PAGE_MARGINS_RE.search(sheet)
    if not match:
        return None
    right_match = MARGIN_RIGHT_ATTR_RE.search(match.group(1))
    if not right_match:
        return None
    return right_match.group(1)


def patch_page_margins_right(xlsx_bytes: bytes, right: str) -> bytes:
    """sheet1 の pageMargins right を設定して xlsx バイト列を返す。"""

    def mutator(sheet: str) -> str:
        sheet = _ensure_page_margins(sheet)
        return PAGE_MARGINS_RE.sub(
            lambda match: _normalized_page_margins(match.group(1), right=right),
            sheet,
            count=1,
        )

    return _patch_sheet1_xml(xlsx_bytes, mutator)


def _logo_footer_shrink_pt() -> float:
    raw = os.environ.get("LOGO_FOOTER_FONT_SHRINK_PT", "1").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0


def _logo_footer_cells() -> tuple[str, ...]:
    raw = os.environ.get("LOGO_FOOTER_CELLS", ",".join(DEFAULT_LOGO_FOOTER_CELLS))
    cells = tuple(cell.strip().upper() for cell in raw.split(",") if cell.strip())
    return cells or DEFAULT_LOGO_FOOTER_CELLS


def _shrink_font_size(font_xml: str, shrink_pt: float) -> str:
    match = SZ_VAL_RE.search(font_xml)
    if not match:
        return font_xml
    current = float(match.group(2))
    new_size = max(1.0, current - shrink_pt)
    if new_size.is_integer():
        new_text = str(int(new_size))
    else:
        new_text = f"{new_size:.1f}".rstrip("0").rstrip(".")
    return SZ_VAL_RE.sub(rf"\g<1>{new_text}\g<3>", font_xml, count=1)


def patch_logo_footer_font_sizes(
    xlsx_bytes: bytes,
    cells: tuple[str, ...] | None = None,
    shrink_pt: float | None = None,
) -> bytes:
    """ロゴ下の指定セルだけ font size を下げる（他セルへの影響を避ける）。"""
    target_cells = cells or _logo_footer_cells()
    delta = _logo_footer_shrink_pt() if shrink_pt is None else max(0.0, shrink_pt)
    if delta <= 0 or not target_cells:
        return xlsx_bytes

    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        sheet = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = zin.read("xl/styles.xml").decode("utf-8")

    fonts_match = FONT_BLOCK_RE.search(styles)
    xfs_match = CELLXFS_BLOCK_RE.search(styles)
    if not fonts_match or not xfs_match:
        return xlsx_bytes

    fonts = FONT_ENTRY_RE.findall(fonts_match.group(2))
    xfs = XF_ENTRY_RE.findall(xfs_match.group(2))
    if not fonts or not xfs:
        return xlsx_bytes

    style_by_cell: dict[str, int] = {}
    for ref in target_cells:
        cell_match = re.search(rf'<c r="{ref}" s="(\d+)"', sheet)
        if not cell_match:
            continue
        old_style = int(cell_match.group(1))
        if old_style >= len(xfs):
            continue
        xf_xml = xfs[old_style]
        font_id_match = re.search(r'fontId="(\d+)"', xf_xml)
        if not font_id_match:
            continue
        font_id = int(font_id_match.group(1))
        if font_id >= len(fonts):
            continue

        shrunk = _shrink_font_size(fonts[font_id], delta)
        new_font_id = next(
            (idx for idx, font in enumerate(fonts) if font == shrunk),
            None,
        )
        if new_font_id is None:
            fonts.append(shrunk)
            new_font_id = len(fonts) - 1

        new_xf_xml = re.sub(
            r'fontId="\d+"',
            f'fontId="{new_font_id}"',
            xf_xml,
            count=1,
        )
        new_style_id = next(
            (idx for idx, xf in enumerate(xfs) if xf == new_xf_xml),
            None,
        )
        if new_style_id is None:
            xfs.append(new_xf_xml)
            new_style_id = len(xfs) - 1
        style_by_cell[ref] = new_style_id

    if not style_by_cell:
        return xlsx_bytes

    styles = styles.replace(
        fonts_match.group(0),
        f'<fonts count="{len(fonts)}">{"".join(fonts)}</fonts>',
    )
    styles = styles.replace(
        xfs_match.group(0),
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>',
    )

    def repl_cell(match: re.Match[str]) -> str:
        ref = match.group(2)
        if ref not in style_by_cell:
            return match.group(0)
        return f"{match.group(1)}{style_by_cell[ref]}{match.group(4)}"

    sheet = SHEET_CELL_RE.sub(repl_cell, sheet)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin, zipfile.ZipFile(
        out_buf, "w"
    ) as zout:
        for item in zin.infolist():
            if item.filename == "xl/styles.xml":
                content = styles.encode("utf-8")
            elif item.filename == "xl/worksheets/sheet1.xml":
                content = sheet.encode("utf-8")
            else:
                content = zin.read(item.filename)
            zout.writestr(item, content)
    return out_buf.getvalue()


def _prepare_xlsx_bytes(
    xlsx_bytes: bytes,
    suffix: str,
    scale: int | None,
) -> bytes:
    if suffix != ".xlsx":
        return xlsx_bytes
    shrink_pt = _logo_footer_shrink_pt()
    if shrink_pt > 0:
        xlsx_bytes = patch_logo_footer_font_sizes(xlsx_bytes, shrink_pt=shrink_pt)
    margin_left = _page_margin_left()
    if margin_left is not None:
        xlsx_bytes = patch_page_margins_left(xlsx_bytes, margin_left)
    margin_right = _page_margin_right()
    if margin_right is not None:
        xlsx_bytes = patch_page_margins_right(xlsx_bytes, margin_right)
    target_scale = scale if scale is not None else _page_setup_scale()
    if target_scale is not None:
        xlsx_bytes = patch_page_setup_scale(xlsx_bytes, target_scale)
    return xlsx_bytes


def libreoffice_convert(src: Path, out_dir: Path) -> Path:
    """xlsx/xls を PDF に変換し、out_dir 内の PDF パスを返す。"""
    src = src.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = src.suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        raise ValueError("拡張子は .xlsx または .xls である必要があります")

    cmd = build_libreoffice_cmd(src, out_dir)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=CONVERT_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "変換に失敗しました"
        raise RuntimeError(msg[:2000])

    pdf_path = out_dir / f"{src.stem}.pdf"
    if not pdf_path.is_file():
        raise RuntimeError("PDF が生成されませんでした")
    return pdf_path


def pdf_page_count(data: bytes) -> int:
    """PDF のページ数を返す（外部ライブラリ不要の簡易パーサ）。"""
    match = re.search(rb"/Type\s*/Pages\b.*?/Count\s+(\d+)", data, re.S)
    if match:
        return int(match.group(1))
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", data))


def page2_text(data: bytes) -> str:
    """2 ページ目のテキスト。1 ページのみなら空文字。"""
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) < 2:
        return ""
    return (reader.pages[1].extract_text() or "").strip()


def pdf_has_overflow_on_page2(data: bytes) -> bool:
    """2 ページ目にロゴ断片など意味のある内容が残っているか。"""
    return bool(page2_text(data))


def drop_blank_page2(data: bytes) -> bytes:
    """2 ページ目が空なら 1 ページ PDF に整える。"""
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) != 2 or page2_text(data):
        return data

    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def keep_first_page_only(data: bytes) -> bytes:
    """LibreOffice が付ける 2 ページ目を除き、1 ページ目だけを返す。"""
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) <= 1:
        return data

    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def pdf_is_acceptable(data: bytes) -> bool:
    """1 ページ、または 2 ページ目が実質空なら許容。"""
    pages = pdf_page_count(data)
    if pages == 1:
        return True
    if pages == 2:
        return not pdf_has_overflow_on_page2(data)
    return False


def _convert_at_scale(
    xlsx_bytes: bytes,
    suffix: str,
    scale: int | None,
    tmp_out: Path,
) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_src = Path(tmp) / f"input{suffix}"
        tmp_src.write_bytes(_prepare_xlsx_bytes(xlsx_bytes, suffix, scale))
        pdf_path = libreoffice_convert(tmp_src, tmp_out)
        return pdf_path.read_bytes()


def find_best_scale(xlsx_bytes: bytes, suffix: str, tmp_out: Path) -> int | None:
    """溢れを解消する最大 scale を二分探索で求める（縮小は最小限）。"""
    original = read_page_setup_scale(xlsx_bytes)
    if original is None or suffix != ".xlsx":
        return None

    lo, hi = PDF_MIN_SCALE, original
    best: int | None = None

    while lo <= hi:
        mid = (lo + hi) // 2
        pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, mid, tmp_out)
        if pdf_is_acceptable(pdf_bytes):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return best


def _should_adjust_scale(suffix: str) -> bool:
    """固定倍率が無いときだけ、必要に応じて倍率探索を行う。"""
    if _page_setup_scale() is not None:
        return False
    return PDF_SCALE_ADJUST or (
        suffix == ".xlsx" and _page_margin_left() is not None
    )


def _convert_bytes_to_pdf_bytes(xlsx_bytes: bytes, suffix: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "out"
        tmp_out.mkdir()

        if _should_adjust_scale(suffix) and suffix == ".xlsx":
            scale = find_best_scale(xlsx_bytes, suffix, tmp_out)
            if scale is None:
                pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, None, tmp_out)
            else:
                pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, scale, tmp_out)
        else:
            pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, None, tmp_out)

        return keep_first_page_only(pdf_bytes)


def convert_xlsx_to_pdf(src: Path, out_dir: Path) -> Path:
    """xlsx/xls を PDF に変換し、out_dir/{stem}.pdf を返す。"""
    src = src.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    suffix = src.suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        raise ValueError("拡張子は .xlsx または .xls である必要があります")

    pdf_bytes = _convert_bytes_to_pdf_bytes(src.read_bytes(), suffix)
    dest = out_dir / f"{src.stem}.pdf"
    dest.write_bytes(pdf_bytes)
    return dest
