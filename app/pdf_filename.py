"""PDF ダウンロード用ファイル名。"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Tokyo"


def timestamp_pdf_filename() -> str:
    tz_name = os.environ.get("PDF_FILENAME_TZ", DEFAULT_TZ).strip() or DEFAULT_TZ
    now = datetime.now(ZoneInfo(tz_name))
    return now.strftime("%Y%m%d%H%M%S") + ".pdf"
