import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
CONVERT_TIMEOUT_SEC = int(os.environ.get("CONVERT_TIMEOUT_SEC", "120"))

# リバースプロキシでサブパス公開する場合（例: https://example.com/esmile009/health）
BASE_PATH_raw = os.environ.get("BASE_PATH", "").strip()
BASE_PATH = BASE_PATH_raw.rstrip("/") if BASE_PATH_raw else ""
if BASE_PATH and not BASE_PATH.startswith("/"):
    BASE_PATH = "/" + BASE_PATH

_docs = f"{BASE_PATH}/docs" if BASE_PATH else "/docs"
_openapi = f"{BASE_PATH}/openapi.json" if BASE_PATH else "/openapi.json"
_redoc = f"{BASE_PATH}/redoc" if BASE_PATH else "/redoc"

app = FastAPI(
    title="xlsx2pdf",
    version="1.0.0",
    docs_url=_docs,
    openapi_url=_openapi,
    redoc_url=_redoc,
)

router = APIRouter()


def _content_disposition(filename: str) -> str:
    """RFC 5987: 日本語ファイル名を latin-1 ヘッダーで壊さない。"""
    ascii_safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._-") or "export.pdf"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/convert")
async def convert(file: UploadFile = File(...)) -> Response:
    name = (file.filename or "upload").strip()
    suffix = Path(name).suffix.lower()
    if suffix not in (".xlsx", ".xls"):
        raise HTTPException(
            status_code=400,
            detail="拡張子は .xlsx または .xls である必要があります",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空のファイルです")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="ファイルが大きすぎます")

    stem = Path(name).stem or "document"

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"input{suffix}"
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        src.write_bytes(data)

        cmd = [
            "libreoffice",
            "--headless",
            "--norestore",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CONVERT_TIMEOUT_SEC,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip() or "変換に失敗しました"
            raise HTTPException(status_code=500, detail=msg[:2000])

        pdf_path = out_dir / f"{src.stem}.pdf"
        if not pdf_path.is_file():
            raise HTTPException(status_code=500, detail="PDF が生成されませんでした")

        body = pdf_path.read_bytes()

    out_name = f"{stem}.pdf"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(out_name)},
    )


if BASE_PATH:
    app.include_router(router, prefix=BASE_PATH)
else:
    app.include_router(router)
