import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_jev_data import ContractError, validate_jev_data


class ValidateJevDataTest(unittest.TestCase):
    def test_matches_jev_normalized_color_keys(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self._write(root / "1.json", [" BLACK ", "Ivory"])
            self._write(root / "2.json", ["black"])

            result = validate_jev_data(root)

            self.assertEqual(result["source_product_count"], 2)
            self.assertEqual(result["products_with_colors"], 2)
            self.assertEqual(result["unique_color_count"], 2)

    def test_does_not_require_image_url(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self._write(root / "1.json", ["navy"])
            self.assertEqual(validate_jev_data(root)["unique_color_count"], 1)

    def test_rejects_invalid_mapping(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            self._write(root / "1.json", [""])
            with self.assertRaisesRegex(ContractError, "color_raw"):
                validate_jev_data(root)

    def test_rejects_missing_or_invalid_required_fields(self) -> None:
        missing = object()
        invalid_strings = (missing, None, "", " \t\n", 0, False, [], {})
        for field, values in (
            ("name", invalid_strings),
            ("dataset", (missing, None, "", "invalid", 0, False, [])),
            ("logical_category", invalid_strings),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                        root = Path(directory)
                        path = root / "1.json"
                        self._write(path, ["navy"])
                        product = json.loads(path.read_text(encoding="utf-8"))
                        target = product["dataset"] if field == "logical_category" else product
                        if value is missing:
                            del target[field]
                        else:
                            target[field] = value
                        path.write_text(json.dumps(product), encoding="utf-8")

                        with self.assertRaisesRegex(ContractError, field):
                            validate_jev_data(root)

    def test_rejects_non_array_color_image_mappings(self) -> None:
        for value in (None, False, 0, "", {}, 1, "invalid", {"color_raw": "navy"}):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                    root = Path(directory)
                    self._write(root / "1.json", ["navy"])
                    path = root / "2.json"
                    self._write(path, [])
                    product = json.loads(path.read_text(encoding="utf-8"))
                    product["color_image_mappings"] = value
                    path.write_text(json.dumps(product), encoding="utf-8")

                    with self.assertRaisesRegex(ContractError, "color_image_mappings must be an array"):
                        validate_jev_data(root)

    def test_allows_missing_or_empty_color_image_mappings(self) -> None:
        for omit_mappings in (True, False):
            with self.subTest(omit_mappings=omit_mappings):
                with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
                    root = Path(directory)
                    self._write(root / "1.json", ["navy"])
                    path = root / "2.json"
                    self._write(path, [])
                    if omit_mappings:
                        product = json.loads(path.read_text(encoding="utf-8"))
                        del product["color_image_mappings"]
                        path.write_text(json.dumps(product), encoding="utf-8")

                    self.assertEqual(validate_jev_data(root), {
                        "source_product_count": 2,
                        "products_with_colors": 1,
                        "unique_color_count": 1,
                    })

    @staticmethod
    def _write(path: Path, colors: list[str]) -> None:
        path.write_text(json.dumps({
            "name": "상품",
            "dataset": {"logical_category": "상의"},
            "color_image_mappings": [{"color_raw": color} for color in colors],
        }, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
