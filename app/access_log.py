"""HTTP アクセスログ（stdout / 任意でファイル）。"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

ACCESS_LOGGER_NAME = "esmile009.access"


def access_logging_enabled() -> bool:
    raw = os.environ.get("ACCESS_LOG", "1").strip().lower()
    return raw not in ("0", "off", "false", "no")


def _configure_logger() -> logging.Logger:
    logger = logging.getLogger(ACCESS_LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stream)

    log_file = os.environ.get("ACCESS_LOG_FILE", "").strip()
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(file_handler)

    return logger


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "-"


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def set_upload_extra(request: Request, filename: str, size: int) -> None:
    request.state.access_log_extra = f'upload="{_quote(filename)}" upload_bytes={size}'



def format_access_line(
    *,
    client: str,
    method: str,
    path: str,
    status: int,
    duration_ms: float,
    bytes_out: int | None = None,
    user_agent: str = "",
    extra: str = "",
) -> str:
    parts = [
        f'client={client}',
        f'method={method}',
        f'path="{_quote(path)}"',
        f'status={status}',
        f'duration_ms={duration_ms:.1f}',
    ]
    if bytes_out is not None and bytes_out > 0:
        parts.append(f'bytes={bytes_out}')
    if user_agent:
        parts.append(f'user_agent="{_quote(user_agent)}"')
    if extra:
        parts.append(extra)
    return "access " + " ".join(parts)


def log_access(request: Request, response: Response, *, duration_ms: float) -> None:
    if not access_logging_enabled():
        return

    bytes_out: int | None = None
    raw_len = response.headers.get("content-length")
    if raw_len and raw_len.isdigit():
        bytes_out = int(raw_len)

    extra = getattr(request.state, "access_log_extra", "")
    line = format_access_line(
        client=client_ip(request),
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        bytes_out=bytes_out,
        user_agent=request.headers.get("user-agent", ""),
        extra=extra,
    )
    _configure_logger().info(line)


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not access_logging_enabled():
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            line = format_access_line(
                client=client_ip(request),
                method=request.method,
                path=request.url.path,
                status=500,
                duration_ms=duration_ms,
                user_agent=request.headers.get("user-agent", ""),
                extra=getattr(request.state, "access_log_extra", ""),
            )
            _configure_logger().info(line)
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        log_access(request, response, duration_ms=duration_ms)
        return response
