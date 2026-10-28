import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "crawler/src"))
sys.path.insert(0, str(ROOT / "indexer"))

import embed_job  # noqa: E402
import import_job  # noqa: E402
import review_gate  # noqa: E402
import vector_points  # noqa: E402

BUCKET = "bucket"
RUN = "pipeline/runs/collection-test"
VRUN = "pipeline/vector-runs/collection-test-fclip-01"
REVISION = "a" * 40


class ConditionalFailed(Exception):
    pass


class FakeS3:
    class exceptions:
        NoSuchKey = KeyError

    def __init__(self):
        self.objects = {}
        self.gets = []

    def get_object(self, Bucket, Key):
        self.gets.append(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **kwargs):
        if IfNoneMatch == "*" and Key in self.objects:
            raise ConditionalFailed(Key)
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Key])

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": key} for key in sorted(objects) if key.startswith(Prefix)]}
        return Paginator()


def png(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(output, format="PNG")
    return output.getvalue()


def product(product_id: int, colors: list[tuple[str, str]]) -> dict:
    return {"product_id": product_id, "name": f"상품 {product_id}", "brand": {"name": "브랜드"},
            "dataset": {"logical_category": "상의"}, "category": {"categoryDepth2Title": "티셔츠"},
            "price": {"normal": 19000}, "source_url": f"https://www.musinsa.com/products/{product_id}",
            "size": {"measurements": [{"size": "M", "sequence": 1, "measurements": {"총장": "70", "어깨너비": "x"}}]},
            "color_image_mappings": [{"product_id": product_id, "color_raw": raw, "image_url": url}
                                     for raw, url in colors]}


def build_run(root: Path) -> FakeS3:
    """Approved bundle + curated manifest + stored images for two products (one image never stored)."""
    s3 = FakeS3()
    bundle = root / "bundle"
    (bundle / "config").mkdir(parents=True)
    products = {
        101: product(101, [("블랙", "https://image.msscdn.net/a/101_bk.jpg"),
                           ("BK", "https://image.msscdn.net/a/101_bk2.jpg")]),
        102: product(102, [("네이비", "https://image.msscdn.net/a/102_na.jpg"),
                           ("화이트", "https://image.msscdn.net/a/102_wh_missing.jpg")]),
    }
    records = []
    for product_id, item in products.items():
        data = json.dumps(item, ensure_ascii=False).encode("utf-8")
        path = bundle / "data/상의" / f"{product_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        key = f"{RUN}/curated/data/상의/{product_id}.json"
        s3.objects[key] = data
        records.append({"product_id": str(product_id), "category": "상의", "path": f"상의/{product_id}.json",
                        "sha256": hashlib.sha256(data).hexdigest(), "s3_key": key})
    s3.objects[f"{RUN}/curated/manifest.json"] = json.dumps({"products": records}).encode()
    stored = {101: ["101_bk.jpg", "101_bk2.jpg"], 102: ["102_na.jpg"]}
    for product_id, names in stored.items():
        images = []
        for index, name in enumerate(names, 1):
            data = png((index * 40, 0, 0))
            key = f"{RUN}/images/products/{product_id}/{index:03d}.png"
            s3.objects[key] = data
            images.append({"source_url": f"https://image.msscdn.net/a/{name}", "s3_key": key,
                           "sha256": hashlib.sha256(data).hexdigest(), "kind": "color"})
        s3.objects[f"{RUN}/images/products/{product_id}/manifest.json"] = json.dumps({"images": images}).encode()
    color_map = {"블랙": "black", "bk": "black", "네이비": "navy", "화이트": "white"}
    (bundle / "config/color_map.json").write_text(json.dumps(color_map, ensure_ascii=False), encoding="utf-8")
    with (bundle / "config/color_map_review.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["color_raw"])
        writer.writerow(["BK"])
    (bundle / "config/reviewed_colors.json").write_text('{"bk": "black"}', encoding="utf-8")
    review_gate.approve(bundle)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as output:
        output.add(bundle / "data", arcname="data")
        output.add(bundle / "config", arcname="config")
    s3.objects[f"{RUN}/approved/bundle.tar.gz"] = archive.getvalue()
    return s3


class FakeModel:
    calls = 0

    def __init__(self, revision, threads):
        pass

    def encode(self, images):
        FakeModel.calls += len(images)
        vectors = []
        for image in images:
            red = image.getpixel((0, 0))[0]
            vector = [0.0] * 512
            vector[red % 512] = 1.0
            vector[(red + 1) % 512] = 0.5
            vectors.append(vector)
        return vectors


def embed_args(**overrides):
    values = {"bucket": BUCKET, "run_id": "collection-test", "vector_run_id": "collection-test-fclip-01",
              "model_revision": REVISION, "part_size": 2, "threads": 1}
    return SimpleNamespace(**{**values, **overrides})


class VectorRunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.s3 = build_run(self.root)
        FakeModel.calls = 0

    def tearDown(self):
        self.folder.cleanup()

    def embed(self, work: str, **overrides):
        (self.root / work).mkdir()
        with patch.dict(os.environ, {"WORK_DIR": str(self.root / work)}), \
                patch("boto3.client", return_value=self.s3), patch.object(embed_job, "FashionClip", FakeModel):
            return embed_job.run(embed_args(**overrides))

    def test_embeds_parts_and_resume_skips_finished_parts(self):
        report = self.embed("w1")
        self.assertEqual(report["point_count"], 3)
        self.assertEqual(report["input_embedding_count"], 3)
        self.assertEqual(report["planning_failures_by_reason"], {"image_not_stored": 1})
        self.assertEqual(report["part_count"], 2)
        self.assertEqual(FakeModel.calls, 3)
        lines = [json.loads(line) for key, body in self.s3.objects.items()
                 if key.startswith(f"{VRUN}/embeddings/") for line in body.decode().splitlines()]
        payload = next(line["payload"] for line in lines if line["payload"]["color_variant"] == "BK")
        self.assertEqual((payload["product_id"], payload["color_normalized"], payload["normalized_color"]),
                         (101, ["black"], "black"))
        self.assertEqual(payload["sizes"], [{"size": "M", "sequence": 1, "measurements": {"top_length": 70.0}}])
        again = self.embed("w2")
        self.assertEqual(FakeModel.calls, 3)
        self.assertEqual(again["input_embedding_count"], 3)

    def test_resume_with_different_model_revision_is_rejected(self):
        self.embed("w1")
        with self.assertRaisesRegex(ValueError, "different data"):
            self.embed("w2", model_revision="b" * 40)

    def test_bundle_must_match_curated_manifest(self):
        manifest = json.loads(self.s3.objects[f"{RUN}/curated/manifest.json"])
        manifest["products"][0]["sha256"] = "0" * 64
        self.s3.objects[f"{RUN}/curated/manifest.json"] = json.dumps(manifest).encode()
        with self.assertRaisesRegex(ValueError, "differs from curated manifest"):
            self.embed("w1")

    def test_import_creates_and_validates_versioned_collection(self):
        from qdrant_client import QdrantClient

        self.embed("w1")
        memory = QdrantClient(":memory:")
        args = SimpleNamespace(bucket=BUCKET, vector_run_id="collection-test-fclip-01",
                               collection="fitzza_products_test_01", batch_size=100, resume=False)
        with patch.dict(os.environ, {"QDRANT_URL": "http://unused"}), \
                patch("boto3.client", return_value=self.s3), patch("qdrant_client.QdrantClient", return_value=memory):
            result = import_job.run(args)
            self.assertTrue(result["passed"], result)
            self.assertEqual(result["qdrant_point_count"], 3)
            self.assertEqual(result["color_distribution"], {"black": 2, "navy": 1})
            with self.assertRaisesRegex(ValueError, "already exists"):
                import_job.run(args)
        self.assertIn(f"{VRUN}/import-report-fitzza_products_test_01.json", self.s3.objects)

    def test_import_rejects_invalid_vectors_before_qdrant(self):
        self.embed("w1")
        key = f"{VRUN}/embeddings/part-00000.jsonl"
        lines = self.s3.objects[key].decode().splitlines()
        record = json.loads(lines[0])
        record["vector"] = record["vector"][:10]
        self.s3.objects[key] = ("\n".join([json.dumps(record)] + lines[1:]) + "\n").encode()
        args = SimpleNamespace(bucket=BUCKET, vector_run_id="collection-test-fclip-01",
                               collection="fitzza_products_test_01", batch_size=100, resume=False)
        with patch("boto3.client", return_value=self.s3), patch("qdrant_client.QdrantClient") as qdrant:
            result = import_job.run(args)
        self.assertFalse(result["passed"])
        self.assertEqual(result["record_problems"], {"invalid_vector:wrong_dimension": 1})
        qdrant.assert_not_called()


class DeploymentModeTests(unittest.TestCase):
    def test_no_network_without_execution_flag(self):
        for module, argv in ((embed_job, ["--run-id", "r", "--vector-run-id", "v", "--model-revision", REVISION]),
                             (import_job, ["--vector-run-id", "v", "--collection", "fitzza_products_v1"])):
            with self.subTest(module=module.__name__), patch("sys.argv", ["job", "--bucket", "b", *argv]), \
                    patch("boto3.client") as aws:
                module.main()
                aws.assert_not_called()

    def test_import_refuses_alias_like_or_foreign_collection_names(self):
        for name in ("fitzza_products_current", "musinsa_products", "fitzza_products_"):
            with self.subTest(name=name), patch("sys.argv", ["job", "--bucket", "b", "--vector-run-id", "v",
                                                             "--collection", name]):
                with self.assertRaises(ValueError):
                    import_job.main()

    def test_point_ids_are_deterministic_and_payload_colors_agree(self):
        self.assertEqual(vector_points.point_id(1, "bk", "k"), vector_points.point_id(1, "bk", "k"))
        self.assertNotEqual(vector_points.point_id(1, "bk", "k"), vector_points.point_id(1, "bk", "k2"))
        payload = vector_points.make_payload(product(1, []), " BK ", "black", "https://x", "k")
        self.assertEqual(vector_points.payload_problems(payload), [])
        with self.assertRaises(ValueError):
            vector_points.make_payload(product(1, []), "BK", "light gray", "https://x", "k")


if __name__ == "__main__":
    unittest.main()
