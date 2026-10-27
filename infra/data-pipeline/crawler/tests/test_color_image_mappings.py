from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.color_image_mappings import (
    extract_color_image_mappings,
    extract_accessory_image_fallback,
    product_image_url,
)
from src.musinsa_parser import normalize_musinsa_product
from src.curate_dataset import validate_product
from src.collector.batch_crawler import BatchProductCrawler


def options_fixture():
    # Shape observed in saved product_20261002_134748.html (no live requests).
    return {"basic": [{"no": 10, "displayType": "COLOR_CHIP", "name": "컬러",
        "optionValues": [{"no": 20, "optionNo": 10, "name": "블랙_기모",
            "imageUrl": "https://image.msscdn.net/thumbnails/images/2026/09/02/black.jpg"}]}],
        "optionItems": [{"no": 30, "goodsNo": 123, "activated": True,
            "optionValueNos": [20, 21], "optionValues": [
                {"no": 20, "optionNo": 10, "name": "블랙_기모"},
                {"no": 21, "optionNo": 11, "name": "M"}]}]}


class ColorImageMappingTests(unittest.TestCase):
    def test_shoe_single_color_uses_primary_image(self):
        options = options_fixture()
        options["basic"][0]["displayType"] = "DROPDOWN"
        options["basic"][0]["optionValues"][0]["imageUrl"] = None
        mappings = extract_accessory_image_fallback(
            123, options, ["https://image.msscdn.net/images/shoe.jpg"]
        )
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["color_raw"], "블랙_기모")
        self.assertEqual(mappings[0]["color_status"], "declared_single_option")

    def test_shoe_without_color_keeps_unspecified_primary_image(self):
        mappings = extract_accessory_image_fallback(
            123,
            {"basic": [], "optionItems": []},
            ["https://image.msscdn.net/images/shoe.jpg"],
        )
        self.assertEqual(len(mappings), 1)
        self.assertIsNone(mappings[0]["color_raw"])
        self.assertEqual(mappings[0]["color_status"], "unspecified")

    def test_shoe_multiple_colors_without_images_remains_rejected(self):
        options = options_fixture()
        options["basic"][0]["displayType"] = "DROPDOWN"
        second = deepcopy(options["basic"][0]["optionValues"][0])
        second.update(no=22, name="화이트", imageUrl=None)
        options["basic"][0]["optionValues"].append(second)
        options["optionItems"][0]["optionValueNos"].append(22)
        options["optionItems"][0]["optionValues"].append(
            {"no": 22, "optionNo": 10, "name": "화이트"}
        )
        self.assertEqual(extract_accessory_image_fallback(
            123, options, ["https://image.msscdn.net/images/shoe.jpg"]
        ), [])

    def test_explicit_mapping_preserves_raw_and_evidence(self):
        options = options_fixture()
        before = deepcopy(options)
        mappings = extract_color_image_mappings(123, options)
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["product_id"], 123)
        self.assertEqual(mappings[0]["color_raw"], "블랙_기모")
        self.assertEqual(mappings[0]["source_option_value_id"], 20)
        self.assertEqual(mappings[0]["evidence"], "Options.basic.COLOR_CHIP.imageUrl")
        self.assertEqual(options, before)

    def test_foreign_deleted_inactive_or_unlinked_option_rejected(self):
        for field, value in (("goodsNo", 999), ("goodsNo", "123"), ("activated", False),
                             ("isDeleted", True), ("optionValueNos", [21])):
            options = options_fixture()
            options["optionItems"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(extract_color_image_mappings(123, options), [])

    def test_deleted_group_or_value_and_size_group_rejected(self):
        for location in ("group", "value", "size"):
            options = options_fixture()
            if location == "group":
                options["basic"][0]["isDeleted"] = True
            elif location == "value":
                options["basic"][0]["optionValues"][0]["isDeleted"] = True
            else:
                options["basic"][0]["displayType"] = "DROPDOWN"
            self.assertEqual(extract_color_image_mappings(123, options), [])

    def test_generic_swatches_missing_image_and_unapproved_hosts_rejected(self):
        for url in (None, "", "https://image.msscdn.net/images/color_image/color/black.png",
                    "http://image.msscdn.net/a.jpg", "https://localhost/a.jpg",
                    "https://user:secret@image.msscdn.net/a.jpg", "https://image.msscdn.net:99999/a"):
            with self.subTest(url=url):
                self.assertIsNone(product_image_url(url))
        self.assertEqual(product_image_url("/images/a.jpg"), "https://image.msscdn.net/images/a.jpg")
        self.assertEqual(product_image_url("//image.msscdn.net/a.jpg"), "https://image.msscdn.net/a.jpg")

    def test_duplicate_mapping_collapsed_and_shared_placeholder_rejected(self):
        options = options_fixture()
        options["basic"][0]["optionValues"].append(deepcopy(options["basic"][0]["optionValues"][0]))
        self.assertEqual(len(extract_color_image_mappings(123, options)), 1)
        options["basic"][0]["optionValues"][-1]["name"] = "WHITE"
        self.assertEqual(extract_color_image_mappings(123, options), [])

    def test_multiple_color_dimensions_require_explicit_combination(self):
        options = options_fixture()
        options["basic"].append(deepcopy(options["basic"][0]))
        self.assertEqual(extract_color_image_mappings(123, options), [])

    def test_name_and_thumbnail_never_used_as_fallback(self):
        self.assertEqual(extract_color_image_mappings(123, {"basic": [], "optionItems": [],
            "goodsNm": "BLACK SHIRT", "thumbnailImageUrl": "https://image.msscdn.net/123.jpg"}), [])

    def test_parser_to_curated_contract_offline(self):
        detail = {"goodsNo": 123, "goodsNm": "상품", "sex": ["남성"],
                  "category": {"categoryDepth1Name": "상의"}}
        queries = [{"queryKey": key, "state": {"data": {"data": data}}}
                   for key, data in ((["Detail", 123], detail), (["Options", 123], options_fixture()))]
        payload = {"props": {"pageProps": {"dehydratedState": {"queries": queries}}}}
        html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + '</script>'
        product = normalize_musinsa_product(html, "https://www.musinsa.com/products/123")
        product["size"] = {"available": True, "unit": "cm", "measurements": [
            {"size": "M", "measurements": {"총장": 70}}]}
        self.assertEqual(validate_product(product), ("123", "상의"))
        detail["goodsNo"] = 999
        payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["data"] = detail
        html = '<script id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'
        with self.assertRaisesRegex(ValueError, "identity"):
            normalize_musinsa_product(html, "https://www.musinsa.com/products/123")


class CrawlerProductIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_redirected_product_cannot_be_assigned_to_requested_id(self):
        crawler = BatchProductCrawler(None)
        crawler.page = Mock(goto=AsyncMock(return_value=Mock(status=200)),
                            wait_for_timeout=AsyncMock(), content=AsyncMock(return_value="fixture"))
        with patch("src.collector.batch_crawler.normalize_musinsa_product", return_value={"product_id": 999}):
            with self.assertRaisesRegex(ValueError, "identity"):
                await crawler.fetch_basic_product(123)


if __name__ == "__main__":
    unittest.main()
