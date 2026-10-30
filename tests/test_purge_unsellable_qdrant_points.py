from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import MagicMock

from scripts.purge_unsellable_qdrant_points import (
    extract_sellable_colors,
    build_sellable_colors_map,
    scan_and_purge_unsellable_points,
)


class PurgeUnsellableQdrantPointsTests(unittest.TestCase):
    def test_extract_sellable_colors_filters_inactive(self):
        product = {
            "product_id": 2837412,
            "options": [{"name": "컬러", "values": []}, {"name": "사이즈", "values": []}],
            "option_items": [
                {"activated": True, "values": ["BEIGE", "FREE"]},
                {"activated": True, "values": ["BLACK", "FREE"]},
                {"activated": False, "values": ["PURPLE", "FREE"]},
            ],
        }
        sellable = extract_sellable_colors(product)
        self.assertEqual(sellable, {"beige", "black"})
        self.assertNotIn("purple", sellable)
        self.assertNotIn("red", sellable)

    def test_build_sellable_colors_map(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)
            p1 = {
                "product_id": 1001,
                "options": [{"name": "색상"}],
                "option_items": [{"activated": True, "values": ["NAVY", "L"]}],
            }
            p2 = {
                "product_id": 1002,
                "options": [{"name": "COLOR"}],
                "option_items": [{"activated": True, "values": ["WHITE", "M"]}],
            }
            (dir_path / "1001.json").write_text(json.dumps(p1), encoding="utf-8")
            (dir_path / "1002.json").write_text(json.dumps(p2), encoding="utf-8")

            res = build_sellable_colors_map(dir_path)
            self.assertEqual(res[1001], {"navy"})
            self.assertEqual(res[1002], {"white"})

    def test_scan_and_purge_dry_run_does_not_call_delete(self):
        mock_client = MagicMock()
        mock_point_valid = MagicMock()
        mock_point_valid.id = "p-1"
        mock_point_valid.payload = {"product_id": 2837412, "color_raw": "BEIGE"}

        mock_point_invalid = MagicMock()
        mock_point_invalid.id = "p-2"
        mock_point_invalid.payload = {"product_id": 2837412, "color_raw": "RED"}

        mock_client.scroll.return_value = ([mock_point_valid, mock_point_invalid], None)

        sellable_map = {2837412: {"beige", "black"}}
        result = scan_and_purge_unsellable_points(
            client=mock_client,
            collection_name="test_col",
            sellable_map=sellable_map,
            dry_run=True,
        )

        self.assertEqual(result["total_scanned"], 2)
        self.assertEqual(result["unsellable_found"], 1)
        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["details"][0]["point_id"], "p-2")
        mock_client.delete.assert_not_called()

    def test_scan_and_purge_live_calls_delete(self):
        mock_client = MagicMock()
        mock_point_invalid = MagicMock()
        mock_point_invalid.id = "p-red"
        mock_point_invalid.payload = {"product_id": 2837412, "color_raw": "RED"}

        mock_client.scroll.return_value = ([mock_point_invalid], None)

        sellable_map = {2837412: {"beige", "black"}}
        result = scan_and_purge_unsellable_points(
            client=mock_client,
            collection_name="test_col",
            sellable_map=sellable_map,
            dry_run=False,
        )

        self.assertEqual(result["deleted_count"], 1)
        mock_client.delete.assert_called_once()

    def test_build_sellable_colors_map_skips_when_no_intersection(self):
        """사이즈 옵션만 있어 sellable이 {"s", "m"}인데 mapping_colors는 {"black"}인 경우,
        오삭제를 방지하기 위해 sellable_map에서 제외되어야 한다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)
            p = {
                "product_id": 2001,
                "options": [{"name": "사이즈"}],
                "option_items": [
                    {"activated": True, "values": ["S"]},
                    {"activated": True, "values": ["M"]},
                ],
                "color_image_mappings": [
                    {"product_id": 2001, "color_raw": "BLACK", "image_url": "https://img.com/black.jpg"}
                ],
            }
            (dir_path / "2001.json").write_text(json.dumps(p), encoding="utf-8")
            res = build_sellable_colors_map(dir_path)
            self.assertNotIn(2001, res)
