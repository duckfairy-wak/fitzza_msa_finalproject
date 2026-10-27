import json
import tempfile
import unittest
from pathlib import Path

from scripts.render_product_image_s3_key_update import load_all_manifests, render_sql


class ProductImageS3KeyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images" / "products" / "123"
        self.images.mkdir(parents=True)
        (self.images / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "product_id": "123",
                    "images": [
                        {
                            "kind": "product",
                            "source_url": "https://cdn.example/a.jpg",
                            "s3_key": "pipeline/runs/x/images/products/123/001.jpg",
                        },
                        {
                            "kind": "product",
                            "source_url": "https://cdn.example/b.jpg",
                            "s3_key": "pipeline/runs/x/images/products/123/002.jpg",
                        },
                        {
                            "kind": "size-guide",
                            "source_url": "https://cdn.example/guide.png",
                            "s3_key": "pipeline/runs/x/images/products/123/003.png",
                        },
                        {
                            "kind": "color",
                            "source_url": "https://cdn.example/black.jpg",
                            "s3_key": "pipeline/runs/x/images/products/123/004.webp",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_renders_object_key_remap_sql(self) -> None:
        manifests = load_all_manifests(self.root / "images" / "products")
        sql = render_sql(manifests, [(123, '[{"productId":123,"colorRaw":"블랙","imageUrl":"pipeline/runs/x/images/products/123/004.webp"}]')], run_id="x")
        self.assertIn("pipeline/runs/x/images/products/123/001.jpg", sql)
        self.assertIn("UPDATE product_service.product AS p", sql)
        self.assertIn("ON COMMIT DROP", sql)
        self.assertIn("COMMIT;", sql)


if __name__ == "__main__":
    unittest.main()
