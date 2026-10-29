import hashlib
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "data-pipeline-integrity"))
import integrity_check


class Body:
    def __init__(self, value):
        self.value = value
        self.closed = False

    def read(self):
        return self.value

    def close(self):
        self.closed = True


class FakeS3:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, *, Bucket, Key):
        return {"Body": Body(self.objects[Key])}


def product_bytes(product_id, **fields):
    return json.dumps({"product_id": product_id, **fields}).encode()


def catalog(product_ids, tamper=None):
    manifest_key = "pipeline/current/manifest.json"
    objects, records = {}, []
    for product_id in product_ids:
        key = f"pipeline/runs/collection-20261025-01/curated/data/모자/{product_id}.json"
        data = product_bytes(product_id, color_image_mappings=[{"image_url": f"https://image.example/{product_id}.jpg"}])
        records.append({"product_id": str(product_id), "sha256": hashlib.sha256(data).hexdigest(), "s3_key": key})
        objects[key] = tamper(data) if tamper and product_id == product_ids[-1] else data
    objects[manifest_key] = json.dumps({"products": records}).encode()
    return FakeS3(objects), manifest_key


def test_integrity_checks_objects_images_and_qdrant(monkeypatch):
    s3, manifest_key = catalog([101])
    monkeypatch.setattr(integrity_check, "_image_is_reachable", lambda url: True)
    monkeypatch.setattr(integrity_check, "_qdrant_points", lambda url, collection: 1)
    monkeypatch.setattr(integrity_check, "_qdrant_product_ids", lambda url, collection: {"101"})

    report = integrity_check.check_catalog(s3, "bucket", manifest_key, "http://qdrant:6333", "products")

    assert report["ok"] is True
    assert report["qdrant"]["points_count"] == 1
    assert report["qdrant"]["unindexed_product_count"] == 0
    assert report["image"]["unreachable_count"] == 0


def test_seed_layout_object_is_found_by_digest(monkeypatch):
    manifest_key = "pipeline/current/manifest.json"
    data = product_bytes(101, images=["https://image.example/101.jpg"])
    digest = hashlib.sha256(data).hexdigest()
    objects = {
        manifest_key: json.dumps({"products": [{"product_id": "101", "sha256": digest}]}).encode(),
        f"pipeline/current/objects/{digest}": data,
    }
    monkeypatch.setattr(integrity_check, "_image_is_reachable", lambda url: True)
    monkeypatch.setattr(integrity_check, "_qdrant_points", lambda url, collection: 1)
    monkeypatch.setattr(integrity_check, "_qdrant_product_ids", lambda url, collection: {"101"})

    assert integrity_check.check_catalog(FakeS3(objects), "bucket", manifest_key, "http://qdrant:6333", "products")["ok"] is True


def test_integrity_fails_when_a_product_is_not_indexed_even_with_enough_points(monkeypatch):
    s3, manifest_key = catalog([101, 102])
    monkeypatch.setattr(integrity_check, "_image_is_reachable", lambda url: True)
    monkeypatch.setattr(integrity_check, "_qdrant_points", lambda url, collection: 50)
    monkeypatch.setattr(integrity_check, "_qdrant_product_ids", lambda url, collection: {"101"})

    report = integrity_check.check_catalog(s3, "bucket", manifest_key, "http://qdrant:6333", "products")

    assert report["ok"] is False
    assert report["qdrant"]["unindexed_product_count"] == 1
    assert report["qdrant"]["sample_product_ids"] == ["102"]


def test_integrity_fails_when_the_index_cannot_be_read(monkeypatch):
    s3, manifest_key = catalog([101])
    monkeypatch.setattr(integrity_check, "_image_is_reachable", lambda url: True)
    monkeypatch.setattr(integrity_check, "_qdrant_points", lambda url, collection: None)
    monkeypatch.setattr(integrity_check, "_qdrant_product_ids", lambda url, collection: None)

    report = integrity_check.check_catalog(s3, "bucket", manifest_key, "http://qdrant:6333", "products")

    assert report["ok"] is False and report["qdrant"]["product_lookup_ok"] is False


def test_integrity_fails_when_an_object_differs_from_the_manifest_digest(monkeypatch):
    s3, manifest_key = catalog([101, 102], tamper=lambda data: data.replace(b"image.example", b"image.changed"))
    monkeypatch.setattr(integrity_check, "_image_is_reachable", lambda url: True)
    monkeypatch.setattr(integrity_check, "_qdrant_points", lambda url, collection: 2)
    monkeypatch.setattr(integrity_check, "_qdrant_product_ids", lambda url, collection: {"101", "102"})

    report = integrity_check.check_catalog(s3, "bucket", manifest_key, "http://qdrant:6333", "products")

    assert report["ok"] is False
    assert report["s3"]["invalid_object_count"] == 1
    assert report["s3"]["invalid_object_sample_product_ids"] == ["102"]


def test_qdrant_product_ids_follow_scroll_pages(monkeypatch):
    pages = iter([
        {"result": {"points": [{"id": "a", "payload": {"product_id": 101}}], "next_page_offset": "b"}},
        {"result": {"points": [{"id": "b", "payload": {"product_id": 102}}, {"id": "c", "payload": {}}], "next_page_offset": None}},
    ])
    bodies = []

    class Response:
        status = 200

        def __init__(self, data):
            self.data = data

        def read(self):
            return json.dumps(self.data).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data))
        return Response(next(pages))

    monkeypatch.setattr(integrity_check, "urlopen", fake_urlopen)

    assert integrity_check._qdrant_product_ids("http://qdrant:6333", "musinsa_products") == {"101", "102"}
    assert "offset" not in bodies[0] and bodies[1]["offset"] == "b"
    assert bodies[0]["with_payload"] == ["product_id"] and bodies[0]["with_vector"] is False
