"""Stream product/review images and privacy-minimized reviews directly to S3."""

from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from botocore.exceptions import ClientError


IMAGE_HOSTS = {"image.msscdn.net", "image.musinsa.com", "image.musinsa.co.kr"}
REVIEW_URL = "https://goods.musinsa.com/api2/review/v1/view/list"
IMAGE_BASE_URL = "https://image.msscdn.net"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
EXTENSIONS = {
    "image/avif": ".avif", "image/gif": ".gif", "image/jpeg": ".jpg",
    "image/png": ".png", "image/webp": ".webp",
}


class ImageSourceError(RuntimeError):
    """An individual source image cannot be downloaded or validated."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as error:
        if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return False
        raise


def put_json(s3, bucket: str, key: str, value: object) -> None:
    body = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json",
                  ServerSideEncryption="AES256")


def normalize_image_url(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("/"):
        value = f"{IMAGE_BASE_URL}{value}"
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return None
    return value


def fetch_image(url: str, *, attempts: int = 4) -> tuple[bytes, str, str]:
    normalized = normalize_image_url(url)
    if normalized is None:
        raise ImageSourceError("unapproved image URL")
    request = Request(normalized, headers={
        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
        "User-Agent": "Mozilla/5.0 (compatible; FitzzaCloudCrawler/1.0)",
    })
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                if normalize_image_url(response.geturl()) is None:
                    raise ImageSourceError("image redirect left approved hosts")
                data = response.read(MAX_IMAGE_BYTES + 1)
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if not data or len(data) > MAX_IMAGE_BYTES:
                raise ImageSourceError("invalid image byte length")
            extension = EXTENSIONS.get(content_type)
            if extension is None:
                raise ImageSourceError(
                    f"unsupported image content type: {content_type}"
                )
            valid = ((extension == ".jpg" and data.startswith(b"\xff\xd8\xff"))
                     or (extension == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
                     or (extension == ".gif" and data.startswith((b"GIF87a", b"GIF89a")))
                     or (extension == ".webp" and len(data) >= 12
                         and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
                     or (extension == ".avif" and len(data) >= 12
                         and data[4:8] == b"ftyp" and b"avif" in data[8:32]))
            if not valid:
                raise ImageSourceError("image signature does not match content type")
            return data, content_type, extension
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise ImageSourceError(f"HTTP {error.code}") from error
        except (URLError, TimeoutError):
            pass
        if attempt + 1 == attempts:
            raise ImageSourceError("image download exhausted retries")
        time.sleep(2 ** attempt + random.uniform(0, 0.25))
    raise AssertionError("unreachable")


def upload_image(s3, bucket: str, stem: str, url: str) -> dict:
    data, content_type, extension = fetch_image(url)
    key = f"{stem}{extension}"
    digest = hashlib.sha256(data).hexdigest()
    if not object_exists(s3, bucket, key):
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type,
                      ServerSideEncryption="AES256",
                      Metadata={"sha256": digest, "source-url-sha256": hashlib.sha256(url.encode()).hexdigest()})
    return {"source_url": url, "s3_key": key, "sha256": digest,
            "size_bytes": len(data), "content_type": content_type}


def product_image_urls(product: dict) -> list[tuple[str, str]]:
    candidates = [("product", value) for value in product.get("images") or []]
    candidates += [("color", item.get("image_url"))
                   for item in product.get("color_image_mappings") or []
                   if isinstance(item, dict)]
    guide = (product.get("size") or {}).get("guide_image")
    if guide:
        candidates.append(("size-guide", guide))
    seen, result = set(), []
    for kind, value in candidates:
        url = normalize_image_url(value)
        if url and url not in seen:
            seen.add(url)
            result.append((kind, url))
    return result


def upload_product_images(s3, bucket: str, prefix: str, product: dict) -> dict:
    product_id = str(product["product_id"])
    manifest_key = f"{prefix}/images/products/{product_id}/manifest.json"
    if object_exists(s3, bucket, manifest_key):
        return {"skipped": True, "image_count": 0}
    images, failures = [], []
    for index, (kind, url) in enumerate(product_image_urls(product), 1):
        try:
            record = upload_image(s3, bucket,
                f"{prefix}/images/products/{product_id}/{index:03d}", url)
            record["kind"] = kind
            images.append(record)
        except ImageSourceError as error:
            failure = {"kind": kind, "source_url": url, "error": str(error)}
            failures.append(failure)
            print(json.dumps({"event": "image_download_skipped",
                "scope": "product", "product_id": product_id, **failure}),
                flush=True)
        time.sleep(0.2)
    if failures:
        put_json(s3, bucket,
            f"{prefix}/audit/image-download-failures/products/{product_id}.json",
            {"schema_version": 1, "product_id": product_id,
             "recorded_at": utc_now(), "failures": failures})
    manifest = {"schema_version": 1, "product_id": product_id,
                "downloaded_at": utc_now(), "image_count": len(images),
                "images": images}
    put_json(s3, bucket, manifest_key, manifest)
    return manifest


def fetch_review_page(product_id: str, page: int, page_size: int) -> dict:
    query = urlencode({"page": page, "pageSize": page_size, "goodsNo": product_id,
        "sort": "new", "selectedSimilarNo": product_id, "myFilter": "false",
        "hasPhoto": "false", "isExperience": "false"})
    request = Request(f"{REVIEW_URL}?{query}", headers={"Accept": "application/json",
        "Referer": f"https://www.musinsa.com/products/{product_id}",
        "User-Agent": "Mozilla/5.0 (compatible; FitzzaCloudCrawler/1.0)"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise
        except (URLError, TimeoutError):
            pass
        if attempt + 1 == 4:
            raise RuntimeError("review request exhausted retries")
        time.sleep(2 ** attempt + random.uniform(0, 0.25))
    raise AssertionError("unreachable")


def normalize_review(value: dict) -> dict:
    review_id = value.get("no")
    if not isinstance(review_id, int):
        raise ValueError("review ID is missing")
    survey = value.get("reviewSurveySatisfaction")
    questions = survey.get("questions", []) if isinstance(survey, dict) else []
    return {"source_review_id": review_id, "review_type": value.get("type"),
        "content": value.get("content"), "grade": value.get("grade"),
        "goods_option": value.get("goodsOption"), "created_at": value.get("createDate"),
        "like_count": value.get("likeCount"), "survey": [
            {"attribute": question.get("attribute"), "answers": [answer.get("answerShortText")
             for answer in question.get("answers", []) if isinstance(answer, dict)
             and answer.get("answerShortText") is not None]}
            for question in questions if isinstance(question, dict)],
        "image_files": []}


def upload_reviews(s3, bucket: str, prefix: str, product_id: str,
                   max_reviews: int = 100) -> dict:
    output_key = f"{prefix}/reviews/data/{product_id}.json"
    if object_exists(s3, bucket, output_key):
        return {"skipped": True, "review_count": 0, "image_count": 0}
    reviews, seen, reported_total, page = [], set(), 0, 0
    while len(reviews) < max_reviews:
        payload = fetch_review_page(product_id, page, 20)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("invalid review response")
        items, reported_total = data["list"], int(data.get("total", 0))
        total_pages = int((data.get("page") or {}).get("totalPages", 0))
        for item in items:
            review = normalize_review(item)
            if review["source_review_id"] not in seen:
                seen.add(review["source_review_id"])
                reviews.append(review)
            if len(reviews) >= max_reviews:
                break
        page += 1
        if not items or (total_pages and page >= total_pages):
            break
        time.sleep(1.0)
    result = {"schema_version": 1, "source": "musinsa", "product_id": product_id,
        "collected_at": utc_now(), "reported_review_count": reported_total,
        "collected_review_count": len(reviews), "truncated": len(reviews) < reported_total,
        "downloaded_review_image_count": 0, "reviews": reviews}
    put_json(s3, bucket, output_key, result)
    return {"review_count": len(reviews), "image_count": 0}
