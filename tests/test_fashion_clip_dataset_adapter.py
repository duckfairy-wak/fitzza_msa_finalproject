import json
import uuid

import pytest

from scripts.fashion_clip_dataset_adapter import adapt_product, export_dataset


def candidate() -> dict:
    return {
        "product_id": str(uuid.UUID("1d01de89-1949-50ad-9a5e-9924dfe50ec9")),
        "source_product_id": 3232889,
        "source": "musinsa",
        "source_url": "https://www.musinsa.com/products/3232889",
        "name": "상품",
        "brand": {"name": "브랜드"},
        "category": {"categoryDepth2Title": "캡/야구모자"},
        "dataset": {"logical_category": "모자"},
        "season": {"primary": "ALL"},
        "price": {"normal": 29900},
        "features": {},
        "color": {"raw": "NAVY", "name": "NAVY"},
        "thumbnail_url": "https://example.com/navy.jpg",
        "thumbnail_status": "verified",
        "measurement_unit": "cm",
        "sizes": [
            {
                "size": "FREE",
                "measurement_status": "label_match",
                "머리둘레": 60,
                "챙길이": 7.5,
                "깊이": 17,
            },
            {"size": "L", "measurement_status": "shared_scope_unverified", "머리둘레": 62},
        ],
    }


def test_verified_variant_maps_to_indexer_shape() -> None:
    product, reasons = adapt_product(candidate())
    assert reasons == []
    assert isinstance(product["product_id"], int)
    assert product["product_id"] != product["source_product_id"]
    assert product["images"] == ["https://example.com/navy.jpg"]
    assert product["size"]["measurements"] == [
        {"size": "FREE", "sequence": 0, "measurements": {"머리둘레": 60.0, "챙길이": 7.5, "깊이": 17.0}}
    ]
    assert adapt_product(candidate())[0]["product_id"] == product["product_id"]


def test_unknown_image_and_measurements_are_not_invented() -> None:
    source = candidate()
    source["thumbnail_status"] = "unverified"
    source["thumbnail_url"] = None
    source["sizes"][0]["measurement_status"] = "shared_scope_unverified"
    product, reasons = adapt_product(source)
    assert product is None
    assert set(reasons) == {"thumbnail_not_verified", "no_verified_measurements"}


def test_export_writes_only_verified_products(tmp_path) -> None:
    source = tmp_path / "source"
    folder = source / "모자"
    folder.mkdir(parents=True)
    good = candidate()
    bad = candidate()
    bad["product_id"] = str(uuid.uuid4())
    bad["thumbnail_status"] = "unverified"
    (folder / "good.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    (folder / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")

    output = tmp_path / "output"
    report = export_dataset(source, output)

    assert report["input_count"] == 2
    assert report["exported_count"] == 1
    assert report["excluded_count"] == 1
    assert report["exclusion_reasons"] == {"thumbnail_not_verified": 1}
    indexed = list((output / "data").rglob("*.json"))
    assert len(indexed) == 1
    assert json.loads(indexed[0].read_text(encoding="utf-8"))["product_id"] == report["products"][0]["product_id"]
    assert (output / "report.json").exists()


def test_export_refuses_nonempty_output(tmp_path) -> None:
    source = tmp_path / "source" / "모자"
    source.mkdir(parents=True)
    (source / "one.json").write_text(json.dumps(candidate(), ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty"):
        export_dataset(source.parent, output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
