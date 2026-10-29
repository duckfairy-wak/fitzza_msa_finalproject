"""S3에 계산 완료된 Fashion-CLIP 벡터를 로컬 Qdrant로 일괄 임포트하는 자동화 스크립트.

사용법:
    python scripts/import_s3_vectors_to_local_qdrant.py [--profile fitzza] [--qdrant-url http://localhost:6333]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from qdrant_client import QdrantClient
from qdrant_client.http import models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_BUCKET = "fitzza-prod-foundation-databucket-wwng6wfc0hqy"
DEFAULT_VECTOR_RUN_PREFIX = "pipeline/vector-runs/collection-20261025-01-fclip-01"
DEFAULT_COLLECTION = "pipeline_staging_s3_crawled_v1"
DEFAULT_ALIAS = "musinsa_products"
DEFAULT_REGION = "ap-northeast-2"
DEFAULT_PROFILE = "fitzza"
DEFAULT_QDRANT_URL = "http://localhost:6333"
PART_COUNT = 27  # part-00000.jsonl ~ part-00026.jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="S3에 저장된 벡터 런 데이터를 로컬 Docker Qdrant로 임포트합니다."
    )
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="S3 버킷 이름")
    parser.add_argument(
        "--prefix",
        default=DEFAULT_VECTOR_RUN_PREFIX,
        help="S3 벡터 런 경로 접두사",
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help="Qdrant 서버 URL (기본값: http://localhost:6333)",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="적재할 Qdrant 컬렉션 이름",
    )
    parser.add_argument(
        "--alias",
        default=DEFAULT_ALIAS,
        help="서비스가 바라볼 Qdrant 별칭 (기본값: musinsa_products)",
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="AWS 리전")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="AWS CLI 프로필")
    return parser


def import_vectors(args: argparse.Namespace) -> int:
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        s3 = session.client("s3")
    except ProfileNotFound:
        logger.warning(
            "AWS 프로필 '%s'을 찾을 수 없어 기본 자격 증명으로 연결을 시도합니다.",
            args.profile,
        )
        session = boto3.Session(region_name=args.region)
        s3 = session.client("s3")

    logger.info("로컬 Qdrant 연결 확인 중: %s", args.qdrant_url)
    try:
        client = QdrantClient(url=args.qdrant_url, timeout=60)
        client.get_collections()
    except Exception as exc:
        logger.error("Qdrant 연결 실패 (%s): %s. Docker Qdrant가 켜져 있는지 확인하세요.", args.qdrant_url, exc)
        return 1

    if client.collection_exists(args.collection):
        logger.info("기존 컬렉션 '%s' 삭제 후 새로 생성합니다.", args.collection)
        client.delete_collection(args.collection)

    client.create_collection(
        collection_name=args.collection,
        vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE),
    )
    logger.info("새 컬렉션 '%s' 생성 완료 (512차원, Cosine)", args.collection)

    total_upserted = 0
    for idx in range(PART_COUNT):
        part_key = f"{args.prefix}/embeddings/part-{idx:05d}.jsonl"
        try:
            obj = s3.get_object(Bucket=args.bucket, Key=part_key)
            lines = obj["Body"].read().decode("utf-8").splitlines()
        except (BotoCoreError, ClientError) as exc:
            logger.error("S3 파일 읽기 실패 (%s): %s", part_key, exc)
            return 1

        points: list[models.PointStruct] = []
        for line in lines:
            if not line.strip():
                continue
            rec = json.loads(line)
            payload = rec.get("payload") or {}
            # S3 Object Key를 우선하여 image_url에 매핑
            if payload.get("image_key"):
                payload["image_url"] = payload["image_key"]
            points.append(
                models.PointStruct(
                    id=rec["point_id"],
                    vector=rec["vector"],
                    payload=payload,
                )
            )

        if points:
            client.upsert(collection_name=args.collection, points=points, wait=True)
            total_upserted += len(points)
            logger.info("Part %02d/%02d 적재 완료 (+%d개, 누적: %d개)", idx + 1, PART_COUNT, len(points), total_upserted)

    # Alias 연결
    if args.alias:
        existing_aliases = [a.alias_name for a in client.get_aliases().aliases]
        operations: list[Any] = []
        if args.alias in existing_aliases:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=args.alias)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=args.collection,
                    alias_name=args.alias,
                )
            )
        )
        client.update_collection_aliases(change_aliases_operations=operations)
        logger.info("Alias 연결 완료: %s -> %s", args.alias, args.collection)

    final_count = client.count(args.collection).count
    logger.info("🎉 모든 벡터 적재 완료! 총 포인트 수: %d개", final_count)
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    code = import_vectors(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
