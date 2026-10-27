import hashlib
import json

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


def test_validate_run_checks_counts_and_manifest():
    product = b'{"product_id":"101"}'
    manifest_hash = hashlib.sha256(product).hexdigest()
    s3 = FakeS3({
        "r/curated/manifest.json": json.dumps({"files": {"data/cat/101.json": manifest_hash}}).encode(),
        "r/curated/data/cat/101.json": product,
        "r/reviews/data/101.json": b"{}",
        "r/images/products/101/1.jpg": b"jpg",
        "r/audit/image-download-failures/products/101.json": b"{}",
    })

    report = validate_run(s3, "bucket", "r")

    assert report["valid"] is True
    assert report["product_json_count"] == 1
    assert report["review_json_count"] == 1
    assert report["product_image_count"] == 1
    assert report["image_failure_audit_count"] == 1
