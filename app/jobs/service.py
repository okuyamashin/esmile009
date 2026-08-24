"""ジョブ API とワーカーが使うサービス層。"""

from __future__ import annotations

import os
import uuid

from app.jobs.backends.base import JobBackend
from app.jobs.backends.local import LocalJobBackend
from app.jobs.models import JobRecord, JobStatus


def get_job_backend() -> JobBackend:
    backend = os.environ.get("JOB_BACKEND", "local").strip().lower()
    if backend == "aws":
        from app.jobs.backends.aws import AwsJobBackend

        return AwsJobBackend()
    if backend == "local":
        return LocalJobBackend()
    raise RuntimeError(f"未知の JOB_BACKEND: {backend}")


class JobService:
    def __init__(self, backend: JobBackend | None = None) -> None:
        self._backend = backend or get_job_backend()

    def create(
        self,
        original_filename: str,
        input_bytes: bytes,
        suffix: str,
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        return self._backend.create_job(job_id, original_filename, input_bytes, suffix)

    def get(self, job_id: str) -> JobRecord | None:
        return self._backend.get_job(job_id)

    def pdf_bytes(self, job_id: str) -> bytes | None:
        return self._backend.read_pdf(job_id)

    def pdf_download_name(self, job_id: str) -> str | None:
        return self._backend.pdf_download_name(job_id)

    def job_pdf_path(self, job_id: str, base_path: str) -> str | None:
        record = self.get(job_id)
        if record is None or record.status != JobStatus.DONE:
            return None
        prefix = base_path.rstrip("/")
        path = f"/jobs/{job_id}/pdf"
        return f"{prefix}{path}" if prefix else path


_job_service: JobService | None = None


def get_job_service() -> JobService:
    global _job_service
    if _job_service is None:
        _job_service = JobService()
    return _job_service
