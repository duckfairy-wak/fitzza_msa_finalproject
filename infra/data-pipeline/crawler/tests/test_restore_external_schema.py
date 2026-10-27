import unittest

from src.restore_external_schema import (
    restore_product_image_manifest,
    restore_review_document,
    restore_status_document,
)


class RestoreExternalSchemaTests(unittest.TestCase):
    def test_product_image_failures_move_out_of_manifest(self):
        document = {"schema_version": 1, "product_id": "1", "image_count": 0,
            "images": [], "failed_image_count": 1,
            "failures": [{"error": "HTTP 404"}]}

        restored, failures = restore_product_image_manifest(document)

        self.assertEqual(failures, [{"error": "HTTP 404"}])
        self.assertNotIn("failed_image_count", restored)
        self.assertNotIn("failures", restored)

    def test_review_failure_fields_are_removed(self):
        document = {"schema_version": 1, "failed_review_image_count": 0,
            "reviews": [{"source_review_id": 1, "image_files": [],
                         "image_failures": []}]}

        restored = restore_review_document(document)

        self.assertNotIn("failed_review_image_count", restored)
        self.assertNotIn("image_failures", restored["reviews"][0])
        self.assertEqual(restored["reviews"][0]["image_files"], [])

    def test_status_failure_fields_are_removed(self):
        restored = restore_status_document({"schema_version": 1,
            "product_image_failures_this_run": 64,
            "review_image_failures_this_run": 0,
            "product_count": 3000})

        self.assertEqual(restored, {"schema_version": 1, "product_count": 3000})


if __name__ == "__main__":
    unittest.main()
