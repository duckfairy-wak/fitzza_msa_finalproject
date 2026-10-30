import os
import sys
import json
import torch
import numpy as np
import requests
from PIL import Image
from io import BytesIO
from tqdm import tqdm
from transformers import CLIPModel, CLIPProcessor
from qdrant_client import QdrantClient
from qdrant_client.http import models
import uuid

# 사전 생성된 color_map.json 메모리 로드
COLOR_MAP_FILE = os.environ["COLOR_MAP_FILE"]
if os.path.exists(COLOR_MAP_FILE):
    with open(COLOR_MAP_FILE, "r", encoding="utf-8") as f:
        COLOR_MAP_DB = json.load(f)
else:
    print("🚨 경고: color_map.json 파일이 없습니다. generate_color_map.py를 먼저 실행하세요.")
    sys.exit(1)

def normalize_color(raw_color: str) -> str:
    return COLOR_MAP_DB.get(raw_color.lower().strip(), "etc")

def normalize_fit(raw_fit_list: list) -> str:
    if not raw_fit_list: return None
    fit_map = {"슬림": "slim", "레귤러": "regular", "보통": "regular", "루즈": "relaxed", "오버 사이즈": "oversized", "오버핏": "oversized"}
    return fit_map.get(raw_fit_list[0].strip(), None)

def extract_sellable_colors(product: dict) -> set[str]:
    """Extract active/sellable color names from option_items.

    Returns normalized lowercase strings. If no active option_items or color
    cannot be distinguished, returns an empty set indicating fallback to all.
    """
    option_items = product.get("option_items") or []
    if not option_items:
        return set()

    options = product.get("options") or []
    color_group_idx = None
    for idx, opt in enumerate(options):
        name = opt.get("name") or ""
        if any(kw in name.lower() for kw in ["컬러", "색상", "color"]):
            color_group_idx = idx
            break

    sellable = set()
    for item in option_items:
        if item.get("activated") is False:
            continue
        values = item.get("values") or []
        if not values:
            continue
        if color_group_idx is not None and color_group_idx < len(values):
            val = values[color_group_idx]
            if isinstance(val, str) and val.strip():
                sellable.add(val.strip().lower())
        else:
            for val in values:
                if isinstance(val, str) and val.strip():
                    sellable.add(val.strip().lower())
    return sellable

def filter_sellable_color_mappings(product: dict) -> list[dict]:
    """Filter color_image_mappings to only those present in sellable option_items.

    If sellable_colors is determined, only mappings matching a sellable color
    are retained. If filtering would eliminate all mappings (edge case),
    it falls back to original mappings to ensure product remains indexable.
    """
    mappings = product.get("color_image_mappings") or []
    if not mappings:
        return []

    sellable_colors = extract_sellable_colors(product)
    if not sellable_colors:
        return mappings

    filtered = [
        m for m in mappings
        if isinstance(m.get("color_raw"), str)
        and m["color_raw"].strip().lower() in sellable_colors
    ]

    return filtered if filtered else mappings

class FashionCLIPRunner:
    def __init__(self, model_name="patrickjohncyh/fashion-clip"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f">> Fashion-CLIP 모델 로딩 중... (Device: {self.device})")
        revision = os.environ["MODEL_REVISION"]
        self.model = CLIPModel.from_pretrained(model_name, revision=revision).to(self.device)
        self.processor = CLIPProcessor.from_pretrained(model_name, revision=revision)
        self.model.eval()

    def encode_images(self, pil_images, batch_size=16):
        embeddings = []
        for i in range(0, len(pil_images), batch_size):
            batch = pil_images[i:i + batch_size]
            inputs = self.processor(images=batch, return_tensors="pt", padding=True).to(self.device)

            with torch.no_grad():
                feats = self.model.get_image_features(**inputs)
                if hasattr(feats, "pooler_output") and feats.pooler_output is not None:
                    feats = feats.pooler_output
                elif hasattr(feats, "last_hidden_state"):
                    feats = feats.last_hidden_state[:, 0, :]

                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
                embeddings.extend(feats.cpu().numpy())
        return np.array(embeddings)

# 상품 실측에 따른 정규화 함수
def normalize_measurements(category_name: str, raw_measurements: dict) -> dict:
    mapped = {}
    if category_name in ["상의", "아우터"]:
        key_map = {
            "총장": "top_length",
            "어깨너비": "shoulder",
            "가슴단면": "chest",
            "소매길이": "sleeve",
            "밑단단면": "top_hem",
            "소매부리단면": "cuff",
            "암홀": "armhole"
        }
    elif category_name == "하의":
        key_map = {
            "총장": "bottom_length",
            "허리단면": "waist",
            "엉덩이단면": "hip",
            "허벅지단면": "thigh",
            "밑위": "rise",
            "밑단단면": "bottom_hem"
        }
    elif category_name == "신발":
        key_map = {
            "발길이": "foot_length",
            "발볼": "foot_width",
            "발목높이": "ankle_height",
            "굽높이": "heel_height"
        }
    elif category_name == "모자":
        key_map = {
            "머리둘레": "head_circumference",
            "챙길이": "brim_length",
            "깊이": "depth"
        }
    else:
        key_map = {}

    for k, v in raw_measurements.items():
        en_key = key_map.get(k)
        if en_key is not None:
            try:
                val = float(v)
                if val > 0.0:
                    mapped[en_key] = val
            except (ValueError, TypeError):
                pass
    return mapped


def make_payload(p, img_url, raw_color, norm_color):
    # 카테고리
    logical_cat = p.get("dataset", {}).get("logical_category")
    if logical_cat not in ["상의", "하의", "아우터", "모자", "신발"]:
        raise ValueError("Unknown product category")

    # 계절감
    season_candidates = p.get("season", {}).get("primary_candidates", [])

    # 상품 실측
    raw_measurements_list = p.get("size", {}).get("measurements", [])
    normalized_sizes = []
    for size_item in raw_measurements_list:
        norm_m = normalize_measurements(logical_cat, size_item.get("measurements", {}))
        if norm_m:
            normalized_sizes.append({"size": size_item.get("size"), "sequence": size_item.get("sequence", 0), "measurements": norm_m})

    payload = {
        "product_id": int(p["product_id"]),
        "product_name": p.get("name", ""),
        "brand_name": p.get("brand", {}).get("name", ""),
        "category": logical_cat,
        "subcategory": p.get("category", {}).get("categoryDepth2Title", ""),
        "price": int(p.get("price", {}).get("normal", 0)),
        "season_candidates": season_candidates,
        "color_raw": raw_color,
        "color_normalized": [norm_color],
        "features": p.get("features", {}),
        "sizes": normalized_sizes,
        "image_url": img_url,
        "product_url": p.get("source_url", "")
    }


    return payload


def load_image(url):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"image.msscdn.net", "image.musinsa.com", "image.musinsa.co.kr"}:
        raise ValueError("Unapproved image host")
    with requests.get(url, timeout=(5, 30), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Image response must be 200")
        content = bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MiB")
    with Image.open(BytesIO(content)) as image:
        if image.width * image.height > 20_000_000:
            raise ValueError("Image dimensions exceed limit")
        return image.convert("RGB")


def main():
    collection = os.environ["QDRANT_COLLECTION_NAME"]
    if not collection.startswith("pipeline_staging_"):
        raise ValueError("Only staging collections are allowed")
    data_root = os.environ["DATA_ROOT"]
    products = []
    for root, _, names in os.walk(data_root):
        for name in sorted(names):
            if name.endswith(".json"):
                with open(os.path.join(root, name), encoding="utf-8") as file:
                    products.append(json.load(file))
    if not products:
        raise ValueError("No product data")
    client = QdrantClient(url=os.environ["QDRANT_URL"], timeout=60)
    if client.collection_exists(collection):
        raise ValueError("Existing collections are never deleted or overwritten")
    runner = FashionCLIPRunner()
    client.create_collection(collection_name=collection,
        vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE))
    records, images = [], []
    point_count = 0
    indexed_products = set()

    def flush():
        nonlocal point_count
        if not images:
            return
        try:
            vectors = runner.encode_images(images, batch_size=4)
            if vectors.shape != (len(images), 512) or not np.isfinite(vectors).all():
                raise ValueError("Invalid embedding shape or values")
            points = []
            for (p, url, raw, color), vector in zip(records, vectors):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{p['product_id']}_{raw.strip().lower()}_{url}"))
                points.append(models.PointStruct(id=point_id, vector=vector.tolist(),
                    payload=make_payload(p, url, raw, color)))
            client.upsert(collection_name=collection, points=points, wait=True)
            point_count += len(points)
            indexed_products.update(str(p["product_id"]) for p, _, _, _ in records)
        finally:
            for image in images:
                image.close()
            records.clear()
            images.clear()

    try:
        for product in products:
            mappings = filter_sellable_color_mappings(product)
            if not mappings:
                raise ValueError("Product missing color-image mappings")
            for mapping in mappings:
                raw = mapping["color_raw"]
                key = raw.strip().lower()
                if key not in COLOR_MAP_DB:
                    raise ValueError("Unmapped color")
                url = mapping["image_url"]
                images.append(load_image(url))
                records.append((product, url, raw, COLOR_MAP_DB[key]))
                if len(images) == 4:
                    flush()
        flush()
    finally:
        for image in images:
            image.close()
    count = client.count(collection_name=collection, exact=True).count
    if count != point_count or len(indexed_products) != len(products):
        raise ValueError("Post-upsert point/product count mismatch")
    print(json.dumps({"points": count, "products": len(indexed_products),
                      "collection": collection, "serving_switched": False}))


if __name__ == "__main__":
    main()
