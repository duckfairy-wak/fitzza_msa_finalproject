import json
import tempfile
import unittest
from pathlib import Path

from scripts.render_crawled_product_import import load_bundle, render_sql, verify_status


class CrawledProductImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "curated" / "data" / "top"
        self.data.mkdir(parents=True)
        self.images = self.root / "images" / "products" / "123"
        self.images.mkdir(parents=True)
        (self.images / "01.jpg").write_bytes(b"fake")
        (self.images / "02.jpg").write_bytes(b"fake")
        self.failures = self.root / "audit" / "image-download-failures" / "products"
        self.failures.mkdir(parents=True)
        (self.failures / "999.json").write_text("{}", encoding="utf-8")
        self.status = self.root / "status.json"
        self.status.write_text(
            json.dumps({"state": "succeeded", "product_count": 1}),
            encoding="utf-8",
        )
        self.write_product()

    def write_product(self) -> None:
        document = {
            "source": "musinsa",
            "source_url": "https://www.musinsa.com/products/123",
            "product_id": 123,
            "name": "테스트 셔츠",
            "name_en": "TEST SHIRT",
            "style_no": "T-1",
            "gender": {"normalized": "MALE"},
            "brand": {"id": "brand-a", "name": "브랜드A", "name_en": "BrandA"},
            "category": {
                "categoryDepth1Code": "001",
                "categoryDepth1Name": "상의",
                "categoryDepth2Code": "001002",
                "categoryDepth2Name": "셔츠",
            },
            "season": {"primary": "여름"},
            "price": {"normal": 10000, "sale": 8000, "discount_rate": 20},
            "images": ["https://image.example/old.jpg"],
            "material": "면 100%",
            "fit_type": "RELAXED",
            "features": {"핏": ["루즈"]},
            "color_image_mappings": [
                {"product_id": 123, "color_raw": "블랙", "image_url": "https://image.example/black.jpg"}
            ],
            "size": {
                "type_name": "셔츠",
                "unit": "cm",
                "description": "오차 있음",
                "guide_image": "https://image.example/guide.png",
                "measurements": [{"size": "M", "sequence": 1, "measurements": {"총장": 70.0}}],
            },
            "options": [{"name": "컬러"}, {"name": "사이즈"}],
            "option_items": [
                {
                    "id": 9001,
                    "managed_code": "BLACK-M",
                    "price_delta": 0,
                    "activated": True,
                    "values": ["블랙", "M"],
                }
            ],
        }
        (self.data / "123.json").write_text(json.dumps(document), encoding="utf-8")

    def test_status_requires_succeeded(self) -> None:
        bad = self.root / "bad-status.json"
        bad.write_text(json.dumps({"state": "failed", "product_count": 1}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "succeeded"):
            verify_status(bad, expected_count=1)

    def test_prefers_s3_object_keys_when_inventory_present(self) -> None:
        bundle = load_bundle(
            data_root=self.root / "curated" / "data",
            status_path=self.status,
            manifest_path=None,
            images_root=self.root / "images" / "products",
            failures_root=self.failures,
            image_key_prefix="pipeline/runs/collection-20261025-01/images/products",
            image_public_base_url="https://cdn.example",
            expected_count=1,
            skip_invalid=False,
        )
        self.assertEqual(len(bundle.products), 1)
        self.assertEqual(len(bundle.images), 2)
        self.assertTrue(bundle.images[0].image_url.startswith("https://cdn.example/pipeline/runs/"))
        self.assertEqual(bundle.image_failure_files, 1)
        sql = render_sql(bundle, run_id="collection-20261025-01")
        self.assertIn("CREATE TEMP TABLE crawled_product", sql)
        self.assertIn("ON CONFLICT (product_id) DO UPDATE", sql)
        self.assertIn("ON CONFLICT (source_option_id) DO UPDATE", sql)
        self.assertIn("9001", sql)
        self.assertIn("COMMIT;", sql)

    def test_falls_back_to_json_images_without_inventory(self) -> None:
        bundle = load_bundle(
            data_root=self.root / "curated" / "data",
            status_path=None,
            manifest_path=None,
            images_root=None,
            failures_root=None,
            image_key_prefix="pipeline/runs/x/images/products",
            image_public_base_url=None,
            expected_count=None,
            skip_invalid=False,
        )
        self.assertEqual(bundle.images[0].image_url, "https://image.example/old.jpg")


if __name__ == "__main__":
    unittest.main()
