"""ジョブの状態モデル。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    original_filename: str
    created_at: str
    updated_at: str
    error: str | None = None

    def to_dict(self, pdf_path: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "jobId": self.job_id,
            "status": self.status.value,
            "originalFilename": self.original_filename,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "error": self.error,
        }
        if pdf_path and self.status == JobStatus.DONE:
            body["pdfUrl"] = pdf_path
        return body
