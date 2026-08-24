"""非同期変換ジョブ（パターン A: キュー + ワーカー）。"""

from app.jobs.service import JobService, get_job_service

__all__ = ["JobService", "get_job_service"]
