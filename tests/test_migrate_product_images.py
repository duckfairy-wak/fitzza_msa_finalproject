import io
import json
from unittest.mock import Mock

from scripts.migrate_product_images import (
    build_migration_sql,
    collect_references,
    object_key,
    upload_verified_image,
    validate_image,
)


def product_detail():
    return {
        "productId": 10,
        "thumbnailUrl": "https://source.example/thumb.jpg",
        "images": [
            "https://source.example/thumb.jpg",
            "https://source.example/detail.png",
        ],
        "options": [
            {"optionId": 21, "imageUrl": "https://source.example/option.webp"},
            {"optionId": 22, "imageUrl": None},
        ],
        "sizeGuide": {"guideImageUrl": "https://source.example/guide.gif"},
        "colorImageMappings": [
            {"colorRaw": "Black", "imageUrl": "https://source.example/thumb.jpg"}
        ],
    }


def test_collects_every_persisted_product_image_location():
    references = collect_references(product_detail())

    assert [reference["kind"] for reference in references] == [
        "product",
        "product_image",
        "product_image",
        "product_option",
        "product_size_guide",
        "color_image_mapping",
    ]
    assert references[2]["selector"] == {"sequence": 1}
    assert references[3]["selector"] == {"option_id": 21}


def test_image_validation_checks_content_type_and_magic_bytes():
    assert validate_image("image/jpeg", b"\xff\xd8\xffpayload") == ("image/jpeg", "jpg")
    assert validate_image("image/webp", b"RIFF1234WEBPpayload") == ("image/webp", "webp")

    try:
        validate_image("image/jpeg", b"not-an-image")
    except ValueError as error:
        assert "signature" in str(error)
    else:
        raise AssertionError("invalid signature was accepted")


def test_content_addressed_key_is_stable():
    digest = "ab" + "1" * 62
    assert object_key("/public/product-images/", digest, "jpg") == (
        f"public/product-images/ab/{digest}.jpg"
    )


def fake_s3():
    s3 = Mock()
    s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
    stored = {}

    def head_object(**kwargs):
        key = kwargs["Key"]
        if key not in stored:
            raise s3.exceptions.NoSuchKey()
        body, metadata = stored[key]
        return {"ContentLength": len(body), "Metadata": metadata}

    def put_object(**kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["ServerSideEncryption"] == "AES256"
        assert kwargs["CacheControl"] == "public,max-age=31536000,immutable"
        stored[kwargs["Key"]] = (kwargs["Body"], kwargs["Metadata"])

    s3.head_object.side_effect = head_object
    s3.put_object.side_effect = put_object
    return s3, stored


def test_s3_upload_is_verified_and_idempotent():
    s3, _ = fake_s3()
    arguments = {
        "account_id": "123456789012",
        "bucket": "assets",
        "key": "public/product-images/aa/asset.jpg",
        "body": b"image",
        "content_type": "image/jpeg",
        "digest": "aa" * 32,
    }

    assert upload_verified_image(s3, **arguments) == "created"
    assert upload_verified_image(s3, **arguments) == "verified_existing"
    s3.put_object.assert_called_once()


def test_generated_sql_is_conditional_and_rolls_back_by_default():
    old = "https://source.example/image.jpg"
    new = "https://assets.example/aa/image.jpg"
    references = [
        {"product_id": 10, "kind": "product", "selector": {}, "source_url": old},
        {"product_id": 10, "kind": "product_image", "selector": {"sequence": 0},
         "source_url": old},
        {"product_id": 10, "kind": "product_option", "selector": {"option_id": 21},
         "source_url": old},
        {"product_id": 10, "kind": "product_size_guide", "selector": {},
         "source_url": old},
        {"product_id": 10, "kind": "color_image_mapping",
         "selector": {"color_raw": "Black"}, "source_url": old},
    ]
    mapping = {
        "uploads": [{"source_url": old, "public_url": new, "status": "created"}],
        "references": references,
    }

    sql = build_migration_sql(mapping)

    assert "BEGIN;" in sql
    assert "ROLLBACK;" in sql
    assert "COMMIT;" not in sql
    assert "AND image_url = 'https://source.example/image.jpg'" in sql
    assert "sequence = 0" in sql
    assert "option_id = 21" in sql
    assert "guide_image_url" in sql
    assert "jsonb_array_elements" in sql


def test_generated_sql_ignores_failed_uploads():
    mapping = {
        "uploads": [{"source_url": "https://bad", "status": "download_failed"}],
        "references": [{
            "product_id": 10,
            "kind": "product",
            "selector": {},
            "source_url": "https://bad",
        }],
    }

    assert "UPDATE" not in build_migration_sql(mapping)
