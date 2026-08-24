"""AWS S3（ファイル）+ SQS（キュー）バックエンド。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.jobs.backends.base import JobBackend
from app.jobs.models import JobRecord, JobStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bucket() -> str:
    name = os.environ.get("JOB_S3_BUCKET", "").strip()
    if not name:
        raise RuntimeError("JOB_S3_BUCKET が未設定です")
    return name


def _queue_url() -> str:
    url = os.environ.get("JOB_SQS_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("JOB_SQS_QUEUE_URL が未設定です")
    return url


def _prefix() -> str:
    raw = os.environ.get("JOB_S3_PREFIX", "jobs").strip().strip("/")
    return raw or "jobs"


def _meta_key(job_id: str) -> str:
    return f"{_prefix()}/{job_id}/meta.json"


def _input_key(job_id: str, suffix: str) -> str:
    return f"{_prefix()}/{job_id}/input{suffix}"


def _pdf_key(job_id: str) -> str:
    return f"{_prefix()}/{job_id}/output.pdf"


class AwsJobBackend(JobBackend):
    def __init__(self) -> None:
        region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1"))
        self._s3 = boto3.client("s3", region_name=region)
        self._sqs = boto3.client("sqs", region_name=region)
        self._bucket = _bucket()
        self._queue_url = _queue_url()

    def _put_meta(self, record: JobRecord) -> None:
        body = json.dumps(
            {
                "job_id": record.job_id,
                "status": record.status.value,
                "original_filename": record.original_filename,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "error": record.error,
            },
            ensure_ascii=False,
        )
        self._s3.put_object(
            Bucket=self._bucket,
            Key=_meta_key(record.job_id),
            Body=body.encode("utf-8"),
            ContentType="application/json",
        )

    def _load_meta(self, job_id: str) -> JobRecord | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=_meta_key(job_id))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return None
            raise
        data = json.loads(obj["Body"].read().decode("utf-8"))
        return JobRecord(
            job_id=data["job_id"],
            status=JobStatus(data["status"]),
            original_filename=data["original_filename"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            error=data.get("error"),
        )

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
        self._s3.put_object(
            Bucket=self._bucket,
            Key=_input_key(job_id, suffix),
            Body=input_bytes,
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self._put_meta(record)
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"job_id": job_id}),
        )
        return record

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._load_meta(job_id)

    def dequeue_job_id(self, wait_seconds: int = 0) -> str | None:
        wait = min(max(wait_seconds, 0), 20)
        resp = self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait,
            VisibilityTimeout=int(os.environ.get("JOB_SQS_VISIBILITY_TIMEOUT", "300")),
        )
        messages = resp.get("Messages", [])
        if not messages:
            return None
        message = messages[0]
        body = json.loads(message["Body"])
        job_id = body["job_id"]
        # receipt handle をワーカーが完了後に削除するため、processing マーカーに保存
        marker = Path(os.environ.get("JOB_LOCAL_DIR", "/var/lib/esmile009/jobs")) / "sqs_receipts"
        marker.mkdir(parents=True, exist_ok=True)
        (marker / f"{job_id}.json").write_text(
            json.dumps(
                {
                    "receipt_handle": message["ReceiptHandle"],
                    "message_id": message.get("MessageId"),
                }
            ),
            encoding="utf-8",
        )
        return job_id

    def _delete_sqs_message(self, job_id: str) -> None:
        marker = Path(os.environ.get("JOB_LOCAL_DIR", "/var/lib/esmile009/jobs")) / "sqs_receipts"
        path = marker / f"{job_id}.json"
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._sqs.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=data["receipt_handle"],
        )
        path.unlink(missing_ok=True)

    def mark_processing(self, job_id: str) -> JobRecord:
        record = self._load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.PROCESSING
        record.updated_at = _now_iso()
        self._put_meta(record)
        return record

    def mark_done(self, job_id: str, pdf_bytes: bytes) -> JobRecord:
        record = self._load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=_pdf_key(job_id),
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        record.status = JobStatus.DONE
        record.updated_at = _now_iso()
        record.error = None
        self._put_meta(record)
        self._delete_sqs_message(job_id)
        return record

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        record = self._load_meta(job_id)
        if record is None:
            raise KeyError(job_id)
        record.status = JobStatus.FAILED
        record.updated_at = _now_iso()
        record.error = error[:2000]
        self._put_meta(record)
        self._delete_sqs_message(job_id)
        return record

    def read_input(self, job_id: str) -> tuple[bytes, str]:
        for suffix in (".xlsx", ".xls"):
            key = _input_key(job_id, suffix)
            try:
                obj = self._s3.get_object(Bucket=self._bucket, Key=key)
                return obj["Body"].read(), suffix
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    continue
                raise
        raise FileNotFoundError(job_id)

    def read_pdf(self, job_id: str) -> bytes | None:
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=_pdf_key(job_id))
            return obj["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return None
            raise

    def pdf_download_name(self, job_id: str) -> str | None:
        record = self._load_meta(job_id)
        if record is None:
            return None
        stem = Path(record.original_filename).stem or "document"
        return f"{stem}.pdf"
