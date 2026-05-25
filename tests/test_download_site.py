"""テスト用ダウンロード API のテスト。"""

from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path

from app.main import TEST_DOWNLOAD_XLSX, test_download_file, test_download_page

ROOT = Path(__file__).resolve().parents[1]


class TestDownloadSiteTests(unittest.TestCase):
    def test_page_is_available(self) -> None:
        response = test_download_page()
        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("テスト用 Excel ダウンロード", body)
        self.assertIn("完了報告書_2544094.xlsx", body)
        self.assertIn('href="/test-download/file"', body)

    def test_downloads_sample_xlsx_when_present(self) -> None:
        if not TEST_DOWNLOAD_XLSX.is_file():
            raise unittest.SkipTest(f"sample not found: {TEST_DOWNLOAD_XLSX}")

        response = test_download_file()
        path = getattr(response, "path", None)
        self.assertIsNotNone(path)
        with zipfile.ZipFile(path) as zf:
            self.assertIn("xl/workbook.xml", zf.namelist())


if __name__ == "__main__":
    unittest.main()
