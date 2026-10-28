import hashlib
import json

import pytest

from src.validate_import import validate_run


class Body:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value

    def close(self):
        pass


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):
        return {"Body": Body(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, **kwargs):
        keys = [key for key in self.objects if key.startswith(Prefix)]
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}


PRODUCT = b'{"product_id":"101"}'


def run_objects(manifest: dict, extra: dict | None = None) -> FakeS3:
    objects = {
        "r/curated/manifest.json": json.dumps(manifest).encode(),
        "r/curated/data/cat/101.json": PRODUCT,
        "r/reviews/data/101.json": b"{}",
        "r/images/products/101/1.jpg": b"jpg",
        "r/audit/image-download-failures/products/101.json": b"{}",
    }
    objects.update(extra or {})
    return FakeS3(objects)


def products_manifest(sha256: str, path: str = "cat/101.json") -> dict:
    return {"schema_version": 1, "products": [
        {"product_id": "101", "category": "cat", "path": path, "sha256": sha256,
         "s3_key": f"r/curated/data/{path}"}]}


def test_validate_run_checks_counts_and_legacy_files_manifest():
    manifest_hash = hashlib.sha256(PRODUCT).hexdigest()
    report = validate_run(run_objects({"files": {"data/cat/101.json": manifest_hash}}), "bucket", "r")

    assert report["valid"] is True
    assert report["product_json_count"] == 1
    assert report["review_json_count"] == 1
    assert report["product_image_count"] == 1
    assert report["image_failure_audit_count"] == 1
    assert report["manifest_sha256_checked_count"] == 1


def test_products_manifest_hashes_are_compared():
    report = validate_run(run_objects(products_manifest(hashlib.sha256(PRODUCT).hexdigest())), "bucket", "r")

    assert report["valid"] is True
    assert report["manifest_hash_entry_count"] == 1
    assert report["manifest_sha256_checked_count"] == 1


def test_products_manifest_digest_mismatch_fails():
    report = validate_run(run_objects(products_manifest("0" * 64)), "bucket", "r")

    assert report["valid"] is False
    assert report["manifest_sha256_mismatches"] == ["data/cat/101.json"]


def test_manifest_without_hash_entries_fails_closed():
    report = validate_run(run_objects({"schema_version": 1, "products": []}), "bucket", "r")

    assert report["valid"] is False
    assert report["manifest_sha256_checked_count"] == 0


def test_products_outside_manifest_and_missing_objects_fail():
    digest = hashlib.sha256(PRODUCT).hexdigest()
    manifest = products_manifest(digest)
    manifest["products"].append({"product_id": "202", "category": "cat", "path": "cat/202.json",
                                 "sha256": digest, "s3_key": "r/curated/data/cat/202.json"})
    report = validate_run(run_objects(manifest, {"r/curated/data/cat/303.json": b"{}"}), "bucket", "r")

    assert report["valid"] is False
    assert report["products_not_in_manifest"] == ["data/cat/303.json"]
    assert report["manifest_products_missing_in_s3"] == ["data/cat/202.json"]


def test_products_manifest_keys_must_be_curated_product_json():
    for key in ("r/curated/manifest.json", "r/curated/report.json", "r/curated/data/cat/101.txt"):
        manifest = {"products": [{"product_id": "101", "s3_key": key, "sha256": "0" * 64}]}
        with pytest.raises(ValueError, match="not a curated product JSON"):
            validate_run(run_objects(manifest), "bucket", "r")


def test_legacy_non_json_data_entry_is_hash_checked_not_reported_missing():
    note = b"note"
    manifest = {"files": {"data/cat/101.json": hashlib.sha256(PRODUCT).hexdigest(),
                          "data/README.txt": hashlib.sha256(note).hexdigest()}}
    report = validate_run(run_objects(manifest, {"r/curated/data/README.txt": note}), "bucket", "r")

    assert report["valid"] is True
    assert report["manifest_products_missing_in_s3"] == []
    assert report["manifest_sha256_checked_count"] == 2
