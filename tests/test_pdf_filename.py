"""PDF ファイル名のテスト。"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.pdf_filename import timestamp_pdf_filename, timestamp_save_key


class PdfFilenameTests(unittest.TestCase):
    @patch.dict(os.environ, {"PDF_FILENAME_TZ": "Asia/Tokyo"}, clear=False)
    @patch("app.pdf_filename.datetime")
    def test_timestamp_save_key(self, mock_datetime) -> None:
        mock_datetime.now.return_value = datetime(
            2026, 6, 18, 15, 4, 5, tzinfo=ZoneInfo("Asia/Tokyo")
        )
        self.assertEqual(timestamp_save_key(), "20260618150405")
        self.assertEqual(timestamp_pdf_filename(), "20260618150405.pdf")


if __name__ == "__main__":
    unittest.main()
