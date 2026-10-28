import hashlib
import io
import json

from botocore.exceptions import ClientError

from scripts import verify_s3_import_integrity
from scripts.verify_s3_import_integrity import ExpectedCounts, verify


class Paginator:
    def __init__(self, objects):
        self.objects = objects

    def paginate(self, *, Bucket, Prefix):
        del Bucket
        yield {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]}


class FakeS3:
    def __init__(self, objects, failing_keys=()):
        self.objects = objects
        self.failing_keys = set(failing_keys)

    def get_object(self, *, Bucket, Key):
        del Bucket
        if Key in self.failing_keys:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return Paginator(self.objects)


def encode(value):
    return json.dumps(value).encode()


def test_verify_accepts_matching_s3_and_db_summary():
    prefix = "pipeline/runs/collection-20261025-01"
    product = encode({"product_id": 101})
    product_key = f"{prefix}/curated/data/상의/101.json"
    objects = {
        f"{prefix}/curated/manifest.json": encode({"products": [{"product_id": "101", "s3_key": product_key, "sha256": hashlib.sha256(product).hexdigest()}]}),
        product_key: product,
        f"{prefix}/images/products/101/001.jpg": b"image",
        f"{prefix}/audit/image-download-failures/products/101.json": encode({"failures": [{}]}),
        f"{prefix}/reviews/data/101.json": encode({"product_id": "101", "collected_review_count": 2, "reviews": [{}, {}]}),
    }
    db = {"product_count": 1, "distinct_product_count": 1, "image_count": 1, "review_count": 2, "orphan_image_count": 0, "orphan_review_count": 0}

    report = verify(FakeS3(objects), "bucket", prefix, ExpectedCounts(1, 1, 1, 2), db)

    assert report["ok"] is True


def test_verify_reports_hash_duplicate_foreign_key_and_count_errors():
    prefix = "pipeline/runs/collection-20261025-01"
    product_key = f"{prefix}/curated/data/상의/101.json"
    objects = {
        f"{prefix}/curated/manifest.json": encode({"products": [
            {"product_id": "101", "s3_key": product_key, "sha256": "0" * 64},
            {"product_id": "101", "s3_key": product_key, "sha256": "0" * 64},
        ]}),
        product_key: encode({"product_id": 101}),
        f"{prefix}/images/products/999/001.jpg": b"image",
        f"{prefix}/reviews/data/999.json": encode({"product_id": "999", "reviews": [{}]}),
    }

    report = verify(FakeS3(objects), "bucket", prefix, ExpectedCounts(1, 1, 0, 1), None)

    assert report["ok"] is False
    assert any("sha256 mismatch" in error for error in report["errors"])
    assert any("duplicate" in error for error in report["errors"])
    assert any("foreign key" in error for error in report["errors"])
    assert any("image product id missing" in error for error in report["errors"])


def test_db_comparison_uses_s3_actual_counts_separately_from_expected_counts():
    prefix = "pipeline/runs/collection-20261025-01"
    product = encode({"product_id": 101})
    product_key = f"{prefix}/curated/data/상의/101.json"
    objects = {
        f"{prefix}/curated/manifest.json": encode({"products": [{"product_id": "101", "s3_key": product_key, "sha256": hashlib.sha256(product).hexdigest()}]}),
        product_key: product,
    }
    db = {"product_count": 1, "distinct_product_count": 1, "image_count": 0, "review_count": 0, "orphan_image_count": 0, "orphan_review_count": 0}

    report = verify(FakeS3(objects), "bucket", prefix, ExpectedCounts(2, 0, 0, 0), db)

    assert any("products: expected 2, got 1" in error for error in report["errors"])
    assert not any("DB product count" in error for error in report["errors"])


def test_verify_collects_object_and_layout_errors_and_continues():
    prefix = "pipeline/runs/collection-20261025-01"
    product_key = f"{prefix}/curated/data/상의/101.json"
    extra_key = f"{prefix}/curated/data/상의/202.json"
    review_key = f"{prefix}/reviews/data/101.json"
    failure_key = f"{prefix}/audit/image-download-failures/products/101.json"
    objects = {
        f"{prefix}/curated/manifest.json": encode({"products": [{"product_id": "101", "s3_key": product_key, "sha256": "0" * 64}]}),
        product_key: b"unreadable",
        extra_key: encode({"product_id": 202}),
        review_key: encode({"product_id": "202", "reviews": []}),
        failure_key: encode({"failures": [{}, {}]}),
    }

    report = verify(FakeS3(objects, failing_keys={product_key}), "bucket", prefix, ExpectedCounts(1, 0, 2, 0), None)

    assert report["actual"]["image_failures"] == 2
    assert any("object read failed" in error for error in report["errors"])
    assert any("curated object missing from manifest" in error for error in report["errors"])
    assert any("does not match file name" in error for error in report["errors"])
    assert any("review foreign key missing" in error for error in report["errors"])


def test_main_creates_output_parent_directory(monkeypatch, tmp_path):
    prefix = "pipeline/runs/collection-20261025-01"
    product = encode({"product_id": 101})
    product_key = f"{prefix}/curated/data/상의/101.json"
    client = FakeS3({
        f"{prefix}/curated/manifest.json": encode({"products": [{"product_id": "101", "s3_key": product_key, "sha256": hashlib.sha256(product).hexdigest()}]}),
        product_key: product,
    })
    output = tmp_path / "nested" / "integrity-report.json"
    monkeypatch.setattr(verify_s3_import_integrity.boto3, "client", lambda *args, **kwargs: client)
    monkeypatch.setattr("sys.argv", ["verify", "--bucket", "bucket", "--prefix", prefix, "--output", str(output)])

    assert verify_s3_import_integrity.main() == 1
    assert output.exists()
