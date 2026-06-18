"""アクセスログ middleware のテスト。"""

from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.access_log import ACCESS_LOGGER_NAME, client_ip, format_access_line
from app.main import app


class AccessLogTests(unittest.TestCase):
    def setUp(self) -> None:
        logging.getLogger(ACCESS_LOGGER_NAME).handlers.clear()

    def test_format_access_line(self) -> None:
        line = format_access_line(
            client="203.0.113.1",
            method="GET",
            path="/health",
            status=200,
            duration_ms=1.2,
            bytes_out=52,
            user_agent="curl/8.0",
        )
        self.assertIn('client=203.0.113.1', line)
        self.assertIn('method=GET', line)
        self.assertIn('path="/health"', line)
        self.assertIn("status=200", line)

    def test_client_ip_uses_x_forwarded_for(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-forwarded-for", b"203.0.113.1, 10.0.0.1")],
            "client": ("127.0.0.1", 12345),
        }
        from starlette.requests import Request

        request = Request(scope)
        self.assertEqual(client_ip(request), "203.0.113.1")

    @patch.dict(os.environ, {"ACCESS_LOG": "1"}, clear=False)
    def test_health_emits_access_log(self) -> None:
        logger = logging.getLogger(ACCESS_LOGGER_NAME)
        with self.assertLogs(logger, level="INFO") as captured:
            response = TestClient(app).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("access " in line and "/health" in line for line in captured.output))

    @patch.dict(os.environ, {"ACCESS_LOG": "off"}, clear=False)
    def test_access_log_can_be_disabled(self) -> None:
        logger = logging.getLogger(ACCESS_LOGGER_NAME)
        with patch.object(logger, "info") as mock_info:
            TestClient(app).get("/health")
        mock_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
