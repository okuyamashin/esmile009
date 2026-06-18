import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.access_log import AccessLogMiddleware, append_access_extra, set_upload_extra
from app.converter import _convert_bytes_to_pdf_bytes
from app.convert_store import save_pdf, saved_pdf_path, validate_saved_filename
from app.pdf_filename import timestamp_pdf_filename
from app.version import APP_VERSION, health_payload

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_DOWNLOAD_DIR = ROOT_DIR / "test-download"
TEST_DOWNLOAD_XLSX = Path(
    os.environ.get(
        "TEST_DOWNLOAD_XLSX",
        str(ROOT_DIR / "samples/in/完了報告書_2544094.xlsx"),
    )
)
TEST_DOWNLOAD_FILENAME = TEST_DOWNLOAD_XLSX.name

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
    version=APP_VERSION,
    docs_url=_docs,
    openapi_url=_openapi,
    redoc_url=_redoc,
)
app.add_middleware(AccessLogMiddleware)

router = APIRouter()


def _content_disposition(filename: str) -> str:
    """RFC 5987: 日本語ファイル名を latin-1 ヘッダーで壊さない。"""
    ascii_safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._-") or "export.pdf"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"


@router.get("/health")
def health() -> dict[str, str]:
    return health_payload()


@router.get("/test-download")
def test_download_page() -> HTMLResponse:
    index_html = TEST_DOWNLOAD_DIR / "index.html"
    if not index_html.is_file():
        raise HTTPException(status_code=404, detail="テスト用ページが見つかりません")
    download_url = f"{BASE_PATH}/test-download/file" if BASE_PATH else "/test-download/file"
    html = index_html.read_text(encoding="utf-8").replace("__DOWNLOAD_URL__", download_url)
    return HTMLResponse(html)


@router.get("/test-download/file")
def test_download_file() -> FileResponse:
    if not TEST_DOWNLOAD_XLSX.is_file():
        raise HTTPException(
            status_code=404,
            detail="テスト用 Excel が見つかりません。samples/in/ に配置してください。",
        )
    return FileResponse(
        TEST_DOWNLOAD_XLSX,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=TEST_DOWNLOAD_FILENAME,
        headers={"Content-Disposition": _content_disposition(TEST_DOWNLOAD_FILENAME)},
    )


@router.post("/convert")
async def convert(request: Request, file: UploadFile = File(...)) -> Response:
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

    set_upload_extra(request, name, len(data))

    try:
        body = _convert_bytes_to_pdf_bytes(data, suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    out_name = timestamp_pdf_filename()
    download_name = f"{Path(name).stem or 'document'}.pdf"
    saved = save_pdf(body, out_name)
    saved_path = f"{BASE_PATH}/output/{out_name}" if BASE_PATH else f"/output/{out_name}"
    if saved is not None:
        append_access_extra(request, f'saved="{out_name}" saved_path="{saved_path}"')

    headers = {"Content-Disposition": _content_disposition(download_name)}
    if saved is not None:
        headers["X-Saved-Filename"] = out_name
        headers["X-Saved-Path"] = saved_path

    return Response(
        content=body,
        media_type="application/pdf",
        headers=headers,
    )


@router.get("/output/{filename}")
def get_saved_output(filename: str) -> FileResponse:
    try:
        validate_saved_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = saved_pdf_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="PDF が見つかりません")

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


if BASE_PATH:
    app.include_router(router, prefix=BASE_PATH)
else:
    app.include_router(router)
