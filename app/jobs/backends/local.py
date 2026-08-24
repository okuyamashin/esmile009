"""ローカルディスク上のキュー（Docker / 単一 EC2 検証用）。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.jobs.backends.base import JobBackend
from app.jobs.models import JobRecord, JobStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _jobs_root() -> Path:
    root = Path(os.environ.get("JOB_LOCAL_DIR", "/var/lib/esmile009/jobs"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job_dir(job_id: str) -> Path:
    return _jobs_root() / job_id


def _queue_dir() -> Path:
    path = _jobs_root() / "queue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _processing_dir() -> Path:
    path = _jobs_root() / "processing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(job_id: str) -> Path:
    return _job_dir(job_id) / "meta.json"


def _input_path(job_id: str, suffix: str) -> Path:
    return _job_dir(job_id) / f"input{suffix}"


def _pdf_path(job_id: str) -> Path:
    return _job_dir(job_id) / "output.pdf"


def _load_meta(job_id: str) -> JobRecord | None:
    path = _meta_path(job_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return JobRecord(
        job_id=data["job_id"],
        status=JobStatus(data["status"]),
        original_filename=data["original_filename"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        error=data.get("error"),
    )


def _write_meta(record: JobRecord) -> None:
    _job_dir(record.job_id).mkdir(parents=True, exist_ok=True)
    _meta_path(record.job_id).write_text(
        json.dumps(
            {
                "job_id": record.job_id,
                "status": record.status.value,
                "original_filename": record.original_filename,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "error": record.error,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class LocalJobBackend(JobBackend):
    def create_job(
        self,
        job_id: str,
        original_filename: str,
        input_bytes: bytes,
        suffix: str,
    ) -> JobRecord:
        now = _now_iso()
        record = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            original_filename=original_filename,
            created_at=now,
            updated_at=now,
        )
        _job_dir(job_id).mkdir(parents=True, exist_ok=True)
        _input_path(job_id, suffix).write_bytes(input_bytes)
        _write_meta(record)
        queue_file = _queue_dir() / f"{job_id}.json"
        queue_file.write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        return _load_meta(job_id)

    def dequeue_job_id(self, wait_seconds: int = 0) -> str | None:
        # wait_seconds はローカルでは簡易スリープのみ（ワーカー側でループ）
        for _ in range(max(1, wait_seconds)):
            for queue_file in sorted(_queue_dir().glob("*.json")):
                processing_file = _processing_dir() / queue_file.name
                try:
                    queue_file.rename(processing_file)
                except OSError:
                    continue
                data = json.loads(processing_file.read_text(encoding="utf-8"))
                job_id = data["job_id"]
                processing_file.unlink(missing_ok=True)
                return job_id
            if wait_seconds > 0:
                import time

                time.sleep(1)
        return None

    def mark_processing(self, job_id: str) -> JobRecord:
        record = _load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.PROCESSING
        record.updated_at = _now_iso()
        _write_meta(record)
        return record

    def mark_done(self, job_id: str, pdf_bytes: bytes) -> JobRecord:
        record = _load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        _pdf_path(job_id).write_bytes(pdf_bytes)
        record.status = JobStatus.DONE
        record.updated_at = _now_iso()
        record.error = None
        _write_meta(record)
        return record

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        record = _load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.FAILED
        record.updated_at = _now_iso()
        record.error = error[:2000]
        _write_meta(record)
        return record

    def read_input(self, job_id: str) -> tuple[bytes, str]:
        for suffix in (".xlsx", ".xls"):
            path = _input_path(job_id, suffix)
            if path.is_file():
                return path.read_bytes(), suffix
        raise FileNotFoundError(job_id)

    def read_pdf(self, job_id: str) -> bytes | None:
        path = _pdf_path(job_id)
        return path.read_bytes() if path.is_file() else None

    def pdf_download_name(self, job_id: str) -> str | None:
        record = _load_meta(job_id)
        if record is None:
            return None
        stem = Path(record.original_filename).stem or "document"
        return f"{stem}.pdf"
