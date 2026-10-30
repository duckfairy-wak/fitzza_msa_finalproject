import concurrent.futures
import json
import sys
import time
from collections import Counter, defaultdict
import boto3

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BUCKET = "fitzza-prod-foundation-databucket-wwng6wfc0hqy"
PREFIX = "pipeline/runs/collection-20261025-01/curated/data/"

def get_all_s3_keys(s3, bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                keys.append(obj["Key"])
    return keys

def inspect_single_object(s3, bucket, key):
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode("utf-8")
        data = json.loads(body)
        
        top_keys = tuple(sorted(data.keys()))
        has_product_id = bool(data.get("product_id"))
        has_name = bool(data.get("name"))
        has_price = bool(data.get("price"))
        
        cat = data.get("category") or {}
        cat_depth1 = cat.get("categoryDepth1Title") or cat.get("categoryDepth1Name") or "NONE"
        cat_depth2 = cat.get("categoryDepth2Title") or cat.get("categoryDepth2Name") or "NONE"
        
        price_obj = data.get("price")
        price_valid = isinstance(price_obj, dict) and "current" in price_obj
        
        size_obj = data.get("size")
        size_valid = size_obj is not None
        
        return {
            "status": "OK",
            "key": key,
            "top_keys": top_keys,
            "has_product_id": has_product_id,
            "has_name": has_name,
            "has_price": has_price,
            "price_valid": price_valid,
            "cat_depth1": cat_depth1,
            "cat_depth2": cat_depth2,
            "size_valid": size_valid,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "key": key,
            "error": f"{type(exc).__name__}: {exc}",
        }

def main():
    print("=" * 80, flush=True)
    print("🔍 [AWS S3] curated 3,002개 상품 JSON 전수 정합성 검증 시작", flush=True)
    print(f"   - 버킷: {BUCKET}", flush=True)
    print(f"   - 프리픽스: {PREFIX}", flush=True)
    print("=" * 80, flush=True)

    start_time = time.perf_counter()
    session = boto3.Session(profile_name="fitzza", region_name="ap-northeast-2")
    s3 = session.client("s3")

    print("[1] S3 대상 JSON 파일 목록 수집 중...", flush=True)
    keys = get_all_s3_keys(s3, BUCKET, PREFIX)
    total_files = len(keys)
    print(f"   ➔ 총 대상 JSON 파일 수: {total_files:,}개", flush=True)

    if total_files == 0:
        print("🚨 대상 JSON 파일이 없습니다.", flush=True)
        return

    print(f"\n[2] {total_files:,}개 파일 고속 병렬 다운로드 & 스키마 검증 중 (MaxWorkers=50)...", flush=True)
    
    results = []
    schema_patterns = Counter()
    cat_depth1_dist = Counter()
    cat_depth2_dist = Counter()
    errors = []
    missing_fields = defaultdict(int)

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        def task(k):
            return inspect_single_object(s3, BUCKET, k)

        futures = [executor.submit(task, k) for k in keys]
        done_count = 0
        for future in concurrent.futures.as_completed(futures):
            done_count += 1
            if done_count % 300 == 0 or done_count == total_files:
                print(f"   - 진행도: {done_count:,} / {total_files:,} ({done_count/total_files*100:.1f}%)", flush=True)
            
            res = future.result()
            results.append(res)
            if res["status"] == "ERROR":
                errors.append(res)
            else:
                schema_patterns[res["top_keys"]] += 1
                cat_depth1_dist[res["cat_depth1"]] += 1
                cat_depth2_dist[res["cat_depth2"]] += 1
                if not res["has_product_id"]:
                    missing_fields["product_id"] += 1
                if not res["has_name"]:
                    missing_fields["name"] += 1
                if not res["has_price"]:
                    missing_fields["price"] += 1
                if not res["price_valid"]:
                    missing_fields["price.current"] += 1

    elapsed = time.perf_counter() - start_time

    print("\n" + "=" * 80, flush=True)
    print("📊 [S3 상품 JSON 전수 검증 종합 결과 리포트]", flush=True)
    print("=" * 80, flush=True)
    print(f"⏱️ 총 소요 시간: {elapsed:.2f}초 (초당 {total_files/elapsed:.1f}개 파일 분석)", flush=True)
    print(f"📁 총 검증 파일 수: {total_files:,}개", flush=True)
    print(f"✅ 정상 파싱 성공 : {total_files - len(errors):,}개 ({(total_files - len(errors))/total_files*100:.2f}%)", flush=True)
    print(f"❌ 파싱/접근 에러  : {len(errors):,}개", flush=True)

    if errors:
        print("\n🚨 [에러 발생 파일 샘플 (최대 5건)]:", flush=True)
        for err in errors[:5]:
            print(f"   - {err['key']}: {err.get('error')}", flush=True)

    print(f"\n🧩 [최상위 필드 스키마 일치도]", flush=True)
    print(f"   - 식별된 스키마 패턴 종류 수: {len(schema_patterns)}가지", flush=True)
    pattern_idx = 1
    for keys_tuple, count in schema_patterns.most_common():
        pct = count / total_files * 100.0
        print(f"   📌 [패턴 #{pattern_idx}] ({count:,}개 상품, 전체의 {pct:.2f}% 점유):", flush=True)
        print(f"      필드 개수: {len(keys_tuple)}개", flush=True)
        print(f"      필드 목록: {list(keys_tuple)}", flush=True)
        pattern_idx += 1

    print(f"\n🏷️ [대분류 카테고리(categoryDepth1) 분포]", flush=True)
    for cat, count in cat_depth1_dist.most_common():
        print(f"   - {cat:10s}: {count:,}개 ({count/total_files*100:.2f}%)", flush=True)

    print(f"\n🏷️ [주요 중분류 카테고리(categoryDepth2) 상위 10개]", flush=True)
    for subcat, count in cat_depth2_dist.most_common(10):
        print(f"   - {subcat:20s}: {count:,}개 ({count/total_files*100:.2f}%)", flush=True)

    print(f"\n⚠️ [필수 필드 결측치(Missing) 현황]", flush=True)
    if not missing_fields:
        print("   ✅ 모든 파일에서 product_id, name, price, price.current 등 핵심 필드 결측 0건 (완벽!)", flush=True)
    else:
        for f, cnt in missing_fields.items():
            print(f"   - {f}: {cnt:,}건 누락", flush=True)

    print("=" * 80, flush=True)

if __name__ == "__main__":
    main()
