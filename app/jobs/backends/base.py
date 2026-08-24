"""ジョブバックエンドの抽象インターフェース。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO

from app.jobs.models import JobRecord


class JobBackend(ABC):
    @abstractmethod
    def create_job(
        self,
        job_id: str,
        original_filename: str,
        input_bytes: bytes,
        suffix: str,
    ) -> JobRecord:
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord | None:
        ...

    @abstractmethod
    def dequeue_job_id(self, wait_seconds: int = 0) -> str | None:
        ...

    @abstractmethod
    def mark_processing(self, job_id: str) -> JobRecord:
        ...

    @abstractmethod
    def mark_done(self, job_id: str, pdf_bytes: bytes) -> JobRecord:
        ...

    @abstractmethod
    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        ...

    @abstractmethod
    def read_input(self, job_id: str) -> tuple[bytes, str]:
        """(bytes, suffix) を返す。"""

    @abstractmethod
    def read_pdf(self, job_id: str) -> bytes | None:
        ...

    @abstractmethod
    def pdf_download_name(self, job_id: str) -> str | None:
        ...
