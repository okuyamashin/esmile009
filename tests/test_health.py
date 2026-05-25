"""health エンドポイントのテスト。"""

from __future__ import annotations

import unittest

from app.main import health
from app.version import APP_VERSION, health_payload


class HealthTests(unittest.TestCase):
    def test_health_payload_has_version(self) -> None:
        payload = health_payload()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], APP_VERSION)
        self.assertIn("git_commit", payload)

    def test_health_endpoint(self) -> None:
        body = health()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], APP_VERSION)
        self.assertIn("git_commit", body)


if __name__ == "__main__":
    unittest.main()
