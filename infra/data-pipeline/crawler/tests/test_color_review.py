import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from src import color_review
from src.review_gate import approve, fingerprint, verify


class ColorReviewTests(unittest.TestCase):
    def bundle(self, root, products=None):
        (root / "data/top").mkdir(parents=True)
        (root / "config").mkdir()
        products = products or [(1, ["BK", "라벤더"]), (2, ["차콜", "화이트/블루"])]
        for product_id, colors in products:
            (root / f"data/top/{product_id}.json").write_text(json.dumps({
                "product_id": product_id, "name": f"상품{product_id}",
                "color_image_mappings": [{"color_raw": c, "image_url": f"https://img/{product_id}{i}.jpg"}
                                         for i, c in enumerate(colors)]}, ensure_ascii=False), encoding="utf-8")
        (root / "config/color_map.json").write_text(json.dumps(
            {"bk": "black", "라벤더": "etc", "차콜": "charcoal", "화이트/블루": "multi"}, ensure_ascii=False), encoding="utf-8")
        (root / "config/color_map_review.csv").write_text("color_raw,Jev 선택\n라벤더,purple\n", encoding="utf-8")
        (root / "config/color_map_overrides.json").write_text('{"BK": "black", "NA": "navy", "_note": "x"}',
                                                              encoding="utf-8")
        (root / "config/color_map_jev_results.jsonl").write_text(json.dumps(
            {"key": "라벤더", "raw": "라벤더", "choice": "purple", "confidence": 0.4, "top3": [["purple", 0.4]]},
            ensure_ascii=False) + "\n", encoding="utf-8")

    def decisions(self, root, values):
        path = root.parent / f"{root.name}-decisions.json"
        path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        return path

    def test_page_lists_exactly_what_the_gate_requires(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bundle"
            root.mkdir()
            self.bundle(root)
            page = color_review.build_page(root).read_text(encoding="utf-8")
            data = json.loads(page.split("const ITEMS=", 1)[1].split(", COLORS=", 1)[0])
            self.assertEqual({item["key"] for item in data}, {"라벤더", "bk", "화이트/블루"})
            self.assertFalse((root / "config/reviewed_colors.json").exists())

    def test_applied_decisions_pass_the_review_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bundle"
            root.mkdir()
            self.bundle(root)
            changed = color_review.apply_decisions(
                root, self.decisions(root, {"라벤더": "purple", "BK": "black", "화이트/블루": "multi"}))
            self.assertEqual(changed, {"라벤더": ("etc", "purple")})
            approve(root)
            verify(root)

    def test_incomplete_or_invalid_decisions_change_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bundle"
            root.mkdir()
            self.bundle(root)
            before = (root / "config/color_map.json").read_text(encoding="utf-8")
            for values in ({"라벤더": "purple"}, {"라벤더": "violet", "bk": "black", "화이트/블루": "multi"},
                           {"라벤더": "purple", "bk": "black", "화이트/블루": "multi", "없는색": "red"}):
                with self.assertRaises(ValueError):
                    color_review.apply_decisions(root, self.decisions(root, values))
            self.assertEqual((root / "config/color_map.json").read_text(encoding="utf-8"), before)
            self.assertFalse((root / "config/reviewed_colors.json").exists())

    def approved(self, root):
        self.bundle(root)
        color_review.apply_decisions(root, self.decisions(root, {"라벤더": "purple", "bk": "black", "화이트/블루": "multi"}))
        approve(root)

    def test_package_rebuilds_the_same_approved_bundle(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(color_review, "EXPECTED_PRODUCTS", 2):
            root = Path(folder) / "bundle"
            root.mkdir()
            self.approved(root)
            (root.parent / "bundle-color-review.html").write_text("page", encoding="utf-8")
            output = Path(folder) / "approved.tar.gz"
            summary = color_review.package(root, output, require_quality=False)
            self.assertFalse(summary["quality_approved"])
            with tarfile.open(output, "r:gz") as archive:
                names = archive.getnames()
            self.assertTrue(all(name.split("/")[0] in ("config", "data") for name in names))
            unpacked = Path(folder) / "unpacked"
            color_review.unpack_like_indexer(output, unpacked)
            verify(unpacked)
            second = Path(folder) / "again.tar.gz"
            color_review.package(root, second, require_quality=False)
            self.assertEqual(output.read_bytes(), second.read_bytes())

    def test_final_package_requires_pinned_quality_approval(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(color_review, "EXPECTED_PRODUCTS", 2):
            root = Path(folder) / "bundle"
            root.mkdir()
            self.approved(root)
            with self.assertRaisesRegex(ValueError, "품질 승인"):
                color_review.package(root, Path(folder) / "a.tar.gz", require_quality=True)
            quality = {"approved": True, "files": fingerprint(root)["files"], "model_revision": "short"}
            (root / "config/_QUALITY_APPROVED.json").write_text(json.dumps(quality), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "commit SHA"):
                color_review.package(root, Path(folder) / "b.tar.gz", require_quality=True)
            quality["model_revision"] = "a" * 40
            (root / "config/_QUALITY_APPROVED.json").write_text(json.dumps(quality), encoding="utf-8")
            self.assertTrue(color_review.package(root, Path(folder) / "c.tar.gz", require_quality=True)["quality_approved"])

    def test_package_refuses_the_wrong_product_count(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "bundle"
            root.mkdir()
            self.approved(root)
            with self.assertRaisesRegex(ValueError, "3000"):
                color_review.package(root, Path(folder) / "a.tar.gz", require_quality=False)

    def test_changed_bundle_after_approval_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(color_review, "EXPECTED_PRODUCTS", 2):
            root = Path(folder) / "bundle"
            root.mkdir()
            self.approved(root)
            (root / "config/color_map.json").write_text(
                json.dumps({"bk": "black", "라벤더": "pink", "차콜": "charcoal", "화이트/블루": "multi"}, ensure_ascii=False),
                encoding="utf-8")
            with self.assertRaises(ValueError):
                color_review.package(root, Path(folder) / "a.tar.gz", require_quality=False)


if __name__ == "__main__":
    unittest.main()
