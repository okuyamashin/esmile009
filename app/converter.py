"""LibreOffice を使った Excel → PDF 変換。"""

from __future__ import annotations

import io
import os
import re
import shutil
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

# LibreOffice(Docker) は xlsx の 0.7/0.7/85% より左寄りに出力する。
# 完了報告書では left=1.0 / right=0 / scale=88% で Excel PDF に近づく（2544094_prod 相当）。
# 2544674 は閉じタグ形式のため normalize_print_settings で先に整えてから適用する。
DEFAULT_PAGE_MARGIN_LEFT = "1.0"
DEFAULT_PAGE_MARGIN_RIGHT = "0"
DEFAULT_PAGE_SETUP_SCALE = "88"
SZ_VAL_RE = re.compile(r'(<sz val=")(\d+(?:\.\d+)?)(")')

# ロゴ直下の会社情報（3 行）。セル単位でフォントだけ縮小する。
DEFAULT_LOGO_FOOTER_CELLS = ("N6", "N7", "N8")
FONT_BLOCK_RE = re.compile(r"<fonts count=\"(\d+)\">(.*?)</fonts>", re.S)
FONT_ENTRY_RE = re.compile(r"<font>.*?</font>", re.S)
CELLXFS_BLOCK_RE = re.compile(r"<cellXfs count=\"(\d+)\">(.*?)</cellXfs>", re.S)
XF_ENTRY_RE = re.compile(r"<xf\b.*?(?:/>|>.*?</xf>)", re.S)
SHEET_CELL_RE = re.compile(r'(<c r="([A-Z]+\d+)"[^>]*\ss=")(\d+)(")')
CELL_BLOCK_RE = re.compile(r'(<c r="([A-Z]+\d+)"[^>]*)(?:/>|>.*?</c>)', re.S)
MERGE_CELL_RE = re.compile(r'<mergeCell ref="([^"]+)"')
SHARED_STRINGS_BLOCK_RE = re.compile(
    r"<sst\b[^>]*>(.*?)</sst>",
    re.S,
)
SHARED_STRING_ENTRY_RE = re.compile(r"<si>.*?</si>", re.S)
REMARKS_LABEL = "【備考】"
DEFAULT_REMARKS_PADDING_LINES = 2
CUSTOMER_NAME_LABEL = "お客様名"
CUSTOMER_CLEAR_MARKERS = ("空室", "不明")
SAMAS_RE = re.compile(r"[\s\u3000]*様[\s\u3000]*$")


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


def _libreoffice_bin() -> str:
    override = os.environ.get("LIBREOFFICE_BIN", "").strip()
    if override:
        return override
    for name in ("libreoffice", "soffice"):
        if shutil.which(name):
            return name
    return "libreoffice"


def build_libreoffice_cmd(src: Path, out_dir: Path) -> list[str]:
    return [
        _libreoffice_bin(),
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
    raw = os.environ.get("PAGE_SETUP_SCALE", DEFAULT_PAGE_SETUP_SCALE).strip()
    if raw.lower() in ("", "off", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        return int(DEFAULT_PAGE_SETUP_SCALE) if DEFAULT_PAGE_SETUP_SCALE.isdigit() else None


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


def normalize_print_settings(xlsx_bytes: bytes) -> bytes:
    """pageMargins/pageSetup を LibreOffice が読める形式に整える。値は原本を維持する。"""

    def mutator(sheet: str) -> str:
        if PAGE_MARGINS_RE.search(sheet):
            sheet = PAGE_MARGINS_RE.sub(
                lambda match: _normalized_page_margins(match.group(1)),
                sheet,
                count=1,
            )
        else:
            sheet = _insert_print_block(sheet, DEFAULT_PAGE_MARGINS_XML)

        if PAGE_SETUP_RE.search(sheet):

            def repl_setup(match: re.Match[str]) -> str:
                attrs = match.group(1)
                scale_match = SCALE_ATTR_RE.search(attrs)
                scale_val = scale_match.group(1) if scale_match else "85"
                orient_match = re.search(r'\borientation="([^"]+)"', attrs)
                orient_val = orient_match.group(1) if orient_match else "portrait"
                return (
                    f'<pageSetup paperSize="9" scale="{scale_val}" fitToHeight="0" '
                    f'orientation="{orient_val}" r:id="rId1"/>'
                )

            sheet = PAGE_SETUP_RE.sub(repl_setup, sheet, count=1)
        else:
            sheet = _insert_print_block(sheet, DEFAULT_PAGE_SETUP_XML)
        return sheet

    return _patch_sheet1_xml(xlsx_bytes, mutator)


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


def _remarks_padding_lines() -> int:
    raw = os.environ.get(
        "REMARKS_BOTTOM_PADDING_LINES",
        str(DEFAULT_REMARKS_PADDING_LINES),
    ).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_REMARKS_PADDING_LINES


def _xml_decode_text(text: str) -> str:
    return (
        text.replace("&#xA;", "\n")
        .replace("&#xD;", "\r")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _xml_encode_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r\n", "&#xA;")
        .replace("\n", "&#xA;")
        .replace("\r", "&#xA;")
    )


def _parse_shared_strings(shared_strings_xml: str) -> list[str]:
    block = SHARED_STRINGS_BLOCK_RE.search(shared_strings_xml)
    if not block:
        return []
    return [
        _xml_decode_text(re.sub(r"<[^>]+>", "", entry))
        for entry in SHARED_STRING_ENTRY_RE.findall(block.group(1))
    ]


def _serialize_shared_strings(shared_strings_xml: str, values: list[str]) -> str:
    match = re.search(r"(<sst\b[^>]*>)(.*?)(</sst>)", shared_strings_xml, re.S)
    if not match:
        return shared_strings_xml
    opening = re.sub(r'\bcount="\d+"', f'count="{len(values)}"', match.group(1))
    opening = re.sub(r'\buniqueCount="\d+"', f'uniqueCount="{len(values)}"', opening)
    entries = "".join(f"<si><t>{_xml_encode_text(value)}</t></si>" for value in values)
    return (
        shared_strings_xml[: match.start()]
        + opening
        + entries
        + match.group(3)
        + shared_strings_xml[match.end() :]
    )


def _read_sheet_cell_text(
    sheet: str,
    ref: str,
    shared_values: list[str],
) -> str | None:
    match = re.search(rf'<c r="{re.escape(ref)}"[^/]*?(?:/>|>.*?</c>)', sheet, re.S)
    if not match:
        return None
    cell = match.group(0)
    if ' t="s"' in cell:
        value_match = re.search(r"<v>(\d+)</v>", cell)
        if not value_match:
            return None
        idx = int(value_match.group(1))
        if idx >= len(shared_values):
            return None
        return shared_values[idx]
    if ' t="str"' in cell or ' t="inlineStr"' in cell:
        value_match = re.search(r"<v>(.*?)</v>", cell, re.S)
        if value_match:
            return _xml_decode_text(value_match.group(1))
        inline = re.findall(r"<t[^>]*>(.*?)</t>", cell, re.S)
        if inline:
            return _xml_decode_text("".join(inline))
    value_match = re.search(r"<v>(.*?)</v>", cell, re.S)
    if value_match:
        return _xml_decode_text(value_match.group(1))
    return None


def _normalize_spacing(text: str) -> str:
    return re.sub(r"[\s\u3000]+", " ", text).strip()


def _customer_name_core(text: str) -> str:
    return SAMAS_RE.sub("", _normalize_spacing(text)).strip()


def _should_clear_customer_name(text: str) -> bool:
    core = _customer_name_core(text)
    if not core:
        return True
    return any(marker in core for marker in CUSTOMER_CLEAR_MARKERS)


def _find_customer_name_ref(sheet: str, shared_values: list[str]) -> str | None:
    for match in re.finditer(r'<c r="([A-Z]+)(\d+)"', sheet):
        ref = f"{match.group(1)}{match.group(2)}"
        text = _read_sheet_cell_text(sheet, ref, shared_values)
        if text and CUSTOMER_NAME_LABEL in text:
            customer_ref = f"C{match.group(2)}"
            if re.search(rf'<c r="{re.escape(customer_ref)}"', sheet):
                return customer_ref
    return None


def _write_sheet_cell_text(
    sheet: str,
    ref: str,
    shared_values: list[str],
    shared_strings_xml: str,
    new_text: str,
) -> tuple[str, list[str], str]:
    cell_match = re.search(
        rf'(<c r="{re.escape(ref)}"[^/]*)(?:/>|>.*?</c>)',
        sheet,
        re.S,
    )
    if not cell_match:
        return sheet, shared_values, shared_strings_xml

    cell_xml = cell_match.group(0)
    if ' t="s"' in cell_xml:
        idx_match = re.search(r"<v>(\d+)</v>", cell_xml)
        if not idx_match:
            return sheet, shared_values, shared_strings_xml
        idx = int(idx_match.group(1))
        if idx >= len(shared_values):
            shared_values.extend([""] * (idx + 1 - len(shared_values)))
        shared_values[idx] = new_text
        shared_strings_xml = _serialize_shared_strings(shared_strings_xml, shared_values)
        return sheet, shared_values, shared_strings_xml

    encoded = _xml_encode_text(new_text)
    if ' t="str"' in cell_xml or ' t="inlineStr"' in cell_xml:
        if "<v>" in cell_xml:
            new_cell = re.sub(r"<v>.*?</v>", f"<v>{encoded}</v>", cell_xml, count=1, flags=re.S)
        else:
            new_cell = re.sub(
                r"<is>.*?</is>",
                f"<is><t>{encoded}</t></is>",
                cell_xml,
                count=1,
                flags=re.S,
            )
    elif "<v>" in cell_xml:
        new_cell = re.sub(r"<v>.*?</v>", f"<v>{encoded}</v>", cell_xml, count=1, flags=re.S)
    else:
        return sheet, shared_values, shared_strings_xml

    sheet = sheet.replace(cell_xml, new_cell, 1)
    return sheet, shared_values, shared_strings_xml


def _find_remarks_content_ref(sheet: str, shared_values: list[str]) -> str | None:
    for match in re.finditer(r'<c r="([A-Z]+)(\d+)"', sheet):
        ref = f"{match.group(1)}{match.group(2)}"
        text = _read_sheet_cell_text(sheet, ref, shared_values)
        if text and REMARKS_LABEL in text:
            return f"A{int(match.group(2)) + 1}"

    for merge_ref in MERGE_CELL_RE.findall(sheet):
        start, _end = merge_ref.split(":", 1)
        row_match = re.search(r"\d+", start)
        if start.startswith("A") and row_match and int(row_match.group()) >= 25:
            return start
    return None


def _xf_with_remarks_alignment(xf_xml: str) -> str:
    if re.search(r"<alignment\b", xf_xml):

        def repl_alignment(match: re.Match[str]) -> str:
            alignment = match.group(0)
            if re.search(r'vertical="', alignment):
                alignment = re.sub(r'vertical="[^"]*"', 'vertical="top"', alignment)
            else:
                alignment = alignment.replace("<alignment ", '<alignment vertical="top" ', 1)
            if re.search(r'shrinkToFit="', alignment):
                alignment = re.sub(r'shrinkToFit="[^"]*"', 'shrinkToFit="0"', alignment)
            else:
                alignment = alignment.replace("<alignment ", '<alignment shrinkToFit="0" ', 1)
            if 'wrapText=' not in alignment:
                alignment = alignment.replace("<alignment ", '<alignment wrapText="1" ', 1)
            return alignment

        return re.sub(r"<alignment\b[^>]*/>|<alignment\b[^>]*>.*?</alignment>", repl_alignment, xf_xml, count=1)

    if xf_xml.endswith("/>"):
        return xf_xml[:-2] + ' applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1" shrinkToFit="0"/></xf>'
    return re.sub(
        r"(<xf\b[^>]*)(>.*?</xf>|/>)",
        r'\1 applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1" shrinkToFit="0"/>\2',
        xf_xml,
        count=1,
    )


def _pad_remarks_text(text: str, extra_lines: int) -> str:
    normalized = text.rstrip("\r\n")
    if extra_lines <= 0:
        return normalized
    return normalized + ("\n" * extra_lines)


def patch_remarks_bottom_padding(
    xlsx_bytes: bytes,
    padding_lines: int | None = None,
) -> bytes:
    """備考結合セルの本文末尾に空行を足し、上詰め表示にする。"""
    extra_lines = _remarks_padding_lines() if padding_lines is None else max(0, padding_lines)
    if extra_lines <= 0:
        return xlsx_bytes

    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        sheet = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = zin.read("xl/styles.xml").decode("utf-8")
        shared_strings_xml = (
            zin.read("xl/sharedStrings.xml").decode("utf-8")
            if "xl/sharedStrings.xml" in zin.namelist()
            else ""
        )

    shared_values = _parse_shared_strings(shared_strings_xml)
    remarks_ref = _find_remarks_content_ref(sheet, shared_values)
    if not remarks_ref:
        return xlsx_bytes

    current_text = _read_sheet_cell_text(sheet, remarks_ref, shared_values)
    if current_text is None:
        return xlsx_bytes

    padded_text = _pad_remarks_text(current_text, extra_lines)
    if padded_text == current_text:
        return xlsx_bytes

    cell_match = re.search(
        rf'(<c r="{re.escape(remarks_ref)}"[^/]*)(?:/>|>.*?</c>)',
        sheet,
        re.S,
    )
    if not cell_match:
        return xlsx_bytes

    cell_xml = cell_match.group(0)
    style_match = re.search(r'\ss="(\d+)"', cell_xml)
    xfs_match = CELLXFS_BLOCK_RE.search(styles)
    if style_match and xfs_match:
        xfs = XF_ENTRY_RE.findall(xfs_match.group(2))
        old_style = int(style_match.group(1))
        if old_style < len(xfs):
            new_xf = _xf_with_remarks_alignment(xfs[old_style])
            new_style_id = next((idx for idx, xf in enumerate(xfs) if xf == new_xf), None)
            if new_style_id is None:
                xfs.append(new_xf)
                new_style_id = len(xfs) - 1
            styles = styles.replace(
                xfs_match.group(0),
                f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>',
            )
            sheet = sheet.replace(
                cell_xml,
                re.sub(r'\ss="\d+"', f' s="{new_style_id}"', cell_xml, count=1),
                1,
            )
            cell_xml = re.search(
                rf'(<c r="{re.escape(remarks_ref)}"[^/]*)(?:/>|>.*?</c>)',
                sheet,
                re.S,
            ).group(0)

    if ' t="s"' in cell_xml:
        idx_match = re.search(r"<v>(\d+)</v>", cell_xml)
        if not idx_match:
            return xlsx_bytes
        idx = int(idx_match.group(1))
        if idx >= len(shared_values):
            shared_values.extend([""] * (idx + 1 - len(shared_values)))
        shared_values[idx] = padded_text
        shared_strings_xml = _serialize_shared_strings(shared_strings_xml, shared_values)
    else:
        sheet, shared_values, shared_strings_xml = _write_sheet_cell_text(
            sheet,
            remarks_ref,
            shared_values,
            shared_strings_xml,
            padded_text,
        )

    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin, zipfile.ZipFile(
        out_buf, "w"
    ) as zout:
        for item in zin.infolist():
            if item.filename == "xl/styles.xml":
                content = styles.encode("utf-8")
            elif item.filename == "xl/worksheets/sheet1.xml":
                content = sheet.encode("utf-8")
            elif item.filename == "xl/sharedStrings.xml" and shared_strings_xml:
                content = shared_strings_xml.encode("utf-8")
            else:
                content = zin.read(item.filename)
            zout.writestr(item, content)
    return out_buf.getvalue()


def read_remarks_cell_text(xlsx_bytes: bytes) -> str | None:
    """備考本文セルの文字列を返す。無ければ None。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        if "xl/worksheets/sheet1.xml" not in zin.namelist():
            return None
        sheet = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        shared_strings_xml = (
            zin.read("xl/sharedStrings.xml").decode("utf-8")
            if "xl/sharedStrings.xml" in zin.namelist()
            else ""
        )
    shared_values = _parse_shared_strings(shared_strings_xml)
    remarks_ref = _find_remarks_content_ref(sheet, shared_values)
    if not remarks_ref:
        return None
    return _read_sheet_cell_text(sheet, remarks_ref, shared_values)


def patch_blank_customer_name(xlsx_bytes: bytes) -> bytes:
    """空室・不明・空白のお客様名は「様」ごと表示しない。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        sheet = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        shared_strings_xml = (
            zin.read("xl/sharedStrings.xml").decode("utf-8")
            if "xl/sharedStrings.xml" in zin.namelist()
            else ""
        )

    shared_values = _parse_shared_strings(shared_strings_xml)
    customer_ref = _find_customer_name_ref(sheet, shared_values)
    if not customer_ref:
        return xlsx_bytes

    current_text = _read_sheet_cell_text(sheet, customer_ref, shared_values)
    if current_text is None or not _should_clear_customer_name(current_text):
        return xlsx_bytes

    sheet, shared_values, shared_strings_xml = _write_sheet_cell_text(
        sheet,
        customer_ref,
        shared_values,
        shared_strings_xml,
        "",
    )

    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin, zipfile.ZipFile(
        out_buf, "w"
    ) as zout:
        for item in zin.infolist():
            if item.filename == "xl/worksheets/sheet1.xml":
                content = sheet.encode("utf-8")
            elif item.filename == "xl/sharedStrings.xml" and shared_strings_xml:
                content = shared_strings_xml.encode("utf-8")
            else:
                content = zin.read(item.filename)
            zout.writestr(item, content)
    return out_buf.getvalue()


def read_customer_name_text(xlsx_bytes: bytes) -> str | None:
    """お客様名セルの文字列を返す。無ければ None。"""
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
        if "xl/worksheets/sheet1.xml" not in zin.namelist():
            return None
        sheet = zin.read("xl/worksheets/sheet1.xml").decode("utf-8")
        shared_strings_xml = (
            zin.read("xl/sharedStrings.xml").decode("utf-8")
            if "xl/sharedStrings.xml" in zin.namelist()
            else ""
        )
    shared_values = _parse_shared_strings(shared_strings_xml)
    customer_ref = _find_customer_name_ref(sheet, shared_values)
    if not customer_ref:
        return None
    return _read_sheet_cell_text(sheet, customer_ref, shared_values)


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
    xlsx_bytes = patch_remarks_bottom_padding(xlsx_bytes)
    xlsx_bytes = patch_blank_customer_name(xlsx_bytes)
    xlsx_bytes = normalize_print_settings(xlsx_bytes)
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


def _convert_bytes_to_pdf_bytes(xlsx_bytes: bytes, suffix: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "out"
        tmp_out.mkdir()

        pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, None, tmp_out)
        if suffix == ".xlsx" and not pdf_is_acceptable(pdf_bytes):
            scale = find_best_scale(xlsx_bytes, suffix, tmp_out)
            if scale is not None:
                pdf_bytes = _convert_at_scale(xlsx_bytes, suffix, scale, tmp_out)

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
