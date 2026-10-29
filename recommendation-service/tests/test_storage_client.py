"""recommendation-service StorageClient 단위 테스트."""

import time
from unittest.mock import MagicMock, patch
import pytest

from app.clients.storage_client import (
    StorageClient,
    get_storage_client,
    set_storage_client,
)
from app.core.config import Settings


@pytest.fixture(autouse=True)
def reset_storage_client_singleton():
    """테스트 후 싱글톤 상태를 원복하는 픽스처."""
    set_storage_client(None)
    yield
    set_storage_client(None)


def test_storage_client_backend_flags():
    s_local = StorageClient(Settings(storage_backend="local"))
    assert not s_local.is_s3

    s_s3 = StorageClient(Settings(storage_backend="s3"))
    assert s_s3.is_s3

    s_aws = StorageClient(Settings(storage_backend="aws"))
    assert s_aws.is_s3


def test_extract_s3_key():
    client = StorageClient(Settings(aws_s3_bucket_name="my-bucket"))

    # 단순 S3 객체 키
    assert client._extract_s3_key("pipeline/runs/01/images/1.jpg") == "pipeline/runs/01/images/1.jpg"
    assert client._extract_s3_key("/pipeline/runs/01/images/1.jpg") == "pipeline/runs/01/images/1.jpg"

    # S3 엔드포인트/버킷 포함 URL
    url_with_bucket = "http://localhost:4566/my-bucket/pipeline/runs/01/images/1.jpg"
    assert client._extract_s3_key(url_with_bucket) == "pipeline/runs/01/images/1.jpg"

    # 가상 호스팅 스타일 S3 URL
    virtual_url = "https://my-bucket.s3.ap-northeast-2.amazonaws.com/pipeline/runs/01/images/1.jpg"
    assert client._extract_s3_key(virtual_url) == "pipeline/runs/01/images/1.jpg"


def test_get_presigned_url_empty_or_none():
    client = StorageClient(Settings(storage_backend="s3"))
    assert client.get_presigned_url(None) == ""
    assert client.get_presigned_url("") == ""
    assert client.get_presigned_url("   ") == ""


def test_get_presigned_url_bypasses_external_musinsa_url():
    client = StorageClient(Settings(storage_backend="s3", aws_s3_bucket_name="fitzza-prod-assets"))
    musinsa_url = "https://image.msscdn.net/images/goods_img/20231012/1234/1234_1_500.jpg"
    # 외부 CDN URL은 S3 서명을 시도하지 않고 원본 그대로 유지해야 함
    result = client.get_presigned_url(musinsa_url)
    assert result == musinsa_url


def test_get_presigned_url_local_backend_fallback():
    client = StorageClient(Settings(storage_backend="local"))
    s3_key = "pipeline/runs/01/images/products/101/001.png"
    # 로컬 모드에서는 원본 키/경로를 그대로 반환
    assert client.get_presigned_url(s3_key) == s3_key


def test_get_presigned_url_cloudfront_cdn_priority():
    settings = Settings(
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-prod-assets",
        cloudfront_domain="https://cdn.fitzza.com",
    )
    client = StorageClient(settings)
    s3_key = "pipeline/runs/01/images/products/101/001.png"

    # CloudFront 설정 시 서명 대신 CDN 캐시 URL 반환
    result = client.get_presigned_url(s3_key)
    assert result == "https://cdn.fitzza.com/pipeline/runs/01/images/products/101/001.png"


def test_get_presigned_url_s3_signing_and_in_memory_cache():
    settings = Settings(
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-prod-assets",
        cloudfront_domain="",
    )
    client = StorageClient(settings)

    mock_boto_s3 = MagicMock()
    mock_boto_s3.generate_presigned_url.return_value = (
        "https://fitzza-prod-assets.s3.ap-northeast-2.amazonaws.com/test.png?X-Amz-Signature=abc"
    )
    client._s3_client = mock_boto_s3

    s3_key = "pipeline/runs/01/images/products/101/001.png"

    # 1회차 호출: generate_presigned_url 호출됨
    res1 = client.get_presigned_url(s3_key, expires_in=3600)
    assert "X-Amz-Signature=abc" in res1
    assert mock_boto_s3.generate_presigned_url.call_count == 1

    # 2회차 호출: 인메모리 캐시 히트로 boto3 추가 호출 없음
    res2 = client.get_presigned_url(s3_key, expires_in=3600)
    assert res2 == res1
    assert mock_boto_s3.generate_presigned_url.call_count == 1


def test_get_presigned_url_exception_handling_falls_back_gracefully():
    settings = Settings(
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-prod-assets",
    )
    client = StorageClient(settings)

    mock_boto_s3 = MagicMock()
    mock_boto_s3.generate_presigned_url.side_effect = RuntimeError("AWS Network Failure")
    client._s3_client = mock_boto_s3

    s3_key = "pipeline/runs/01/images/products/101/001.png"
    # 예외가 발생해도 서비스를 중단시키지 않고 원본 키를 안전하게 fallback
    result = client.get_presigned_url(s3_key)
    assert result == s3_key


def test_singleton_get_and_set_storage_client():
    initial = get_storage_client()
    assert initial is not None
    assert get_storage_client() is initial

    custom = StorageClient(Settings(storage_backend="s3", aws_s3_bucket_name="custom-bucket"))
    set_storage_client(custom)
    assert get_storage_client() is custom


def test_recommendation_detail_service():
    from app.services.recommendation_detail_service import RecommendationDetailService

    mock_storage = MagicMock()
    mock_storage.get_presigned_url.side_effect = lambda k: f"https://signed.example.com/{k}" if k else None

    service = RecommendationDetailService(storage_client=mock_storage)

    record = {
        "requestId": 999,
        "userId": 42,
        "queryText": "미니멀 코디",
        "status": "DONE",
        "searchType": "TEXT",
        "tpoSummary": "데이트룩",
        "message": "추천 완료",
        "items": [
            {
                "productId": 101,
                "productName": "니트",
                "price": 45000,
                "imageUrl": "pipeline/runs/01/images/products/101/0.jpg",
            }
        ],
        "combos": [
            {
                "comboId": 1,
                "totalPrice": 45000,
                "passStatus": "PASS",
                "harmonyScore": 95.0,
                "feedbackSummary": "조화로운 매칭",
                "budgetExceeded": False,
                "items": [
                    {
                        "productId": 101,
                        "productName": "니트",
                        "price": 45000,
                        "imageUrl": "pipeline/runs/01/images/products/101/0.jpg",
                    }
                ],
            }
        ],
    }

    res = service.build_detail_response(record)
    assert res.requestId == 999
    assert res.items[0].imageUrl == "https://signed.example.com/pipeline/runs/01/images/products/101/0.jpg"
    assert res.combos[0].items[0].imageUrl == "https://signed.example.com/pipeline/runs/01/images/products/101/0.jpg"

    combo_record = {
        "comboId": 1,
        "userId": 42,
        "totalPrice": 45000,
        "feedbackSummary": "굿",
        "items": [
            {
                "productId": 101,
                "productName": "니트",
                "price": 45000,
                "imageUrl": "pipeline/runs/01/images/products/101/0.jpg",
            }
        ],
    }
    internal_res = service.build_internal_combo_response(combo_record)
    assert internal_res.owned is True
    assert internal_res.items[0].imageUrl == "https://signed.example.com/pipeline/runs/01/images/products/101/0.jpg"
