"""変換入出力保存のテスト。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.convert_store import (
    save_file,
    saved_file_path,
    saved_filename_for_key,
    validate_saved_filename,
)
from app.main import app


class ConvertStoreTests(unittest.TestCase):
    def test_validate_saved_filename(self) -> None:
        self.assertEqual(validate_saved_filename("20260618122107.pdf"), "20260618122107.pdf")
        self.assertEqual(validate_saved_filename("20260618122107.xlsx"), "20260618122107.xlsx")
        with self.assertRaises(ValueError):
            validate_saved_filename("../secret.pdf")
        with self.assertRaises(ValueError):
            validate_saved_filename("report.pdf")

    def test_saved_filename_for_key(self) -> None:
        self.assertEqual(saved_filename_for_key("20260618122107", ".xlsx"), "20260618122107.xlsx")

    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_save_and_load_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                name = "20260618122107.pdf"
                saved = save_file(b"%PDF-1.6", name)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertTrue(saved.is_file())
                loaded = saved_file_path(name)
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.read_bytes(), b"%PDF-1.6")

    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_save_pdf_and_xlsx_with_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                key = "20260618122107"
                pdf_name = saved_filename_for_key(key, ".pdf")
                xlsx_name = saved_filename_for_key(key, ".xlsx")
                save_file(b"%PDF-1.6", pdf_name)
                save_file(b"PK-xlsx", xlsx_name)
                self.assertTrue(saved_file_path(pdf_name).is_file())
                self.assertTrue(saved_file_path(xlsx_name).is_file())

    @patch.dict(os.environ, {"CONVERT_SAVE": "off"}, clear=False)
    def test_save_disabled(self) -> None:
        self.assertIsNone(save_file(b"%PDF", "20260618122107.pdf"))


class SavedOutputEndpointTests(unittest.TestCase):
    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_get_saved_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                pdf_name = "20260618150405.pdf"
                xlsx_name = "20260618150405.xlsx"
                save_file(b"%PDF-test", pdf_name)
                save_file(b"PK-test", xlsx_name)
                client = TestClient(app)
                ok = client.get(f"/output/{pdf_name}")
                self.assertEqual(ok.status_code, 200)
                self.assertEqual(ok.content, b"%PDF-test")
                ok_xlsx = client.get(f"/output/{xlsx_name}")
                self.assertEqual(ok_xlsx.status_code, 200)
                self.assertEqual(ok_xlsx.content, b"PK-test")
                missing = client.get("/output/20260618150406.pdf")
                self.assertEqual(missing.status_code, 404)
                bad = client.get("/output/evil.pdf")
                self.assertEqual(bad.status_code, 400)

    @patch("app.main._convert_bytes_to_pdf_bytes", return_value=b"%PDF-test")
    @patch("app.main.timestamp_save_key", return_value="20260618150405")
    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_convert_saves_matching_pdf_and_xlsx(self, _mock_key, _mock_convert) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                sample = (
                    __import__("pathlib").Path(__file__).resolve().parents[1]
                    / "samples/in/完了報告書_2544094.xlsx"
                )
                if not sample.is_file():
                    self.skipTest("sample xlsx missing")
                client = TestClient(app)
                with sample.open("rb") as fh:
                    res = client.post(
                        "/convert",
                        files={
                            "file": (
                                "完了報告書_2544094.xlsx",
                                fh,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
                self.assertEqual(res.status_code, 200)
                self.assertTrue(saved_file_path("20260618150405.pdf").is_file())
                self.assertTrue(saved_file_path("20260618150405.xlsx").is_file())
                self.assertEqual(res.headers.get("X-Saved-Upload-Filename"), "20260618150405.xlsx")


if __name__ == "__main__":
    unittest.main()
