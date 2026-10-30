import concurrent.futures
import os
import shutil
import sys
import time
import boto3

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BUCKET = "fitzza-prod-foundation-databucket-wwng6wfc0hqy"
PREFIX = "pipeline/runs/collection-20261025-01/curated/data/"

# S3 한글 대분류 폴더 -> 로컬 영문 폴더 매핑
CATEGORY_FOLDER_MAP = {
    "상의": "top",
    "하의": "bottom",
    "신발": "shoes",
    "아우터": "outer",
    "모자": "hat",
}

BASE_LOCAL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../product-service/src/main/resources/final_products")
)

def get_all_s3_objects(s3, bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json"):
                # 예: pipeline/runs/collection-20261025-01/curated/data/상의/12345.json
                parts = key[len(prefix):].split("/", 1)
                if len(parts) == 2:
                    cat_ko, filename = parts
                    objects.append((key, cat_ko, filename))
    return objects

def download_file(s3, bucket, key, local_path):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    s3.download_file(bucket, key, local_path)

def main():
    print("=" * 80)
    print("🚀 [AWS S3 -> Local] 3,000개 상품 JSON 로컬 동기화 시작")
    print(f"   - S3 버킷: {BUCKET}")
    print(f"   - S3 경로: {PREFIX}")
    print(f"   - 로컬 대상: {BASE_LOCAL_DIR}")
    print("=" * 80)

    start_time = time.perf_counter()
    session = boto3.Session(profile_name="fitzza", region_name="ap-northeast-2")
    s3 = session.client("s3")

    print("[1] S3 대상 파일 목록 수집 중...")
    items = get_all_s3_objects(s3, BUCKET, PREFIX)
    total_files = len(items)
    print(f"   ➔ 총 대상 파일: {total_files:,}개")

    if total_files != 3000:
        print(f"⚠️ 경고: 수집된 파일 수가 3,000개가 아닙니다 ({total_files}개). 계속 진행합니다.")

    # 기존 'cap' 폴더가 남아있다면 'hat'으로 일원화하기 위해 정리
    old_cap_dir = os.path.join(BASE_LOCAL_DIR, "cap")
    if os.path.exists(old_cap_dir):
        print(f"[2] 기존 중복/분리 cap 폴더 정리: {old_cap_dir}")
        shutil.rmtree(old_cap_dir)

    print(f"\n[3] {total_files:,}개 파일 고속 병렬 다운로드 시작 (MaxWorkers=50)...")
    success_count = 0
    fail_count = 0
    cat_counts = {folder: 0 for folder in CATEGORY_FOLDER_MAP.values()}

    def worker_task(item):
        key, cat_ko, filename = item
        target_folder = CATEGORY_FOLDER_MAP.get(cat_ko, cat_ko)
        local_dest = os.path.join(BASE_LOCAL_DIR, target_folder, filename)
        download_file(s3, BUCKET, key, local_dest)
        return target_folder

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(worker_task, item) for item in items]
        done_count = 0
        for future in concurrent.futures.as_completed(futures):
            done_count += 1
            if done_count % 300 == 0 or done_count == total_files:
                print(f"   - 다운로드 진행도: {done_count:,} / {total_files:,} ({done_count/total_files*100:.1f}%)", flush=True)
            try:
                target_folder = future.result()
                success_count += 1
                cat_counts[target_folder] += 1
            except Exception as exc:
                fail_count += 1
                print(f"🚨 다운로드 실패: {exc}", flush=True)

    elapsed = time.perf_counter() - start_time
    print("\n" + "=" * 80)
    print("🎉 [다운로드 완료 요약]")
    print(f"   - 총 소요 시간: {elapsed:.2f}초")
    print(f"   - 성공 건수: {success_count:,}개")
    print(f"   - 실패 건수: {fail_count}개")
    print("\n[카테고리별 다운로드 현황]")
    for folder, count in sorted(cat_counts.items()):
        print(f"   - {folder:8s}: {count:,}개")
    print("=" * 80)

if __name__ == "__main__":
    main()
