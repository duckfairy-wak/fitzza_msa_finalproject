import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from src.jev_job import download_curated_products, main, object_exists

PREFIX = "pipeline/runs/collection-20261025-01"


class FakeS3:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def product_bytes(product_id: str) -> bytes:
    return json.dumps({"product_id": product_id,
                       "color_image_mappings": [{"color_raw": "블랙", "image_url": "x"}]},
                      ensure_ascii=False).encode("utf-8")


def manifest_record(product_id: str, data: bytes, category: str = "상의") -> dict:
    path = f"{category}/{product_id}.json"
    return {"product_id": product_id, "category": category, "path": path,
            "sha256": hashlib.sha256(data).hexdigest(), "s3_key": f"{PREFIX}/curated/data/{path}"}


def fake_run(records: list[dict], bodies: dict[str, bytes]) -> FakeS3:
    manifest = json.dumps({"schema_version": 1, "products": records}).encode("utf-8")
    return FakeS3({f"{PREFIX}/curated/manifest.json": manifest, **bodies})


class JevJobTests(unittest.TestCase):
    def test_default_never_calls_jev_or_registers_secrets(self):
        args = ["jev_job", "--bucket", "unused", "--run-id", "deployment-only"]
        with patch("sys.argv", args), patch("boto3.client") as aws, \
                patch("src.jev_job.subprocess.run") as jev:
            main()
            aws.assert_not_called()
            jev.assert_not_called()


class ObjectExistsTests(unittest.TestCase):
    def test_matches_only_the_exact_key(self):
        key = f"{PREFIX}/jev/color_map_jev_results.jsonl"
        listings = {"exact": [{"Key": key}], "longer": [{"Key": key + ".bak"}], "empty": []}
        expected = {"exact": True, "longer": False, "empty": False}
        for name, contents in listings.items():
            with self.subTest(name=name):
                s3 = MagicMock()
                s3.list_objects_v2.return_value = {"Contents": contents} if contents else {}
                self.assertEqual(object_exists(s3, "bucket", key), expected[name])
                s3.list_objects_v2.assert_called_once_with(Bucket="bucket", Prefix=key, MaxKeys=1)


class DownloadCuratedProductsTests(unittest.TestCase):
    def download(self, records: list[dict], bodies: dict[str, bytes]) -> tuple[dict, Path]:
        root = Path(tempfile.mkdtemp())
        summary = download_curated_products(fake_run(records, bodies), "bucket", PREFIX, root / "data")
        return summary, root / "data"

    def test_copies_verified_products_into_category_folders(self):
        first, second = product_bytes("101"), product_bytes("202")
        records = [manifest_record("101", first), manifest_record("202", second, "하의")]
        summary, data = self.download(records, {records[0]["s3_key"]: first,
                                                records[1]["s3_key"]: second})
        self.assertEqual(summary["input_layout"], "manifest")
        self.assertEqual(summary["product_count"], 2)
        self.assertEqual(len(summary["source_manifest_sha256"]), 64)
        self.assertEqual((data / "상의/101.json").read_bytes(), first)
        self.assertEqual((data / "하의/202.json").read_bytes(), second)

    def test_rejects_digest_mismatch(self):
        record = manifest_record("101", product_bytes("101"))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.download([record], {record["s3_key"]: product_bytes("101") + b" "})

    def test_rejects_product_identity_mismatch(self):
        other = product_bytes("999")
        record = manifest_record("101", other)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.download([record], {record["s3_key"]: other})

    def test_rejects_unsafe_paths(self):
        for path in ("../상의/101.json", "상의/../101.json", "/상의/101.json", "상의\\101.json",
                     "101.json", "하의/101.json", "상의/102.json"):
            with self.subTest(path=path):
                record = manifest_record("101", product_bytes("101"))
                record["path"] = path
                with self.assertRaisesRegex(ValueError, "Unsafe curated product path"):
                    self.download([record], {})

    def test_rejects_keys_outside_run_prefix(self):
        record = manifest_record("101", product_bytes("101"))
        record["s3_key"] = "pipeline/runs/other-run/curated/data/상의/101.json"
        with self.assertRaisesRegex(ValueError, "outside run prefix"):
            self.download([record], {})

    def test_rejects_duplicate_product_ids(self):
        data = product_bytes("101")
        with self.assertRaisesRegex(ValueError, "duplicate product ID"):
            self.download([manifest_record("101", data), manifest_record("101", data, "하의")], {})

    def test_failure_cancels_downloads_not_yet_started(self):
        bodies, records = {}, []
        for product_id in range(101, 121):
            data = product_bytes(str(product_id))
            records.append(manifest_record(str(product_id), data))
            bodies[records[-1]["s3_key"]] = data
        bodies[records[0]["s3_key"]] = b"tampered"
        s3 = fake_run(records, bodies)
        requested = []
        original_get = s3.get_object

        def tracking_get(Bucket, Key):
            requested.append(Key)
            if Key != records[0]["s3_key"] and not Key.endswith("manifest.json"):
                time.sleep(0.05)
            return original_get(Bucket, Key)

        s3.get_object = tracking_get
        with patch("src.jev_job.DOWNLOAD_WORKERS", 1), \
                self.assertRaisesRegex(ValueError, "digest mismatch"):
            download_curated_products(s3, "bucket", PREFIX, Path(tempfile.mkdtemp()) / "data")
        product_requests = [key for key in requested if not key.endswith("manifest.json")]
        self.assertLessEqual(len(product_requests), 2)

    def test_rejects_empty_manifest(self):
        with self.assertRaisesRegex(ValueError, "manifest product list"):
            self.download([], {})


if __name__ == "__main__":
    unittest.main()
