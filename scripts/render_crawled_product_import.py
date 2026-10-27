"""Validate curated product crawler output and render an idempotent psql import.

Mirrors the review-import pattern: staging TEMP tables + upsert into
``product_service`` tables using the same field rules as
``MusinsaProductMapper`` / ``ProductSeedService``.

Image rows prefer S3 object keys under ``images/products/<product_id>/`` when an
image inventory is provided; URLs are built as
``{image_public_base_url}/{object_key}``. Without inventory, curated JSON
``images[]`` HTTPS URLs are used. Image download failures never abort the run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SOURCE = "musinsa"
SIZE_GROUP_NAME = re.compile(r"사이즈|size", re.IGNORECASE)
COLOR_GROUP_NAME = re.compile(r"컬러|색상|color", re.IGNORECASE)
COLOR_JOIN_DELIMITER = " / "
FIT_TYPES = frozenset({"REGULAR", "RELAXED", "CROPPED", "SLIM", "OVERSIZED"})
GENDERS = frozenset({"MALE", "FEMALE", "UNISEX"})
SEASON_BY_PRIMARY = {"봄": "SPRING", "여름": "SUMMER", "가을": "FALL", "겨울": "WINTER"}
EXPECTED_PRODUCT_COUNT = 3000


@dataclass(frozen=True)
class CategoryRow:
    category_code: str
    category_name: str
    parent_code: str | None
    depth: int


@dataclass(frozen=True)
class BrandRow:
    brand_code: str | None
    brand_name: str
    brand_name_en: str | None


@dataclass(frozen=True)
class ProductRow:
    product_id: int
    brand_name: str
    source_url: str | None
    product_name: str
    product_name_en: str | None
    style_no: str | None
    gender: str | None
    category_1: str
    category_2: str | None
    subcategory: str | None
    price: int
    normal_price: int | None
    discount_rate: int | None
    material: str | None
    season: str | None
    fit_type: str | None
    features_json: str | None
    color_image_mappings_json: str | None
    image_url: str | None
    status: str


@dataclass(frozen=True)
class ImageRow:
    product_id: int
    image_url: str
    sequence: int
    object_key: str | None = None


@dataclass(frozen=True)
class SizeGuideRow:
    product_id: int
    type_name: str | None
    unit: str | None
    description: str | None
    guide_image_url: str | None


@dataclass(frozen=True)
class OptionRow:
    product_id: int
    source_option_id: int
    managed_code: str | None
    color: str | None
    size: str | None
    additional_price: int
    image_url: str | None


@dataclass(frozen=True)
class MeasurementRow:
    source_option_id: int
    size_label: str | None
    sequence: int | None
    measurement_spec_json: str


@dataclass
class ImportBundle:
    categories: list[CategoryRow] = field(default_factory=list)
    brands: list[BrandRow] = field(default_factory=list)
    products: list[ProductRow] = field(default_factory=list)
    images: list[ImageRow] = field(default_factory=list)
    size_guides: list[SizeGuideRow] = field(default_factory=list)
    options: list[OptionRow] = field(default_factory=list)
    measurements: list[MeasurementRow] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    image_failures: set[int] = field(default_factory=set)
    image_failure_files: int = 0


def blank_to_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_status(status_path: Path, expected_count: int = EXPECTED_PRODUCT_COUNT) -> dict[str, Any]:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    require(status.get("state") == "succeeded", f"status.state must be succeeded, got {status.get('state')!r}")
    product_count = status.get("product_count")
    require(
        product_count == expected_count,
        f"status.product_count must be {expected_count}, got {product_count!r}",
    )
    return status


def verify_manifest(manifest_path: Path, curated_root: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files") or manifest.get("products") or manifest.get("entries")
    require(isinstance(entries, list) and entries, "manifest must list files")

    resolved: list[Path] = []
    seen_ids: set[int] = set()
    for entry in entries:
        if isinstance(entry, str):
            relative = entry
            expected_hash = None
        elif isinstance(entry, dict):
            relative = entry.get("path") or entry.get("file") or entry.get("key")
            expected_hash = entry.get("sha256") or entry.get("checksum")
        else:
            raise ValueError("manifest entry must be a string or object")
        require(isinstance(relative, str) and relative, "manifest entry path missing")
        # Accept keys like curated/data/top/1.json, data/모자/1.json, or 모자/1.json
        relative = relative.replace("\\", "/").lstrip("/")
        for prefix in ("curated/", "pipeline/runs/",):
            if relative.startswith(prefix):
                # Keep only the path under curated/ when a full s3-style key is provided.
                if "curated/" in relative:
                    relative = relative[relative.index("curated/") + len("curated/") :]
                break
        candidates = [
            curated_root / relative,
            curated_root / "data" / relative,
        ]
        if relative.startswith("data/"):
            candidates.append(curated_root / relative)
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        require(path is not None, f"manifest file missing: {relative}")
        if expected_hash:
            actual = sha256_file(path)
            require(
                actual.lower() == str(expected_hash).lower(),
                f"SHA-256 mismatch for {relative}: expected {expected_hash}, got {actual}",
            )
        product_id = int(path.stem)
        require(product_id not in seen_ids, f"duplicate product_id in manifest: {product_id}")
        seen_ids.add(product_id)
        resolved.append(path)

    require(
        len(resolved) == EXPECTED_PRODUCT_COUNT,
        f"manifest product count must be {EXPECTED_PRODUCT_COUNT}, got {len(resolved)}",
    )
    return sorted(resolved, key=lambda path: int(path.stem))


def load_product_paths_without_manifest(data_root: Path) -> list[Path]:
    files = sorted(data_root.glob("*/*.json"), key=lambda path: (path.parent.name, int(path.stem)))
    require(files, f"no product JSON under {data_root}")
    ids = [int(path.stem) for path in files]
    require(len(ids) == len(set(ids)), "duplicate product_id under curated/data")
    return files


def load_image_failures(failures_root: Path | None) -> tuple[set[int], int]:
    if failures_root is None or not failures_root.exists():
        return set(), 0
    files = sorted(failures_root.glob("*.json"))
    product_ids = {int(path.stem) for path in files}
    return product_ids, len(files)


def load_image_inventory(images_root: Path | None) -> dict[int, list[str]]:
    """Map product_id -> sorted relative object file names under images/products/<id>/."""
    if images_root is None or not images_root.exists():
        return {}
    inventory: dict[int, list[str]] = {}
    for product_dir in sorted(path for path in images_root.iterdir() if path.is_dir()):
        try:
            product_id = int(product_dir.name)
        except ValueError:
            continue
        names = sorted(
            path.name
            for path in product_dir.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )
        if names:
            inventory[product_id] = names
    return inventory


def group_name(groups: list[Any], index: int) -> str:
    if index >= len(groups) or not isinstance(groups[index], dict):
        return ""
    name = groups[index].get("name")
    return name if isinstance(name, str) else ""


def find_size_index(groups: list[Any], value_count: int) -> int:
    for index in range(value_count):
        if SIZE_GROUP_NAME.search(group_name(groups, index)):
            return index
    return value_count - 1


def resolve_attributes(groups: list[Any], values: list[str]) -> tuple[str | None, str | None]:
    if not values:
        return None, None
    if len(values) == 1:
        name = group_name(groups, 0)
        color_only = bool(COLOR_GROUP_NAME.search(name)) and not bool(SIZE_GROUP_NAME.search(name))
        return (blank_to_none(values[0]), None) if color_only else (None, blank_to_none(values[0]))
    size_index = find_size_index(groups, len(values))
    color = COLOR_JOIN_DELIMITER.join(
        value for index, value in enumerate(values) if index != size_index and blank_to_none(value)
    )
    return blank_to_none(color), blank_to_none(values[size_index])


def color_image_url(mappings: list[dict[str, Any]], color: str | None) -> str | None:
    if not color:
        return None
    for mapping in mappings:
        if mapping.get("color_raw") == color:
            return blank_to_none(mapping.get("image_url"))
    return None


def active_option_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    items = document.get("option_items") or []
    require(isinstance(items, list), "option_items must be a list")
    active: list[dict[str, Any]] = []
    for item in items:
        require(isinstance(item, dict), "option_items entry must be an object")
        if item.get("id") is None or item.get("activated") is False:
            continue
        active.append(item)
    return active


def to_categories(document: dict[str, Any]) -> list[CategoryRow]:
    category = document.get("category") or {}
    require(isinstance(category, dict), "category must be an object")
    levels = [
        (blank_to_none(category.get("categoryDepth1Code")), blank_to_none(category.get("categoryDepth1Name"))),
        (blank_to_none(category.get("categoryDepth2Code")), blank_to_none(category.get("categoryDepth2Name"))),
        (blank_to_none(category.get("categoryDepth3Code")), blank_to_none(category.get("categoryDepth3Name"))),
    ]
    rows: list[CategoryRow] = []
    parent: str | None = None
    for depth, (code, name) in enumerate(levels, start=1):
        if not code or not name:
            break
        rows.append(CategoryRow(category_code=code, category_name=name, parent_code=parent, depth=depth))
        parent = code
    require(rows, "category.categoryDepth1Code or categoryDepth1Name missing")
    return rows


def to_measurement_spec(measurements: dict[str, Any]) -> dict[str, float]:
    spec: dict[str, float] = {}
    for name, value in measurements.items():
        if isinstance(value, (int, float)) and value > 0:
            spec[str(name)] = float(value)
    return spec


def resolve_images(
    product_id: int,
    document: dict[str, Any],
    inventory: dict[int, list[str]],
    *,
    image_key_prefix: str,
    image_public_base_url: str | None,
) -> list[ImageRow]:
    names = inventory.get(product_id)
    if names and image_public_base_url:
        base = image_public_base_url.rstrip("/")
        rows: list[ImageRow] = []
        for sequence, name in enumerate(names):
            object_key = f"{image_key_prefix.rstrip('/')}/{product_id}/{name}"
            url = f"{base}/{object_key}"
            require(len(url) <= 500, f"product {product_id}: image URL exceeds 500 chars")
            rows.append(ImageRow(product_id=product_id, image_url=url, sequence=sequence, object_key=object_key))
        return rows
    if names and not image_public_base_url:
        # Guide prefers object keys; API currently serves image_url as-is, so store the key
        # when no public base is configured (operator can rewrite later via CDN base).
        rows = []
        for sequence, name in enumerate(names):
            object_key = f"{image_key_prefix.rstrip('/')}/{product_id}/{name}"
            require(len(object_key) <= 500, f"product {product_id}: object key exceeds 500 chars")
            rows.append(
                ImageRow(product_id=product_id, image_url=object_key, sequence=sequence, object_key=object_key)
            )
        return rows

    images = document.get("images") or []
    require(isinstance(images, list), "images must be a list")
    rows = []
    for sequence, url in enumerate(images):
        text = blank_to_none(url)
        if not text:
            continue
        require(len(text) <= 500, f"product {product_id}: image URL exceeds 500 chars")
        rows.append(ImageRow(product_id=product_id, image_url=text, sequence=sequence))
    return rows


def parse_product(
    document: dict[str, Any],
    *,
    inventory: dict[int, list[str]],
    image_key_prefix: str,
    image_public_base_url: str | None,
) -> tuple[list[CategoryRow], BrandRow, ProductRow, list[ImageRow], SizeGuideRow | None, list[OptionRow], list[MeasurementRow]]:
    product_id = document.get("product_id")
    require(isinstance(product_id, int) and product_id > 0, "product_id must be a positive integer")
    name = blank_to_none(document.get("name"))
    require(name, "name is required")
    brand = document.get("brand") or {}
    require(isinstance(brand, dict) and blank_to_none(brand.get("name")), "brand.name is required")
    price = document.get("price") or {}
    require(isinstance(price, dict), "price must be an object")
    sale = price.get("sale")
    require(isinstance(sale, int) and sale > 0, "price.sale must be a positive integer")

    categories = to_categories(document)
    brand_row = BrandRow(
        brand_code=blank_to_none(brand.get("id")),
        brand_name=brand["name"].strip(),
        brand_name_en=blank_to_none(brand.get("name_en")),
    )

    gender_raw = ((document.get("gender") or {}) if isinstance(document.get("gender"), dict) else {}).get("normalized")
    gender = blank_to_none(gender_raw)
    if gender:
        gender = gender.upper()
        require(gender in GENDERS, f"unsupported gender: {gender}")

    season_primary = ((document.get("season") or {}) if isinstance(document.get("season"), dict) else {}).get("primary")
    season = SEASON_BY_PRIMARY.get(str(season_primary).strip()) if season_primary else None

    fit_type = blank_to_none(document.get("fit_type"))
    if fit_type:
        fit_type = fit_type.upper()
        require(fit_type in FIT_TYPES, f"unsupported fit_type: {fit_type}")

    features = document.get("features")
    features_json = json.dumps(features, ensure_ascii=False, separators=(",", ":")) if isinstance(features, dict) else None

    mappings = document.get("color_image_mappings") or []
    require(isinstance(mappings, list), "color_image_mappings must be a list")
    cleaned_mappings = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        color_raw = blank_to_none(mapping.get("color_raw"))
        if not color_raw:
            continue
        cleaned_mappings.append(
            {
                "productId": mapping.get("product_id") or product_id,
                "colorRaw": color_raw,
                "imageUrl": blank_to_none(mapping.get("image_url")),
            }
        )
    color_mappings_json = (
        json.dumps(cleaned_mappings, ensure_ascii=False, separators=(",", ":")) if cleaned_mappings else None
    )

    images = resolve_images(
        product_id,
        document,
        inventory,
        image_key_prefix=image_key_prefix,
        image_public_base_url=image_public_base_url,
    )
    thumbnail = images[0].image_url if images else None

    options_meta = document.get("options") or []
    require(isinstance(options_meta, list), "options must be a list")
    active_items = active_option_items(document)
    status = "ON_SALE" if active_items else "SOLD_OUT"

    product = ProductRow(
        product_id=product_id,
        brand_name=brand_row.brand_name,
        source_url=blank_to_none(document.get("source_url")),
        product_name=name,
        product_name_en=blank_to_none(document.get("name_en")),
        style_no=blank_to_none(document.get("style_no")),
        gender=gender,
        category_1=categories[0].category_code,
        category_2=categories[1].category_code if len(categories) > 1 else None,
        subcategory=categories[2].category_code if len(categories) > 2 else None,
        price=sale,
        normal_price=price.get("normal") if isinstance(price.get("normal"), int) else None,
        discount_rate=price.get("discount_rate") if isinstance(price.get("discount_rate"), int) else None,
        material=blank_to_none(document.get("material")),
        season=season,
        fit_type=fit_type,
        features_json=features_json,
        color_image_mappings_json=color_mappings_json,
        image_url=thumbnail,
        status=status,
    )

    size = document.get("size") if isinstance(document.get("size"), dict) else None
    size_guide = None
    if size:
        size_guide = SizeGuideRow(
            product_id=product_id,
            type_name=blank_to_none(size.get("type_name")),
            unit=blank_to_none(size.get("unit")),
            description=blank_to_none(size.get("description")),
            guide_image_url=blank_to_none(size.get("guide_image")),
        )

    option_rows: list[OptionRow] = []
    measurement_rows: list[MeasurementRow] = []
    measurements_by_size: dict[str, dict[str, Any]] = {}
    if size and isinstance(size.get("measurements"), list):
        for entry in size["measurements"]:
            if not isinstance(entry, dict):
                continue
            label = blank_to_none(entry.get("size"))
            specs = entry.get("measurements")
            if not label or not isinstance(specs, dict):
                continue
            measurements_by_size[label] = entry

    for item in active_items:
        source_option_id = item.get("id")
        require(isinstance(source_option_id, int) and source_option_id > 0, "option id must be positive")
        values = item.get("values") or []
        require(isinstance(values, list), "option values must be a list")
        str_values = [str(value) for value in values if value is not None and str(value).strip()]
        color, size_label = resolve_attributes(options_meta, str_values)
        additional = item.get("price_delta")
        additional_price = additional if isinstance(additional, int) else 0
        option_rows.append(
            OptionRow(
                product_id=product_id,
                source_option_id=source_option_id,
                managed_code=blank_to_none(item.get("managed_code")),
                color=color,
                size=size_label,
                additional_price=additional_price,
                image_url=color_image_url(
                    [m for m in mappings if isinstance(m, dict)],
                    color,
                ),
            )
        )
        candidates = [size_label, blank_to_none(item.get("managed_code")), *str_values]
        found = next((measurements_by_size[c] for c in candidates if c and c in measurements_by_size), None)
        if found:
            spec = to_measurement_spec(found.get("measurements") or {})
            if spec:
                measurement_rows.append(
                    MeasurementRow(
                        source_option_id=source_option_id,
                        size_label=blank_to_none(found.get("size")),
                        sequence=found.get("sequence") if isinstance(found.get("sequence"), int) else None,
                        measurement_spec_json=json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                    )
                )

    return categories, brand_row, product, images, size_guide, option_rows, measurement_rows


def load_bundle(
    *,
    data_root: Path,
    status_path: Path | None,
    manifest_path: Path | None,
    images_root: Path | None,
    failures_root: Path | None,
    image_key_prefix: str,
    image_public_base_url: str | None,
    expected_count: int | None,
    skip_invalid: bool,
) -> ImportBundle:
    if status_path is not None:
        verify_status(status_path, expected_count or EXPECTED_PRODUCT_COUNT)

    curated_root = data_root.parent if data_root.name == "data" else data_root
    if manifest_path is not None:
        paths = verify_manifest(manifest_path, curated_root)
    else:
        paths = load_product_paths_without_manifest(data_root)
        if expected_count is not None:
            require(len(paths) == expected_count, f"expected {expected_count} products, found {len(paths)}")

    inventory = load_image_inventory(images_root)
    failure_ids, failure_files = load_image_failures(failures_root)

    bundle = ImportBundle(image_failures=failure_ids, image_failure_files=failure_files)
    categories_by_code: dict[str, CategoryRow] = {}
    brands_by_name: dict[str, BrandRow] = {}

    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            require(isinstance(document, dict), "product document must be an object")
            require(path.stem == str(document.get("product_id")), f"{path.name}: product_id mismatch")
            categories, brand, product, images, size_guide, options, measurements = parse_product(
                document,
                inventory=inventory,
                image_key_prefix=image_key_prefix,
                image_public_base_url=image_public_base_url,
            )
            for category in categories:
                categories_by_code.setdefault(category.category_code, category)
            brands_by_name.setdefault(brand.brand_name, brand)
            bundle.products.append(product)
            bundle.images.extend(images)
            if size_guide is not None:
                bundle.size_guides.append(size_guide)
            bundle.options.extend(options)
            bundle.measurements.extend(measurements)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            message = f"{path}: {error}"
            if not skip_invalid:
                raise ValueError(message) from error
            bundle.skipped.append(message)

    require(bundle.products, "no valid products found")
    bundle.categories = list(categories_by_code.values())
    bundle.brands = list(brands_by_name.values())
    if failure_files:
        # Guide mentioned 64; this run may differ. Never abort the product load.
        bundle.skipped.append(f"image failure audit files={failure_files}; continuing without abort")
    return bundle


def _copy_section(output: io.StringIO, table: str, columns: list[str], rows: list[list[Any]]) -> None:
    output.write(
        f"COPY {table} ({', '.join(columns)}) "
        "FROM STDIN WITH (FORMAT csv, HEADER true, NULL '');\n"
    )
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    output.write("\\.\n")


def render_sql(bundle: ImportBundle, *, run_id: str) -> str:
    output = io.StringIO(newline="")
    output.write("\\set ON_ERROR_STOP on\nBEGIN;\n")
    output.write(f"-- curated product import run_id={run_id}\n")

    output.write(
        "CREATE TEMP TABLE crawled_product_category ("
        "category_code varchar(20), category_name varchar(100), parent_code varchar(20), depth integer"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_product_brand ("
        "brand_code varchar(100), brand_name varchar(100), brand_name_en varchar(100)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_product ("
        "product_id bigint, brand_name varchar(100), source_url varchar(300), "
        "product_name varchar(200), product_name_en varchar(200), style_no varchar(100), "
        "gender varchar(20), category_1 varchar(50), category_2 varchar(50), subcategory varchar(50), "
        "price integer, normal_price integer, discount_rate integer, material varchar(200), "
        "season varchar(10), fit_type varchar(20), features jsonb, color_image_mappings jsonb, "
        "image_url varchar(500), status varchar(20)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_product_image ("
        "product_id bigint, image_url varchar(500), sequence integer, object_key varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_product_size_guide ("
        "product_id bigint, type_name varchar(50), unit varchar(10), description varchar(500), "
        "guide_image_url varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_product_option ("
        "product_id bigint, source_option_id bigint, managed_code varchar(100), color varchar(100), "
        "size varchar(100), additional_price integer, image_url varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE crawled_option_measurement ("
        "source_option_id bigint, size_label varchar(100), sequence integer, measurement_spec jsonb"
        ") ON COMMIT DROP;\n"
    )

    _copy_section(
        output,
        "crawled_product_category",
        ["category_code", "category_name", "parent_code", "depth"],
        [[c.category_code, c.category_name, c.parent_code, c.depth] for c in bundle.categories],
    )
    _copy_section(
        output,
        "crawled_product_brand",
        ["brand_code", "brand_name", "brand_name_en"],
        [[b.brand_code, b.brand_name, b.brand_name_en] for b in bundle.brands],
    )
    _copy_section(
        output,
        "crawled_product",
        [
            "product_id",
            "brand_name",
            "source_url",
            "product_name",
            "product_name_en",
            "style_no",
            "gender",
            "category_1",
            "category_2",
            "subcategory",
            "price",
            "normal_price",
            "discount_rate",
            "material",
            "season",
            "fit_type",
            "features",
            "color_image_mappings",
            "image_url",
            "status",
        ],
        [
            [
                p.product_id,
                p.brand_name,
                p.source_url,
                p.product_name,
                p.product_name_en,
                p.style_no,
                p.gender,
                p.category_1,
                p.category_2,
                p.subcategory,
                p.price,
                p.normal_price,
                p.discount_rate,
                p.material,
                p.season,
                p.fit_type,
                p.features_json,
                p.color_image_mappings_json,
                p.image_url,
                p.status,
            ]
            for p in bundle.products
        ],
    )
    _copy_section(
        output,
        "crawled_product_image",
        ["product_id", "image_url", "sequence", "object_key"],
        [[i.product_id, i.image_url, i.sequence, i.object_key] for i in bundle.images],
    )
    _copy_section(
        output,
        "crawled_product_size_guide",
        ["product_id", "type_name", "unit", "description", "guide_image_url"],
        [
            [g.product_id, g.type_name, g.unit, g.description, g.guide_image_url]
            for g in bundle.size_guides
        ],
    )
    _copy_section(
        output,
        "crawled_product_option",
        [
            "product_id",
            "source_option_id",
            "managed_code",
            "color",
            "size",
            "additional_price",
            "image_url",
        ],
        [
            [
                o.product_id,
                o.source_option_id,
                o.managed_code,
                o.color,
                o.size,
                o.additional_price,
                o.image_url,
            ]
            for o in bundle.options
        ],
    )
    _copy_section(
        output,
        "crawled_option_measurement",
        ["source_option_id", "size_label", "sequence", "measurement_spec"],
        [
            [m.source_option_id, m.size_label, m.sequence, m.measurement_spec_json]
            for m in bundle.measurements
        ],
    )

    output.write(
        "INSERT INTO product_service.category (category_code, category_name, parent_code, depth) "
        "SELECT category_code, category_name, NULLIF(parent_code, ''), depth "
        "FROM crawled_product_category "
        "ON CONFLICT (category_code) DO UPDATE SET "
        "category_name = EXCLUDED.category_name, parent_code = EXCLUDED.parent_code, depth = EXCLUDED.depth;\n"
    )
    output.write(
        "INSERT INTO product_service.brand (brand_name, brand_name_en, brand_code) "
        "SELECT b.brand_name, NULLIF(b.brand_name_en, ''), NULLIF(b.brand_code, '') "
        "FROM crawled_product_brand b "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM product_service.brand existing "
        "  WHERE existing.brand_name = b.brand_name "
        "     OR (NULLIF(b.brand_code, '') IS NOT NULL AND existing.brand_code = b.brand_code)"
        ");\n"
    )
    output.write(
        "INSERT INTO product_service.product AS existing ("
        "product_id, brand_id, source, source_url, product_name, product_name_en, style_no, gender, "
        "category_1, category_2, subcategory, price, normal_price, discount_rate, material, season, "
        "fit_type, features, color_image_mappings, image_url, status, created_at, updated_at"
        ") SELECT "
        "p.product_id, "
        "(SELECT brand_id FROM product_service.brand b WHERE b.brand_name = p.brand_name "
        "ORDER BY brand_id LIMIT 1), "
        f"'{SOURCE}', NULLIF(p.source_url, ''), p.product_name, NULLIF(p.product_name_en, ''), "
        "NULLIF(p.style_no, ''), NULLIF(p.gender, '')::varchar, p.category_1, NULLIF(p.category_2, ''), "
        "NULLIF(p.subcategory, ''), p.price, p.normal_price, p.discount_rate, NULLIF(p.material, ''), "
        "NULLIF(p.season, '')::varchar, NULLIF(p.fit_type, '')::varchar, p.features, p.color_image_mappings, "
        "NULLIF(p.image_url, ''), p.status, NOW(), NOW() "
        "FROM crawled_product p "
        "ON CONFLICT (product_id) DO UPDATE SET "
        "brand_id = EXCLUDED.brand_id, source = EXCLUDED.source, source_url = EXCLUDED.source_url, "
        "product_name = EXCLUDED.product_name, product_name_en = EXCLUDED.product_name_en, "
        "style_no = EXCLUDED.style_no, gender = EXCLUDED.gender, category_1 = EXCLUDED.category_1, "
        "category_2 = EXCLUDED.category_2, subcategory = EXCLUDED.subcategory, price = EXCLUDED.price, "
        "normal_price = EXCLUDED.normal_price, discount_rate = EXCLUDED.discount_rate, "
        "material = EXCLUDED.material, season = EXCLUDED.season, fit_type = EXCLUDED.fit_type, "
        "features = EXCLUDED.features, color_image_mappings = EXCLUDED.color_image_mappings, "
        "image_url = EXCLUDED.image_url, status = EXCLUDED.status, updated_at = EXCLUDED.updated_at;\n"
    )
    output.write(
        "DELETE FROM product_service.product_image pi "
        "USING crawled_product p WHERE pi.product_id = p.product_id;\n"
    )
    output.write(
        "INSERT INTO product_service.product_image (product_id, image_url, sequence) "
        "SELECT product_id, image_url, sequence FROM crawled_product_image;\n"
    )
    output.write(
        "DELETE FROM product_service.product_size_guide g "
        "USING crawled_product p WHERE g.product_id = p.product_id;\n"
    )
    output.write(
        "INSERT INTO product_service.product_size_guide "
        "(product_id, type_name, unit, description, guide_image_url) "
        "SELECT product_id, NULLIF(type_name, ''), NULLIF(unit, ''), NULLIF(description, ''), "
        "NULLIF(guide_image_url, '') FROM crawled_product_size_guide;\n"
    )
    output.write(
        "INSERT INTO product_service.product_option AS existing ("
        "product_id, source_option_id, managed_code, color, size, additional_price, image_url"
        ") SELECT product_id, source_option_id, NULLIF(managed_code, ''), NULLIF(color, ''), "
        "NULLIF(size, ''), COALESCE(additional_price, 0), NULLIF(image_url, '') "
        "FROM crawled_product_option "
        "ON CONFLICT (source_option_id) DO UPDATE SET "
        "product_id = EXCLUDED.product_id, managed_code = EXCLUDED.managed_code, "
        "color = EXCLUDED.color, size = EXCLUDED.size, additional_price = EXCLUDED.additional_price, "
        "image_url = EXCLUDED.image_url;\n"
    )
    output.write(
        "DELETE FROM product_service.option_measurement om "
        "USING product_service.product_option po, crawled_product p "
        "WHERE om.option_id = po.option_id AND po.product_id = p.product_id;\n"
    )
    output.write(
        "INSERT INTO product_service.option_measurement "
        "(option_id, size_label, sequence, measurement_spec) "
        "SELECT po.option_id, NULLIF(m.size_label, ''), m.sequence, m.measurement_spec "
        "FROM crawled_option_measurement m "
        "JOIN product_service.product_option po ON po.source_option_id = m.source_option_id;\n"
    )
    output.write("COMMIT;\n")
    return output.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate curated product JSON and render an idempotent product_service import."
    )
    parser.add_argument("--data", type=Path, required=True, help="curated/data directory")
    parser.add_argument("--status", type=Path, help="run status.json (recommended)")
    parser.add_argument("--manifest", type=Path, help="curated/manifest.json (recommended)")
    parser.add_argument("--images", type=Path, help="local images/products directory")
    parser.add_argument(
        "--image-failures",
        type=Path,
        help="audit/image-download-failures/products directory",
    )
    parser.add_argument(
        "--image-key-prefix",
        default="pipeline/runs/collection-20261025-01/images/products",
        help="S3 key prefix for product images",
    )
    parser.add_argument(
        "--image-public-base-url",
        help="HTTPS base used to turn object keys into image_url values",
    )
    parser.add_argument("--run-id", default="collection-20261025-01")
    parser.add_argument("--expected-count", type=int, default=EXPECTED_PRODUCT_COUNT)
    parser.add_argument("--output", type=Path, required=True, help="destination .sql (keep outside Git)")
    parser.add_argument("--skip-invalid", action="store_true")
    parser.add_argument(
        "--skip-status-check",
        action="store_true",
        help="allow local fixture runs without status.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    status_path = None if args.skip_status_check else args.status
    if not args.skip_status_check and status_path is None:
        raise SystemExit("--status is required unless --skip-status-check is set")
    expected_count = None if args.skip_status_check else args.expected_count
    bundle = load_bundle(
        data_root=args.data,
        status_path=status_path,
        manifest_path=args.manifest,
        images_root=args.images,
        failures_root=args.image_failures,
        image_key_prefix=args.image_key_prefix,
        image_public_base_url=args.image_public_base_url,
        expected_count=expected_count,
        skip_invalid=args.skip_invalid,
    )
    if expected_count is not None and not args.skip_invalid:
        require(
            len(bundle.products) == expected_count,
            f"loaded {len(bundle.products)} != {expected_count}",
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_sql(bundle, run_id=args.run_id), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "products": len(bundle.products),
                "images": len(bundle.images),
                "options": len(bundle.options),
                "measurements": len(bundle.measurements),
                "skipped": len(bundle.skipped),
                "image_failure_files": bundle.image_failure_files,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    for message in bundle.skipped:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
