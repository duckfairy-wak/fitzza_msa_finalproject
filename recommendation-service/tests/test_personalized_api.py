from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.recommendation import PersonalizedProductItem
from app.services.user_history_service import UserActionHistory


def _make_80_dummy_items() -> list[PersonalizedProductItem]:
    categories = ["상의", "하의", "아우터", "신발", "모자"]
    items = []
    pid = 1000
    for round_idx in range(16):
        for cat in categories:
            items.append(
                PersonalizedProductItem(
                    productId=pid,
                    productName=f"테스트 상품 {pid}",
                    brandName="무신사 스탠다드",
                    price=39000,
                    thumbnailUrl=f"https://img.msscdn.net/{pid}.jpg",
                    status="ON_SALE",
                    category=cat,
                    wished=(pid % 2 == 0),
                )
            )
            pid += 1
    return items


@pytest.fixture
def client_with_mock_services():
    # Mock Redis client
    mock_redis = MagicMock()
    mock_redis.is_available = True
    cache_store = {}

    def fake_get(key):
        return cache_store.get(key)

    def fake_set(key, val, ttl_seconds=None):
        cache_store[key] = val
        return True

    def fake_delete(key):
        return cache_store.pop(key, None) is not None

    mock_redis.get.side_effect = fake_get
    mock_redis.set.side_effect = fake_set
    mock_redis.delete.side_effect = fake_delete

    # Feed Service with real paging & caching, mock generation
    from app.services.personalized_feed_service import PersonalizedFeedService

    feed_service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        collection_name="test",
    )
    dummy_80_items = _make_80_dummy_items()
    feed_service.generate_personalized_feed_items = AsyncMock(
        return_value=(dummy_80_items, UserActionHistory(user_id=10))
    )

    # State 주입
    from app.core.config import get_settings
    from app.services.cache_service import CacheService

    settings = get_settings()
    cache_service = CacheService(redis_client=mock_redis, settings=settings)

    app.state.redis_client = mock_redis
    app.state.cache_service = cache_service
    app.state.personalized_feed_service = feed_service

    test_client = TestClient(app)
    return test_client, feed_service, cache_store



def test_get_personalized_feed_guest_cold_start(client_with_mock_services):
    """비로그인(게스트) 시 200 OK와 함께 80개 중 첫 20개 반환 및 페이징 메타데이터 검증"""
    client, mock_feed_service, _ = client_with_mock_services

    resp = client.get("/api/recommendations/personalized")
    assert resp.status_code == 200

    data = resp.json()
    assert data["page"] == 0
    assert data["size"] == 20
    assert data["totalElements"] == 80
    assert data["totalPages"] == 4
    assert data["hasNext"] is True
    assert len(data["content"]) == 20
    assert data["content"][0]["productId"] == 1000
    assert data["content"][0]["category"] == "상의"

    # 게스트(user_id=0)로 피드 생성기 호출되었는지 확인
    mock_feed_service.generate_personalized_feed_items.assert_called_once_with(user_id=0)


def test_get_personalized_feed_pagination(client_with_mock_services):
    """page 0~3 무한 스크롤 및 page 4 초과 요청 처리 검증"""
    client, mock_feed_service, _ = client_with_mock_services

    # Page 0 (1~20번)
    resp0 = client.get("/api/recommendations/personalized?page=0&size=20", headers={"X-User-Id": "10"})
    assert resp0.status_code == 200
    d0 = resp0.json()
    assert len(d0["content"]) == 20
    assert d0["hasNext"] is True
    assert d0["content"][0]["productId"] == 1000

    # Page 1 (21~40번)
    resp1 = client.get("/api/recommendations/personalized?page=1&size=20", headers={"X-User-Id": "10"})
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert len(d1["content"]) == 20
    assert d1["hasNext"] is True
    assert d1["content"][0]["productId"] == 1020

    # Page 3 (61~80번, 마지막 페이지)
    resp3 = client.get("/api/recommendations/personalized?page=3&size=20", headers={"X-User-Id": "10"})
    assert resp3.status_code == 200
    d3 = resp3.json()
    assert len(d3["content"]) == 20
    assert d3["hasNext"] is False  # 마지막 페이지이므로 False

    # Page 4 (범위 초과 페이지)
    resp4 = client.get("/api/recommendations/personalized?page=4&size=20", headers={"X-User-Id": "10"})
    assert resp4.status_code == 200
    d4 = resp4.json()
    assert len(d4["content"]) == 0
    assert d4["hasNext"] is False


def test_get_personalized_feed_caching_and_refresh(client_with_mock_services):
    """Redis 캐싱 적중 및 refresh=true에 의한 강제 무효화 동작 검증"""
    client, mock_feed_service, cache_store = client_with_mock_services

    # 1. 첫 번째 호출 (캐시 미스 -> 피드 생성기 호출 및 캐시 저장)
    resp1 = client.get("/api/recommendations/personalized", headers={"X-User-Id": "77"})
    assert resp1.status_code == 200
    assert mock_feed_service.generate_personalized_feed_items.call_count == 1
    assert "feed:77" in cache_store

    # 2. 두 번째 호출 (캐시 히트 -> 피드 생성기 호출 안 됨)
    resp2 = client.get("/api/recommendations/personalized", headers={"X-User-Id": "77"})
    assert resp2.status_code == 200
    assert mock_feed_service.generate_personalized_feed_items.call_count == 1  # 여전히 1회

    # 3. refresh=true 호출 (캐시 무효화 후 재생성 -> 피드 생성기 재호출)
    resp3 = client.get("/api/recommendations/personalized?refresh=true", headers={"X-User-Id": "77"})
    assert resp3.status_code == 200
    assert mock_feed_service.generate_personalized_feed_items.call_count == 2  # 2회로 증가


def test_get_personalized_feed_gateway_v1_path(client_with_mock_services):
    """게이트웨이 하위 호환 경로 /api/v1/recommendations/personalized 동작 검증"""
    client, _, _ = client_with_mock_services

    resp = client.get("/api/v1/recommendations/personalized")
    assert resp.status_code == 200
    assert resp.json()["totalElements"] == 80


def test_get_personalized_feed_guest_refresh_protection(client_with_mock_services):
    """게스트는 refresh=true를 호출해도 공용 캐시가 삭제되지 않고 유지되는지 검증"""
    client, feed_service, cache_store = client_with_mock_services

    # 1. 게스트 첫 호출 (캐시 미스 -> 생성기 1회 호출)
    resp1 = client.get("/api/recommendations/personalized")
    assert resp1.status_code == 200
    assert feed_service.generate_personalized_feed_items.call_count == 1
    assert "feed:guest" in cache_store

    # 2. 게스트 refresh=true 호출 -> 공용 캐시 보호로 삭제되지 않고 생성기 재호출 없음
    resp2 = client.get("/api/recommendations/personalized?refresh=true")
    assert resp2.status_code == 200
    assert feed_service.generate_personalized_feed_items.call_count == 1  # 여전히 1회
    assert "feed:guest" in cache_store

