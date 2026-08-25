import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs

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
    date = _require_date(date)
    prefix = f"{date}/"
    keys = _list_keys(prefix)
    pdfs = sorted(
        key[len(prefix) :]
        for key in keys
        if key.lower().endswith(".pdf") and key.count("/") == prefix.count("/")
    )
    tsv_keys = [key for key in keys if key.lower().endswith(".tsv")]
    if not tsv_keys:
        return _json(
            200,
            {
                "date": date,
                "headers": [],
                "rows": [],
                "pdfs": pdfs,
                "extra_pdfs": pdfs,
                "tsv": None,
            },
        )

    tsv_key = sorted(tsv_keys)[-1]
    headers, rows = _read_tsv(tsv_key)
    pdf_set = set(pdfs)
    claimed = set()
    for row in rows:
        order_no = (row.get(ORDER_COL) or "").strip()
        matched = _pdfs_for_order(order_no, pdf_set) if order_no else []
        row["_pdfs"] = matched
        row["_has_pdf"] = bool(matched)
        claimed.update(matched)

    extra_pdfs = [name for name in pdfs if name not in claimed]
    return _json(
        200,
        {
            "date": date,
            "headers": headers,
            "rows": rows,
            "pdfs": pdfs,
            "extra_pdfs": extra_pdfs,
            "tsv": tsv_key.rsplit("/", 1)[-1],
        },
    )


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


def _list_keys(prefix):
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents") or []:
            keys.append(obj["Key"])
    return keys


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
