import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from src.cloud_media import ImageSourceError, upload_product_images, upload_reviews


class CloudMediaTests(unittest.TestCase):
    @patch("src.cloud_media.time.sleep")
    @patch("src.cloud_media.put_json")
    @patch("src.cloud_media.object_exists", return_value=False)
    @patch("src.cloud_media.upload_image")
    def test_product_source_failure_is_recorded_and_next_image_continues(
        self, upload_image, _object_exists, put_json, _sleep
    ):
        upload_image.side_effect = [
            ImageSourceError("HTTP 404"),
            {"source_url": "https://image.msscdn.net/ok.jpg", "s3_key": "ok"},
        ]
        product = {"product_id": 123, "images": [
            "https://image.msscdn.net/missing.jpg",
            "https://image.msscdn.net/ok.jpg",
        ]}

        result = upload_product_images(Mock(), "bucket", "prefix", product)

        self.assertEqual(result["image_count"], 1)
        self.assertEqual(put_json.call_count, 2)
        audit = put_json.call_args_list[0].args[3]
        manifest = put_json.call_args_list[1].args[3]
        self.assertEqual(audit["failures"][0]["error"], "HTTP 404")
        self.assertEqual(set(manifest), {
            "schema_version", "product_id", "downloaded_at", "image_count", "images"
        })

    @patch("src.cloud_media.time.sleep")
    @patch("src.cloud_media.put_json")
    @patch("src.cloud_media.object_exists", return_value=False)
    @patch("src.cloud_media.upload_image", side_effect=ImageSourceError("HTTP 404"))
    def test_product_with_only_missing_images_writes_audit_and_contract_manifest(
        self, _upload_image, _object_exists, put_json, _sleep
    ):
        product = {"product_id": 123,
                   "images": ["https://image.msscdn.net/missing.jpg"]}

        result = upload_product_images(Mock(), "bucket", "prefix", product)

        self.assertEqual(result["image_count"], 0)
        self.assertEqual(put_json.call_count, 2)

    @patch("src.cloud_media.object_exists", return_value=False)
    @patch("src.cloud_media.upload_image")
    def test_product_s3_error_is_not_suppressed(self, upload_image, _object_exists):
        upload_image.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
        )
        product = {"product_id": 123,
                   "images": ["https://image.msscdn.net/image.jpg"]}

        with self.assertRaises(ClientError):
            upload_product_images(Mock(), "bucket", "prefix", product)

    @patch("src.cloud_media.put_json")
    @patch("src.cloud_media.object_exists", return_value=False)
    @patch("src.cloud_media.fetch_review_page")
    @patch("src.cloud_media.upload_image")
    def test_review_images_are_not_downloaded_and_contract_is_unchanged(
        self, upload_image, fetch_review_page, _object_exists, put_json
    ):
        fetch_review_page.return_value = {"data": {"total": 1,
            "page": {"totalPages": 1}, "list": [{"no": 9, "images": [
                {"image": "https://image.msscdn.net/missing.jpg"},
                {"image": "https://image.msscdn.net/ok.jpg"},
            ]}]}}
        result = upload_reviews(Mock(), "bucket", "prefix", "123")

        self.assertEqual(result["image_count"], 0)
        upload_image.assert_not_called()
        saved = put_json.call_args.args[3]
        self.assertEqual(set(saved), {"schema_version", "source", "product_id",
            "collected_at", "reported_review_count", "collected_review_count",
            "truncated", "downloaded_review_image_count", "reviews"})
        self.assertEqual(saved["reviews"][0]["image_files"], [])
        self.assertNotIn("image_failures", saved["reviews"][0])


if __name__ == "__main__":
    unittest.main()
