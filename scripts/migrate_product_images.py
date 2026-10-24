"""Audit externally hosted product images and mirror verified bytes to private S3.

The default ``audit`` command performs no AWS or database writes. ``mirror`` requires
an explicit write flag and produces a mapping plus conditional PostgreSQL SQL; it
does not connect to the database.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


SCHEMA_VERSION = 1
DEFAULT_API_BASE_URL = "https://api.fitzza.site/api/v1"
DEFAULT_REFERER = "https://app.fitzza.site/"
DEFAULT_PREFIX = "public/product-images"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
USER_AGENT = "FitzzaProductImageMigration/1.0"
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/gif": ("gif", (b"GIF87a", b"GIF89a")),
    "image/webp": ("webp", (b"RIFF",)),
}


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    content_type: str | None
    body: bytes | None
    error: str | None


def request_json(url: str, timeout: float) -> dict[str, Any]:
    result = request_url(url, timeout=timeout, headers={"Accept": "application/json"})
    if result.status != 200 or result.body is None:
        raise ValueError(f"API request failed: {url} status={result.status} error={result.error}")
    parsed = json.loads(result.body)
    if not isinstance(parsed, dict):
        raise ValueError(f"API response is not an object: {url}")
    return parsed


def request_url(
        url: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None) -> HttpResult:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            if max_bytes is None:
                body = response.read()
            else:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    return HttpResult(response.status, content_type, None, "response_too_large")
            return HttpResult(response.status, content_type, body, None)
    except HTTPError as error:
        return HttpResult(error.code, error.headers.get_content_type(), None, f"http_{error.code}")
    except (TimeoutError, URLError, OSError) as error:
        return HttpResult(None, None, None, type(error).__name__)


def collect_references(detail: dict[str, Any]) -> list[dict[str, Any]]:
    product_id = require_positive_int(detail.get("productId"), "productId")
    references: list[dict[str, Any]] = []

    def add(kind: str, url: Any, selector: dict[str, Any]) -> None:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            references.append({
                "product_id": product_id,
                "kind": kind,
                "selector": selector,
                "source_url": url,
            })

    add("product", detail.get("thumbnailUrl"), {})
    for sequence, url in enumerate(detail.get("images") or []):
        add("product_image", url, {"sequence": sequence})
    for option in detail.get("options") or []:
        add("product_option", option.get("imageUrl"), {
            "option_id": require_positive_int(option.get("optionId"), "optionId")})
    size_guide = detail.get("sizeGuide") or {}
    add("product_size_guide", size_guide.get("guideImageUrl"), {})
    for mapping in detail.get("colorImageMappings") or []:
        color = mapping.get("colorRaw")
        if isinstance(color, str) and color:
            add("color_image_mapping", mapping.get("imageUrl"), {"color_raw": color})
    return references


def require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def audit_source(url: str, referer: str, timeout: float) -> dict[str, Any]:
    browser = request_url(url, timeout=timeout, headers={"Referer": referer}, max_bytes=1)
    direct = browser if browser.status == 200 else request_url(
        url, timeout=timeout, max_bytes=1)
    if browser.status == 200:
        classification = "browser_ok"
    elif direct.status == 200:
        classification = "hotlink_blocked"
    else:
        classification = "origin_failed"
    return {
        "source_url": url,
        "browser_status": browser.status,
        "direct_status": direct.status,
        "content_type": direct.content_type or browser.content_type,
        "classification": classification,
        "error": None if classification != "origin_failed" else direct.error or browser.error,
    }


def build_audit(
        api_base_url: str,
        referer: str,
        page_size: int,
        timeout: float,
        workers: int,
        max_products: int | None = None) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    product_ids: list[int] = []
    page = 0
    while max_products is None or len(product_ids) < max_products:
        listing = request_json(
            f"{api_base_url.rstrip('/')}/products?page={page}&size={page_size}", timeout)
        content = listing.get("content")
        if not isinstance(content, list):
            raise ValueError("Product list response has no content array")
        for product in content:
            product_id = require_positive_int(product.get("productId"), "productId")
            product_ids.append(product_id)
            detail = request_json(
                f"{api_base_url.rstrip('/')}/products/{product_id}", timeout)
            references.extend(collect_references(detail))
            if max_products is not None and len(product_ids) >= max_products:
                break
        if not content or not listing.get("hasNext"):
            break
        page += 1

    source_urls = sorted({reference["source_url"] for reference in references})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        sources = list(pool.map(
            lambda source_url: audit_source(source_url, referer, timeout), source_urls))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_base_url": api_base_url,
        "referer": referer,
        "product_count": len(product_ids),
        "reference_count": len(references),
        "source_count": len(sources),
        "sources": sources,
        "references": references,
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported audit manifest schema")
    sources = manifest.get("sources")
    references = manifest.get("references")
    if not isinstance(sources, list) or not isinstance(references, list):
        raise ValueError("Audit manifest is missing sources or references")
    source_urls = {source.get("source_url") for source in sources}
    if None in source_urls or any(reference.get("source_url") not in source_urls
                                  for reference in references):
        raise ValueError("Audit manifest contains an unknown source reference")


def validate_image(content_type: str | None, body: bytes) -> tuple[str, str]:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image content type: {normalized_type or 'missing'}")
    extension, signatures = ALLOWED_IMAGE_TYPES[normalized_type]
    if normalized_type == "image/webp":
        valid_signature = body.startswith(b"RIFF") and body[8:12] == b"WEBP"
    else:
        valid_signature = any(body.startswith(signature) for signature in signatures)
    if not valid_signature:
        raise ValueError(f"Invalid {normalized_type} signature")
    return normalized_type, extension


def object_key(prefix: str, digest: str, extension: str) -> str:
    clean_prefix = prefix.strip("/")
    return f"{clean_prefix}/{digest[:2]}/{digest}.{extension}"


def upload_verified_image(
        s3: Any,
        *,
        account_id: str,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
        digest: str) -> str:
    try:
        existing = s3.head_object(
            Bucket=bucket, Key=key, ExpectedBucketOwner=account_id)
    except s3.exceptions.NoSuchKey:
        existing = None
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        existing = None
    if existing is None:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="public,max-age=31536000,immutable",
            ContentDisposition="inline",
            Metadata={"sha256": digest},
            ServerSideEncryption="AES256",
            IfNoneMatch="*",
            ExpectedBucketOwner=account_id,
        )
        outcome = "created"
    else:
        if existing.get("ContentLength") != len(body) or existing.get("Metadata", {}).get("sha256") != digest:
            raise ValueError(f"Existing S3 object does not match: {key}")
        outcome = "verified_existing"
    verified = s3.head_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account_id)
    if verified.get("ContentLength") != len(body) or verified.get("Metadata", {}).get("sha256") != digest:
        raise ValueError(f"S3 readback verification failed: {key}")
    return outcome


def mirror_manifest(
        manifest: dict[str, Any],
        *,
        s3: Any,
        account_id: str,
        bucket: str,
        prefix: str,
        public_base_url: str,
        timeout: float,
        max_bytes: int) -> dict[str, Any]:
    validate_manifest(manifest)
    uploads: list[dict[str, Any]] = []
    for source in manifest["sources"]:
        source_url = source["source_url"]
        if source.get("classification") == "origin_failed":
            uploads.append({"source_url": source_url, "status": "skipped_origin_failed"})
            continue
        result = request_url(source_url, timeout=timeout, max_bytes=max_bytes)
        if result.status != 200 or result.body is None:
            uploads.append({
                "source_url": source_url,
                "status": "download_failed",
                "http_status": result.status,
                "error": result.error,
            })
            continue
        try:
            content_type, extension = validate_image(result.content_type, result.body)
        except ValueError as error:
            uploads.append({
                "source_url": source_url,
                "status": "validation_failed",
                "error": str(error),
            })
            continue
        digest = hashlib.sha256(result.body).hexdigest()
        key = object_key(prefix, digest, extension)
        outcome = upload_verified_image(
            s3,
            account_id=account_id,
            bucket=bucket,
            key=key,
            body=result.body,
            content_type=content_type,
            digest=digest,
        )
        relative_key = key.removeprefix(prefix.strip("/") + "/")
        uploads.append({
            "source_url": source_url,
            "status": outcome,
            "sha256": digest,
            "s3_key": key,
            "public_url": f"{public_base_url.rstrip('/')}/{relative_key}",
            "content_type": content_type,
            "bytes": len(result.body),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket,
        "prefix": prefix.strip("/"),
        "public_base_url": public_base_url.rstrip("/"),
        "uploads": uploads,
        "references": manifest["references"],
    }


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_migration_sql(mapping: dict[str, Any]) -> str:
    public_urls = {
        upload["source_url"]: upload["public_url"]
        for upload in mapping.get("uploads", [])
        if upload.get("status") in {"created", "verified_existing"}
    }
    statements = [
        "BEGIN;",
        "SET LOCAL lock_timeout = '5s';",
        "SET LOCAL statement_timeout = '15min';",
    ]
    seen: set[tuple[Any, ...]] = set()
    for reference in mapping.get("references", []):
        old_url = reference["source_url"]
        new_url = public_urls.get(old_url)
        if new_url is None:
            continue
        product_id = require_positive_int(reference.get("product_id"), "product_id")
        kind = reference.get("kind")
        selector = reference.get("selector") or {}
        identity = (kind, product_id, json.dumps(selector, sort_keys=True), old_url)
        if identity in seen:
            continue
        seen.add(identity)
        old_sql, new_sql = sql_literal(old_url), sql_literal(new_url)
        if kind == "product":
            statements.append(
                f"UPDATE product_service.product SET image_url = {new_sql} "
                f"WHERE product_id = {product_id} AND image_url = {old_sql};")
        elif kind == "product_image":
            sequence = require_nonnegative_int(selector.get("sequence"), "sequence")
            statements.append(
                f"UPDATE product_service.product_image SET image_url = {new_sql} "
                f"WHERE product_id = {product_id} AND sequence = {sequence} "
                f"AND image_url = {old_sql};")
        elif kind == "product_option":
            option_id = require_positive_int(selector.get("option_id"), "option_id")
            statements.append(
                f"UPDATE product_service.product_option SET image_url = {new_sql} "
                f"WHERE product_id = {product_id} AND option_id = {option_id} "
                f"AND image_url = {old_sql};")
        elif kind == "product_size_guide":
            statements.append(
                f"UPDATE product_service.product_size_guide SET guide_image_url = {new_sql} "
                f"WHERE product_id = {product_id} AND guide_image_url = {old_sql};")
        elif kind == "color_image_mapping":
            statements.append(
                "UPDATE product_service.product AS p SET color_image_mappings = ("
                "SELECT jsonb_agg(CASE WHEN item->>'imageUrl' = " + old_sql
                + " THEN jsonb_set(item, '{imageUrl}', to_jsonb(" + new_sql
                + "::text)) ELSE item END ORDER BY ordinal) "
                "FROM jsonb_array_elements(p.color_image_mappings) WITH ORDINALITY AS values_(item, ordinal)) "
                f"WHERE p.product_id = {product_id} AND EXISTS (SELECT 1 FROM "
                "jsonb_array_elements(p.color_image_mappings) AS item "
                f"WHERE item->>'imageUrl' = {old_sql});")
    statements.extend([
        "-- Review the affected row count before replacing this line with COMMIT.",
        "ROLLBACK;",
        "",
    ])
    return "\n".join(statements)


def require_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_audit(args: argparse.Namespace) -> int:
    audit = build_audit(
        args.api_base_url,
        args.referer,
        args.page_size,
        args.timeout,
        args.workers,
        args.max_products,
    )
    write_json(args.output, audit)
    counts: dict[str, int] = {}
    for source in audit["sources"]:
        classification = source["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    print(json.dumps({
        "output": str(args.output),
        "product_count": audit["product_count"],
        "source_count": audit["source_count"],
        "classifications": counts,
        "aws_calls": False,
        "database_writes": False,
    }, ensure_ascii=False))
    return 0


def run_mirror(args: argparse.Namespace) -> int:
    if not args.apply_s3_writes:
        raise ValueError("mirror requires --apply-s3-writes")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    config = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "standard", "total_max_attempts": 3},
    )
    caller = session.client("sts", config=config).get_caller_identity()
    if caller.get("Account") != args.account_id:
        raise ValueError("AWS caller account does not match --account-id")
    s3 = session.client("s3", config=config)
    mapping = mirror_manifest(
        manifest,
        s3=s3,
        account_id=args.account_id,
        bucket=args.bucket,
        prefix=args.prefix,
        public_base_url=args.public_base_url,
        timeout=args.timeout,
        max_bytes=args.max_bytes,
    )
    write_json(args.output, mapping)
    args.sql_output.write_text(build_migration_sql(mapping), encoding="utf-8")
    statuses: dict[str, int] = {}
    for upload in mapping["uploads"]:
        status = upload["status"]
        statuses[status] = statuses.get(status, 0) + 1
    print(json.dumps({
        "output": str(args.output),
        "sql_output": str(args.sql_output),
        "statuses": statuses,
        "database_writes": False,
    }, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Audit product image URLs without AWS writes")
    audit.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    audit.add_argument("--referer", default=DEFAULT_REFERER)
    audit.add_argument("--page-size", type=int, default=100)
    audit.add_argument("--max-products", type=int)
    audit.add_argument("--workers", type=int, default=8)
    audit.add_argument("--timeout", type=float, default=15)
    audit.add_argument("--output", type=Path, required=True)
    audit.set_defaults(handler=run_audit)

    mirror = commands.add_parser("mirror", help="Mirror audited images and write rollback-safe SQL")
    mirror.add_argument("--manifest", type=Path, required=True)
    mirror.add_argument("--output", type=Path, required=True)
    mirror.add_argument("--sql-output", type=Path, required=True)
    mirror.add_argument("--account-id", required=True)
    mirror.add_argument("--bucket", required=True)
    mirror.add_argument("--public-base-url", required=True)
    mirror.add_argument("--profile", default="fitzza")
    mirror.add_argument("--region", default="ap-northeast-2")
    mirror.add_argument("--prefix", default=DEFAULT_PREFIX)
    mirror.add_argument("--timeout", type=float, default=30)
    mirror.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    mirror.add_argument("--apply-s3-writes", action="store_true")
    mirror.set_defaults(handler=run_mirror)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (ClientError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
