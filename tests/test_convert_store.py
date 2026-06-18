"""変換 PDF 保存のテスト。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.convert_store import save_pdf, saved_pdf_path, validate_saved_filename
from app.main import app


class ConvertStoreTests(unittest.TestCase):
    def test_validate_saved_filename(self) -> None:
        self.assertEqual(validate_saved_filename("20260618122107.pdf"), "20260618122107.pdf")
        with self.assertRaises(ValueError):
            validate_saved_filename("../secret.pdf")
        with self.assertRaises(ValueError):
            validate_saved_filename("report.pdf")

    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_save_and_load_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                name = "20260618122107.pdf"
                saved = save_pdf(b"%PDF-1.6", name)
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertTrue(saved.is_file())
                loaded = saved_pdf_path(name)
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.read_bytes(), b"%PDF-1.6")

    @patch.dict(os.environ, {"CONVERT_SAVE": "off"}, clear=False)
    def test_save_disabled(self) -> None:
        self.assertIsNone(save_pdf(b"%PDF", "20260618122107.pdf"))


class SavedOutputEndpointTests(unittest.TestCase):
    @patch.dict(os.environ, {"CONVERT_SAVE": "1"}, clear=False)
    def test_get_saved_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CONVERT_SAVE_DIR": tmp}, clear=False):
                name = "20260618150405.pdf"
                save_pdf(b"%PDF-test", name)
                client = TestClient(app)
                ok = client.get(f"/output/{name}")
                self.assertEqual(ok.status_code, 200)
                self.assertEqual(ok.content, b"%PDF-test")
                missing = client.get("/output/20260618150406.pdf")
                self.assertEqual(missing.status_code, 404)
                bad = client.get("/output/evil.pdf")
                self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
