"""SQS / ローカルキューを監視し LibreOffice で変換するワーカー。"""

from __future__ import annotations

import logging
import os
import time

from app.converter import _convert_bytes_to_pdf_bytes
from app.jobs.backends.base import JobBackend
from app.jobs.service import get_job_backend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("esmile009.worker")


def process_job(backend: JobBackend, job_id: str) -> None:
    logger.info("processing job_id=%s", job_id)
    backend.mark_processing(job_id)
    try:
        data, suffix = backend.read_input(job_id)
        pdf_bytes = _convert_bytes_to_pdf_bytes(data, suffix)
        backend.mark_done(job_id, pdf_bytes)
        logger.info("done job_id=%s", job_id)
    except Exception as exc:  # noqa: BLE001 — ジョブ失敗として記録
        logger.exception("failed job_id=%s", job_id)
        backend.mark_failed(job_id, str(exc))


def run_worker() -> None:
    backend = get_job_backend()
    poll_wait = int(os.environ.get("JOB_POLL_WAIT_SEC", "20"))
    idle_sleep = float(os.environ.get("JOB_IDLE_SLEEP_SEC", "1"))

    logger.info(
        "worker started backend=%s poll_wait=%s",
        os.environ.get("JOB_BACKEND", "local"),
        poll_wait,
    )

    while True:
        job_id = backend.dequeue_job_id(wait_seconds=poll_wait)
        if job_id is None:
            time.sleep(idle_sleep)
            continue
        process_job(backend, job_id)


if __name__ == "__main__":
    run_worker()
