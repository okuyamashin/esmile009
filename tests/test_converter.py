"""converter のユニットテスト。"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from app.converter import (
    convert_xlsx_to_pdf,
    drop_blank_page2,
    find_best_scale,
    page2_text,
    patch_logo_footer_font_sizes,
    patch_page_margins_left,
    patch_page_margins_right,
    pdf_has_overflow_on_page2,
    pdf_is_acceptable,
    pdf_page_count,
    read_page_margins_left,
    read_page_margins_right,
    read_page_setup_scale,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_XLSX = ROOT / "samples" / "in" / "完了報告書_2544094.xlsx"
SAMPLE_XLSX_ALT = ROOT / "samples" / "in" / "完了報告書_2544674.xlsx"
EXCEL_REF_PDF = ROOT / "samples" / "out" / "完了報告書_2544094_excel.pdf"


class PdfPageCountTests(unittest.TestCase):
    def test_counts_pages_from_bytes(self) -> None:
        one_page = b"%PDF-1.4\n1 0 obj<</Type/Pages/Kids[2 0 R]/Count 1>>endobj\n"
        self.assertEqual(pdf_page_count(one_page), 1)


class PageSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_XLSX.is_file():
            raise unittest.SkipTest(f"sample not found: {SAMPLE_XLSX}")

    def test_sample_has_scale_85(self) -> None:
        scale = read_page_setup_scale(SAMPLE_XLSX.read_bytes())
        self.assertEqual(scale, 85)

    def test_prepare_applies_lo_compensation(self) -> None:
        from app.converter import _prepare_xlsx_bytes

        prepared = _prepare_xlsx_bytes(SAMPLE_XLSX.read_bytes(), ".xlsx", None)
        self.assertEqual(read_page_margins_left(prepared), "1.0")
        self.assertEqual(read_page_margins_right(prepared), "0")
        self.assertEqual(read_page_setup_scale(prepared), 88)


def _cell_font_size(data: bytes, ref: str) -> float | None:
    import io
    import re
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = zf.read("xl/styles.xml").decode("utf-8")
    cell = re.search(rf'<c r="{ref}" s="(\d+)"', sheet)
    if not cell:
        return None
    style_id = int(cell.group(1))
    xfs_block = re.search(r"<cellXfs count=\"\d+\">(.*?)</cellXfs>", styles, re.S)
    if not xfs_block:
        return None
    xfs = re.findall(r"<xf\b.*?(?:/>|>.*?</xf>)", xfs_block.group(1), re.S)
    fonts = re.findall(r"<font>.*?</font>", styles, re.S)
    xf = xfs[style_id]
    font_id = int(re.search(r'fontId="(\d+)"', xf).group(1))
    font = fonts[font_id]
    size = re.search(r'<sz val="(\d+(?:\.\d+)?)"', font)
    return float(size.group(1)) if size else None


class PageMarginsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_XLSX.is_file():
            raise unittest.SkipTest(f"sample not found: {SAMPLE_XLSX}")

    def test_sample_has_left_margin_07(self) -> None:
        left = read_page_margins_left(SAMPLE_XLSX.read_bytes())
        self.assertEqual(left, "0.7")

    def test_sample_has_right_margin_07(self) -> None:
        right = read_page_margins_right(SAMPLE_XLSX.read_bytes())
        self.assertEqual(right, "0.7")

    def test_patches_left_margin(self) -> None:
        original = SAMPLE_XLSX.read_bytes()
        patched = patch_page_margins_left(original, "1.0")
        self.assertEqual(read_page_margins_left(patched), "1.0")
        self.assertEqual(read_page_margins_left(original), "0.7")

    def test_patches_right_margin(self) -> None:
        original = SAMPLE_XLSX.read_bytes()
        patched = patch_page_margins_right(original, "0")
        self.assertEqual(read_page_margins_right(patched), "0")
        self.assertEqual(read_page_margins_right(original), "0.7")


class AlternateSamplePrintSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_XLSX_ALT.is_file():
            raise unittest.SkipTest(f"sample not found: {SAMPLE_XLSX_ALT}")

    def test_alt_sample_has_print_settings(self) -> None:
        original = SAMPLE_XLSX_ALT.read_bytes()
        self.assertEqual(read_page_margins_left(original), "0.7")
        self.assertEqual(read_page_margins_right(original), "0.7")
        self.assertEqual(read_page_setup_scale(original), 85)

    def test_prepare_normalizes_and_applies_lo_compensation_to_alt_sample(self) -> None:
        from app.converter import _prepare_xlsx_bytes

        prepared = _prepare_xlsx_bytes(SAMPLE_XLSX_ALT.read_bytes(), ".xlsx", None)
        self.assertEqual(read_page_margins_left(prepared), "1.0")
        self.assertEqual(read_page_margins_right(prepared), "0")
        self.assertEqual(read_page_setup_scale(prepared), 88)

    def test_alt_sample_fits_one_page_when_libreoffice_available(self) -> None:
        if not _libreoffice_available():
            raise unittest.SkipTest("libreoffice not available")
        from app.converter import _convert_bytes_to_pdf_bytes

        pdf_bytes = _convert_bytes_to_pdf_bytes(SAMPLE_XLSX_ALT.read_bytes(), ".xlsx")
        self.assertEqual(pdf_page_count(pdf_bytes), 1)
        self.assertGreater(len(pdf_bytes), 1000)


class LogoFooterFontPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_XLSX.is_file():
            raise unittest.SkipTest(f"sample not found: {SAMPLE_XLSX}")

    def test_shrinks_only_logo_footer_cells(self) -> None:
        original = SAMPLE_XLSX.read_bytes()
        patched = patch_logo_footer_font_sizes(original, shrink_pt=1.0)

        self.assertEqual(_cell_font_size(original, "N6"), 12.0)
        self.assertEqual(_cell_font_size(original, "N7"), 10.0)
        self.assertEqual(_cell_font_size(original, "N8"), 9.0)
        self.assertEqual(_cell_font_size(patched, "N6"), 11.0)
        self.assertEqual(_cell_font_size(patched, "N7"), 9.0)
        self.assertEqual(_cell_font_size(patched, "N8"), 8.0)
        # 同じ style を共有する P10 は変えない
        self.assertEqual(_cell_font_size(original, "P10"), 12.0)
        self.assertEqual(_cell_font_size(patched, "P10"), 12.0)

        import io
        import re
        import zipfile

        with zipfile.ZipFile(io.BytesIO(patched)) as zf:
            sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        n6_style = int(re.search(r'<c r="N6" s="(\d+)"', sheet).group(1))
        p10_style = int(re.search(r'<c r="P10" s="(\d+)"', sheet).group(1))
        self.assertNotEqual(n6_style, p10_style)


class SampleConvertIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not SAMPLE_XLSX.is_file():
            raise unittest.SkipTest(f"sample not found: {SAMPLE_XLSX}")
        if not _libreoffice_available():
            raise unittest.SkipTest("libreoffice not available")

    def test_sample_converts_to_single_page_pdf(self) -> None:
        out_dir = ROOT / "samples" / "out"
        pdf_path = convert_xlsx_to_pdf(SAMPLE_XLSX, out_dir)
        self.assertTrue(pdf_path.is_file())

        pdf_bytes = pdf_path.read_bytes()
        pages = pdf_page_count(pdf_bytes)
        self.assertEqual(pages, 1, f"expected 1 page, got {pages}")
        self.assertFalse(pdf_has_overflow_on_page2(pdf_bytes))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_best_scale_is_not_over_reduced(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_out = Path(tmp) / "out"
            tmp_out.mkdir()
            best = find_best_scale(SAMPLE_XLSX.read_bytes(), ".xlsx", tmp_out)
        self.assertIsNotNone(best)
        # 以前の 1 ずつ下げて最初の 1 ページ(71)より、できるだけ大きい scale を選ぶ
        self.assertGreaterEqual(best, 72)

    def test_matches_excel_reference_page_count(self) -> None:
        if not EXCEL_REF_PDF.is_file():
            raise unittest.SkipTest(f"excel reference not found: {EXCEL_REF_PDF}")

        out_dir = ROOT / "samples" / "out"
        pdf_path = convert_xlsx_to_pdf(SAMPLE_XLSX, out_dir)
        excel_pages = pdf_page_count(EXCEL_REF_PDF.read_bytes())
        lo_pages = pdf_page_count(pdf_path.read_bytes())
        self.assertEqual(lo_pages, excel_pages)


def _libreoffice_available() -> bool:
    try:
        proc = subprocess.run(
            ["libreoffice", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


if __name__ == "__main__":
    unittest.main()
