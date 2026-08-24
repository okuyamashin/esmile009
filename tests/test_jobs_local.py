"""非同期ジョブ（ローカルバックエンド）のテスト。"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.jobs.backends.local import LocalJobBackend
from app.jobs.models import JobStatus


class LocalJobBackendTests(unittest.TestCase):
    def test_create_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JOB_LOCAL_DIR": tmp}, clear=False):
                backend = LocalJobBackend()
                record = backend.create_job(
                    "abc123def4567890abc123def4567890",
                    "sample.xlsx",
                    b"xlsx-bytes",
                    ".xlsx",
                )
                self.assertEqual(record.status, JobStatus.QUEUED)
                loaded = backend.get_job(record.job_id)
                assert loaded is not None
                self.assertEqual(loaded.status, JobStatus.QUEUED)

    def test_dequeue_and_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"JOB_LOCAL_DIR": tmp}, clear=False):
                backend = LocalJobBackend()
                job_id = "abc123def4567890abc123def4567890"
                backend.create_job(job_id, "report.xlsx", b"data", ".xlsx")
                dequeued = backend.dequeue_job_id(wait_seconds=0)
                self.assertEqual(dequeued, job_id)
                backend.mark_processing(job_id)
                backend.mark_done(job_id, b"%PDF-1.6")
                pdf = backend.read_pdf(job_id)
                self.assertEqual(pdf, b"%PDF-1.6")
                record = backend.get_job(job_id)
                assert record is not None
                self.assertEqual(record.status, JobStatus.DONE)


if __name__ == "__main__":
    unittest.main()
