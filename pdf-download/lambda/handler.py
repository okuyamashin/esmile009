import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote
from zoneinfo import ZoneInfo

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BUCKET = os.environ.get("DATA_BUCKET", "engawa-esmile009")
ORIGIN_SECRET = os.environ.get("ORIGIN_SECRET", "")
ORDER_COL = "受付地域別受注番号"
DATE_RE = re.compile(r"^(\d{8})/$")
DATE_VALUE_RE = re.compile(r"^\d{8}$")
PDF_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.pdf$")
UNSAFE_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
DATE_IN_TEXT_RE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
TSV_RANGE_RE = re.compile(r"(\d{8})-(\d{8})\.tsv$", re.I)
JST = ZoneInfo("Asia/Tokyo")

s3 = boto3.client(
    "s3",
    region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
    config=Config(signature_version="s3v4"),
)


def lambda_handler(event, context):
    if ORIGIN_SECRET:
        headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
        if headers.get("x-origin-secret") != ORIGIN_SECRET:
            return _json(403, {"error": "forbidden"})

    ctx = event.get("requestContext") or {}
    http = ctx.get("http") or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = event.get("rawPath") or event.get("path") or "/"
    qs = event.get("queryStringParameters") or {}
    if qs is None:
        qs = {}
    if not qs.get("date") and event.get("rawQueryString"):
        parsed = parse_qs(event.get("rawQueryString"), keep_blank_values=True)
        qs = {key: (values[0] if values else "") for key, values in parsed.items()}

    try:
        if method == "GET" and path.endswith("/dates"):
            return list_dates()
        if method == "GET" and path.endswith("/items"):
            return list_items(qs.get("date", ""))
        if method == "POST" and path.endswith("/download"):
            return start_download(_read_json_body(event))
        if method == "POST" and path.endswith("/file"):
            return start_file(_read_json_body(event))
        return _json(404, {"error": "not found"})
    except ValueError as exc:
        return _json(400, {"error": str(exc)})
    except Exception:
        logger.exception("pdf-download api failed")
        return _json(500, {"error": "internal error"})


def list_dates():
    dates = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Delimiter="/"):
        for prefix in page.get("CommonPrefixes") or []:
            match = DATE_RE.match(prefix.get("Prefix") or "")
            if match:
                dates.append(match.group(1))
    dates.sort(reverse=True)
    return _json(200, {"dates": dates, "latest": dates[0] if dates else None})


def list_items(date):
    return _json(200, _items_payload(_require_date(date)))


def _items_payload(date):
    prefix = f"{date}/"
    objects = _list_objects(prefix)
    keys = [obj["Key"] for obj in objects]
    latest_upload = _latest_upload_iso(objects)
    pdfs = sorted(
        key[len(prefix) :]
        for key in keys
        if key.lower().endswith(".pdf") and key.count("/") == prefix.count("/")
    )
    tsv_keys = _tsv_keys_for_date(
        sorted(key for key in keys if key.lower().endswith(".tsv")),
        date,
    )
    if not tsv_keys:
        return {
            "date": date,
            "headers": [],
            "rows": [],
            "pdfs": pdfs,
            "extra_pdfs": pdfs,
            "tsv": None,
            "tsv_count": 0,
            "latest_upload": latest_upload,
        }

    headers = []
    rows = []
    seen = set()
    for tsv_key in tsv_keys:
        file_headers, file_rows = _read_tsv(tsv_key)
        if file_headers:
            headers = file_headers
        for row in file_rows:
            order_no = (row.get(ORDER_COL) or "").strip()
            if not order_no or order_no in seen:
                continue
            seen.add(order_no)
            rows.append(row)

    pdf_set = set(pdfs)
    claimed = set()
    for row in rows:
        order_no = (row.get(ORDER_COL) or "").strip()
        matched = _pdfs_for_order(order_no, pdf_set) if order_no else []
        row["_pdfs"] = matched
        row["_has_pdf"] = bool(matched)
        claimed.update(matched)

    extra_pdfs = [name for name in pdfs if name not in claimed]
    return {
        "date": date,
        "headers": headers,
        "rows": rows,
        "pdfs": pdfs,
        "extra_pdfs": extra_pdfs,
        "tsv": tsv_keys[-1].rsplit("/", 1)[-1],
        "tsv_count": len(tsv_keys),
        "latest_upload": latest_upload,
    }


def start_download(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid json")
    date = _require_date(str(payload.get("date") or ""))
    names = payload.get("pdfs") or []
    if not isinstance(names, list) or not names:
        raise ValueError("pdfs is required")
    if len(names) > 200:
        raise ValueError("too many pdfs")

    unique = []
    seen = set()
    for raw in names:
        name = str(raw).strip()
        if name in seen:
            continue
        if not PDF_NAME_RE.fullmatch(name):
            raise ValueError("invalid pdf name")
        unique.append(name)
        seen.add(name)

    writer = PdfWriter()
    for name in unique:
        key = f"{date}/{name}"
        try:
            body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ValueError(f"pdf not found: {name}") from exc
            raise
        writer.append(PdfReader(io.BytesIO(body)))

    merged = io.BytesIO()
    writer.write(merged)
    pdf_bytes = merged.getvalue()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = f"merged/{date}/{stamp}_{len(unique)}files.pdf"
    filename = f"esmile009-{date}.pdf"
    s3.put_object(
        Bucket=BUCKET,
        Key=dest,
        Body=pdf_bytes,
        ContentType="application/pdf",
        ContentDisposition=f'attachment; filename="{filename}"',
    )
    return _json(
        200,
        {
            "url": f"/{dest}",
            "filename": filename,
            "count": len(unique),
            "bytes": len(pdf_bytes),
        },
    )


def start_file(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid json")
    date = _require_date(str(payload.get("date") or ""))
    name = str(payload.get("pdf") or "").strip()
    if not PDF_NAME_RE.fullmatch(name):
        raise ValueError("invalid pdf name")

    data = _items_payload(date)
    if name not in set(data.get("pdfs") or []):
        raise ValueError(f"pdf not found: {name}")
    row = next(
        (candidate for candidate in (data.get("rows") or []) if name in (candidate.get("_pdfs") or [])),
        None,
    )
    if row is None:
        raise ValueError("pdf is not linked to a tsv row")

    filename = build_download_filename(row)
    src = f"{date}/{name}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = f"merged/{date}/{stamp}_{name}"
    try:
        s3.copy_object(
            Bucket=BUCKET,
            CopySource={"Bucket": BUCKET, "Key": src},
            Key=dest,
            ContentType="application/pdf",
            ContentDisposition=_content_disposition(filename),
            MetadataDirective="REPLACE",
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise ValueError(f"pdf not found: {name}") from exc
        raise
    return _json(200, {"url": f"/{dest}", "filename": filename})


def build_download_filename(row):
    order = _safe_part(row.get(ORDER_COL))
    work_date = _work_date(row.get("終了日時"))
    place = _place(row)
    name = _safe_part(row.get("氏名"))
    return f"{order}_{work_date}_報告書　{place}_{name}様.pdf"


def _safe_part(value):
    return UNSAFE_NAME_RE.sub("", (value or "").strip())


def _work_date(value):
    text = (value or "").strip()
    match = DATE_IN_TEXT_RE.search(text)
    if match:
        return f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}"
    digits = re.sub(r"\D", "", text)
    return digits[:8] if len(digits) >= 8 else digits


def _place(row):
    building = _safe_part(row.get("建物名"))
    if building:
        return building
    city = _safe_part(row.get("住所（市区町村）"))
    rest = _safe_part(row.get("住所（その他）"))
    return f"{city}{rest}"


def _content_disposition(filename):
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"report.pdf\"; filename*=UTF-8''{encoded}"


def _pdfs_for_order(order_no, pdf_set):
    exact = f"{order_no}.pdf"
    extras = sorted(
        name
        for name in pdf_set
        if name != exact and (name.startswith(f"{order_no}.") or name.startswith(f"{order_no}_"))
    )
    matched = []
    if exact in pdf_set:
        matched.append(exact)
    matched.extend(extras)
    return matched


def _tsv_end_date(key):
    match = TSV_RANGE_RE.search(key.rsplit("/", 1)[-1])
    return match.group(2) if match else None


def _tsv_keys_for_date(tsv_keys, date):
    matched = [key for key in tsv_keys if _tsv_end_date(key) == date]
    if matched:
        return matched
    return tsv_keys[-1:] if tsv_keys else []


def _list_objects(prefix):
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents") or []:
            objects.append(obj)
    return objects


def _latest_upload_iso(objects):
    latest = None
    for obj in objects:
        modified = obj.get("LastModified")
        if modified is None:
            continue
        if latest is None or modified > latest:
            latest = modified
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest.astimezone(JST).isoformat()


def _read_tsv(key):
    raw = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    text = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    lines = text.splitlines()
    if not lines:
        return [], []
    headers = lines[0].split("\t")
    expected = len(headers)
    rows = []
    buf = []
    for line in lines[1:]:
        buf.append(line)
        fields = "\n".join(buf).split("\t")
        if len(fields) < expected:
            continue
        if len(fields) > expected:
            fields = fields[: expected - 1] + ["\t".join(fields[expected - 1 :])]
        row = {}
        for header, value in zip(headers, fields):
            if value == "NULL":
                value = ""
            row[header] = value.replace("\r", " ").replace("\n", " ").strip()
        rows.append(row)
        buf = []
    return headers, rows


def _require_date(date):
    date = (date or "").strip()
    if not DATE_VALUE_RE.fullmatch(date):
        raise ValueError("invalid date")
    return date


def _read_json_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json") from exc


def _json(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        },
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }
