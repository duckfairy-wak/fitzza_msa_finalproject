from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

from src.curate_dataset import (
    external_product_contract,
    prepare,
    select_products,
    validate_product,
    write_bundle,
)
from src.cloud_curate import main, curate, restore_product
from src.collector.rules import has_required_size
from src.musinsa_size import normalize_accessory_option_size


def product(identifier=1, category="상의"):
    return {"product_id": identifier, "gender": {"normalized": "UNISEX"},
            "category": {"categoryDepth1Name": category},
            "season": {"original": ["봄", "여름", "가을", "겨울"]},
            "size": {"available": True, "unit": "cm", "measurements": [
                {"size": "M", "measurements": {"총장": 70}}]},
            "color_image_mappings": [{"product_id": identifier, "color_raw": "BK",
                "image_url": "https://image.msscdn.net/images/1.jpg", "evidence": "fixture"}]}


class CurateTests(unittest.TestCase):
    def test_valid_contract(self):
        self.assertEqual(validate_product(product()), ("1", "상의"))

    def test_shoe_sales_options_are_valid_size_fallback(self):
        item = product(category="신발")
        item["size"] = normalize_accessory_option_size({"options": [{
            "name": "사이즈",
            "values": [
                {"name": "250", "code": "250"},
                {"name": "260", "code": "260"},
            ],
        }]})
        self.assertTrue(has_required_size(item, "신발"))
        self.assertEqual(item["size"]["source"], "sales_option")
        self.assertEqual(item["size"]["unit"], "mm")
        self.assertEqual(validate_product(item), ("1", "신발"))

    def test_shoe_unspecified_color_primary_image_is_valid(self):
        item = product(category="신발")
        item["size"]["measurements"][0]["measurements"] = {"발길이": 25}
        item["color_image_mappings"] = [{
            "product_id": 1,
            "color_raw": None,
            "color_status": "unspecified",
            "image_url": "https://image.msscdn.net/images/shoe.jpg",
            "evidence": "Detail.primaryImage.colorUnspecified",
        }]
        self.assertEqual(validate_product(item), ("1", "신발"))

        item["category"]["categoryDepth1Name"] = "상의"
        item["size"]["measurements"][0]["measurements"] = {"총장": 70}
        with self.assertRaisesRegex(ValueError, "invalid_color"):
            validate_product(item)

    def test_hat_sales_size_and_unspecified_image_are_valid(self):
        item = product(category="모자")
        item["size"] = normalize_accessory_option_size({"options": [{
            "name": "사이즈",
            "values": [{"name": "FREE", "code": "FREE"}],
        }]})
        item["color_image_mappings"] = [{
            "product_id": 1,
            "color_raw": None,
            "color_status": "unspecified",
            "image_url": "https://image.msscdn.net/images/hat.jpg",
            "evidence": "Detail.primaryImage.colorUnspecified",
        }]
        self.assertTrue(has_required_size(item, "모자"))
        self.assertEqual(validate_product(item), ("1", "모자"))

        external = external_product_contract(item)
        self.assertNotIn("source", external["size"])
        self.assertNotIn("options", external["size"])
        self.assertEqual(external["size"]["measurements"], [{
            "size": "FREE", "sequence": 1, "measurements": {}
        }])
        mapping = external["color_image_mappings"][0]
        self.assertEqual(mapping["color_raw"], "미지정")
        self.assertNotIn("color_status", mapping)

    def test_sales_options_do_not_replace_apparel_measurements(self):
        item = product(category="상의")
        item["size"] = normalize_accessory_option_size({"options": [{
            "name": "SIZE",
            "values": [{"name": "M", "code": "M"}],
        }]})
        self.assertFalse(has_required_size(item, "상의"))
        with self.assertRaisesRegex(ValueError, "actual_size_missing"):
            validate_product(item)

    def test_missing_color_mapping_is_not_guessed(self):
        item = product()
        del item["color_image_mappings"]
        with self.assertRaisesRegex(ValueError, "mappings_missing"):
            validate_product(item)

    def test_mapping_must_belong_to_product(self):
        item = product()
        item["color_image_mappings"][0]["product_id"] = 2
        with self.assertRaisesRegex(ValueError, "evidence_missing"):
            validate_product(item)

    def test_reject_invalid_measurements(self):
        for value in (0, -1, True, float("inf"), float("nan"), "70"):
            item = product()
            item["size"]["measurements"][0]["measurements"]["총장"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_product(item)

    def test_wrong_gender_category_or_unit(self):
        for field, value in (("gender", {"normalized": "FEMALE_ONLY"}),
                             ("dataset", {"logical_category": "하의"}),
                             ("size", {"available": True, "unit": "inch", "measurements": [{}]})):
            item = product()
            item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_product(item)

    def test_unapproved_or_credentialed_url(self):
        for url in ("http://image.msscdn.net/a", "https://localhost/a",
                    "https://user:password@image.msscdn.net/a", "https://image.msscdn.net:8443/a"):
            item = product()
            item["color_image_mappings"][0]["image_url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_product(item)

    def test_duplicate_mapping(self):
        item = product()
        item["color_image_mappings"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_product(item)

    def test_no_automatic_approval_or_partial_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.json").write_text(json.dumps(product()), encoding="utf-8")
            report, files = prepare([root])
            self.assertFalse(report["ready_for_jev"])
            self.assertFalse(report["approved_for_indexing"])
            self.assertFalse(report["image_contents_verified"])
            with self.assertRaises(ValueError):
                write_bundle(root / "bundle.tar.gz", report, files)
            self.assertFalse((root / "bundle.tar.gz").exists())

    def test_duplicate_product_across_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.json").write_text(json.dumps(product()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                prepare([root, root])

    def test_selection_obeys_season_quota_without_mutating_input(self):
        config = {"total_quota": 4, "season_quota": dict.fromkeys(["봄", "여름", "가을", "겨울"], 1)}
        items = [product(index) for index in range(1, 7)]
        before = deepcopy(items)
        with patch.dict("src.curate_dataset.CATEGORY_CONFIG", {"상의": config}):
            selected = select_products(items, "상의")
        self.assertEqual(len(selected), 4)
        self.assertEqual({item["season"]["primary"] for item in selected}, set(config["season_quota"]))
        self.assertEqual(items, before)

    def test_bundle_has_jev_layout_and_no_approval_markers(self):
        config = {"total_quota": 1, "season_balance_required": False}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1.json").write_text(json.dumps(product()), encoding="utf-8")
            with patch("src.curate_dataset.CATEGORY_CONFIG", {"상의": config}):
                report, files = prepare([root])
            archive = root / "bundle.tar.gz"
            write_bundle(archive, report, files)
            with tarfile.open(archive) as bundle:
                self.assertEqual(set(bundle.getnames()), {"data/상의/1.json", "config/curation_report.json"})
            with self.assertRaises(FileExistsError):
                write_bundle(archive, report, files)

    def test_changed_data_blocks_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "changed"):
                write_bundle(Path(folder) / "x.tar.gz",
                             {"ready_for_jev": True, "files": {}}, {"data/1.json": b"{}"})

    def test_deployment_mode_has_no_aws_calls(self):
        with patch("sys.argv", ["cloud_curate", "--bucket", "unused", "--run-id", "test"]), \
                patch("boto3.client") as client:
            main()
            client.assert_not_called()

    def test_digest_mismatch_never_writes_file(self):
        client = Mock()
        client.get_object.return_value = {"Body": io.BytesIO(b"wrong")}
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "1.json"
            with self.assertRaises(ValueError):
                restore_product(client, "bucket", "key", "0" * 64, destination)
            self.assertFalse(destination.exists())

    def test_incomplete_cloud_input_does_not_publish(self):
        item = json.dumps(product()).encode()
        digest = hashlib.sha256(item).hexdigest()
        client = Mock()
        values = {"seed/manifest.json": json.dumps({"products": [
            {"product_id": "1", "sha256": digest}]}).encode(),
            f"seed/objects/{digest}": item,
            "crawler/checkpoints.json": b'{"files":{}}'}
        client.get_object.side_effect = lambda **kw: {"Body": io.BytesIO(
            values[kw["Key"].split("pipeline/runs/test/")[1]])}
        with tempfile.TemporaryDirectory() as folder:
            report = curate(client, "bucket", "test", Path(folder))
        self.assertFalse(report["ready_for_jev"])
        client.put_object.assert_not_called()

    def test_three_thousand_products_reach_jev_bundle_but_not_indexing_approval(self):
        targets = {"상의": 900, "하의": 750, "신발": 600, "아우터": 450, "모자": 300}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            identifier = 0
            for category, count in targets.items():
                for _ in range(count):
                    identifier += 1
                    item = product(identifier, category)
                    measurement = {"신발": "발길이", "모자": "머리둘레"}.get(category, "총장")
                    item["size"]["measurements"][0]["measurements"] = {measurement: 50}
                    (root / f"{identifier}.json").write_text(json.dumps(item), encoding="utf-8")
            report, files = prepare([root])
            self.assertTrue(report["ready_for_jev"])
            self.assertEqual(report["selected_count"], 3000)
            self.assertEqual(report["selected_by_category"], targets)
            self.assertFalse(report["approved_for_indexing"])
            archive = root / "bundle.tar.gz"
            write_bundle(archive, report, files)
            with tarfile.open(archive) as bundle:
                self.assertEqual(len(bundle.getnames()), 3001)
                self.assertFalse(any("APPROVED" in name for name in bundle.getnames()))

    def test_successful_cloud_publish_is_create_only(self):
        item = json.dumps(product()).encode()
        digest = hashlib.sha256(item).hexdigest()
        client = Mock()
        values = {"seed/manifest.json": json.dumps({"products": [
            {"product_id": "1", "sha256": digest}]}).encode(),
            f"seed/objects/{digest}": item,
            "crawler/checkpoints.json": b'{"files":{}}'}
        client.get_object.side_effect = lambda **kw: {"Body": io.BytesIO(
            values[kw["Key"].split("pipeline/runs/test/")[1]])}
        config = {"total_quota": 1, "season_balance_required": False}
        with tempfile.TemporaryDirectory() as folder, \
                patch("src.curate_dataset.CATEGORY_CONFIG", {"상의": config}):
            report = curate(client, "bucket", "test", Path(folder))
        self.assertTrue(report["ready_for_jev"])
        self.assertEqual(client.put_object.call_args.kwargs["IfNoneMatch"], "*")
        self.assertEqual(client.put_object.call_args.kwargs["Key"],
                         "pipeline/runs/test/curated/bundle.tar.gz")

    def test_unsafe_checkpoint_does_not_publish(self):
        item = json.dumps(product()).encode()
        digest = hashlib.sha256(item).hexdigest()
        client = Mock()
        client.get_object.side_effect = [
            {"Body": io.BytesIO(json.dumps({"products": [
                {"product_id": "1", "sha256": digest}]}).encode())},
            {"Body": io.BytesIO(item)},
            {"Body": io.BytesIO(b'{"files":{"data/../../escape.json":"bad"}}')}]
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, "Unsafe"):
            curate(client, "bucket", "test", Path(folder))
        client.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
