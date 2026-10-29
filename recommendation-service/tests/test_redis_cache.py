from typing import Any
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from app.clients.redis_client import RedisClient
from app.core.config import Settings
from app.core.database import RecommendationRepository
from app.main import app
from app.services.cache_service import CacheService
from app.services.search_engine import FashionSearchEngine

COMMUNITY_TOKEN = "test-only-community-service-token-32b"
PRODUCT_TOKEN = "test-only-product-service-token-32b!"
REVIEW_TOKEN = "test-only-review-service-token-32-b!"
RECOMMENDATION_TOKEN = "test-only-recommendation-token-32-b!"



class StubCoordinator:
    def __init__(self) -> None:
        self.call_count = 0

    def run(self, user_query: str, user_id: str = "user_001") -> dict[str, Any]:
        self.call_count += 1
        return {
            "type": "single",
            "query": user_query,
            "tpo": "테스트 TPO",
            "comment": "테스트 코멘트",
            "results": [
                {
                    "product_id": 999,
                    "product_name": "캐시 테스트 상품",
                    "price": 29000,
                    "color_raw": "블랙",
                    "size_recommendation": {"size_label": "M", "predicted_fit_score": 0.9},
                }
            ],
        }


class StubNotificationClient:
    def send_recommendation_done(self, *args: Any, **kwargs: Any) -> bool:
        return True


class StubUserClient:
    def get_user_body(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"height": 178.0, "weight": 70.0}


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_client(fake_redis: fakeredis.FakeRedis) -> RedisClient:
    settings = Settings(redis_enabled=True, redis_ttl_seconds=3600)
    return RedisClient(settings=settings, redis_instance=fake_redis)


@pytest.fixture
def cache_service(redis_client: RedisClient) -> CacheService:
    settings = Settings(redis_enabled=True, redis_ttl_seconds=3600)
    return CacheService(redis_client=redis_client, settings=settings)


# ---------------------------------------------------------
# 1. RedisClient Unit Tests
# ---------------------------------------------------------

def test_redis_client_basic_crud(redis_client: RedisClient) -> None:
    assert redis_client.is_available is True
    assert redis_client.ping() is True

    # set and get
    assert redis_client.set("sample_key", {"name": "item", "val": 123}) is True
    data = redis_client.get("sample_key")
    assert data == {"name": "item", "val": 123}

    # exists
    assert redis_client.exists("sample_key") is True
    assert redis_client.exists("unknown_key") is False

    # delete
    assert redis_client.delete("sample_key") is True
    assert redis_client.get("sample_key") is None


def test_redis_client_delete_pattern(redis_client: RedisClient) -> None:
    redis_client.set("user:1:pref", "val1")
    redis_client.set("user:1:body", "val2")
    redis_client.set("user:2:pref", "val3")

    deleted = redis_client.delete_pattern("user:1:*")
    assert deleted == 2
    assert redis_client.get("user:1:pref") is None
    assert redis_client.get("user:2:pref") == "val3"


def test_redis_client_disabled_mode() -> None:
    settings = Settings(redis_enabled=False)
    client = RedisClient(settings=settings)
    assert client.is_available is False
    assert client.ping() is False
    assert client.get("any_key") is None
    assert client.set("any_key", "val") is False
    assert client.delete("any_key") is False
    assert client.exists("any_key") is False
    assert client.delete_pattern("any:*") == 0


def test_redis_client_graceful_fallback_on_network_error() -> None:
    mock_redis = MagicMock()
    mock_redis.get.side_effect = redis.ConnectionError("Connection refused")
    mock_redis.set.side_effect = redis.TimeoutError("Timeout")

    settings = Settings(redis_enabled=True)
    client = RedisClient(settings=settings, redis_instance=mock_redis)

    # get fails gracefully
    assert client.get("broken_key") is None
    # upon connection error, circuit opens and client becomes unavailable
    assert client.is_available is False

    # subsequent set fails gracefully without exception
    assert client.set("broken_key", "val") is False

    # Cooldown expires: client automatically becomes available again for probe/recovery
    client._circuit_open_until = 0.0
    assert client.is_available is True


def test_redis_client_initialization_with_redis_url(monkeypatch: Any) -> None:
    settings = Settings(
        redis_enabled=True,
        redis_url="redis://:secret@redis-cluster:6379/2",
    )
    with patch("redis.ConnectionPool.from_url") as mock_from_url:
        mock_pool = MagicMock()
        mock_from_url.return_value = mock_pool
        with patch("redis.Redis") as mock_redis_cls:
            client = RedisClient(settings=settings)
            mock_from_url.assert_called_once_with(
                "redis://:secret@redis-cluster:6379/2",
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_timeout,
                decode_responses=True,
            )
            mock_redis_cls.assert_called_once_with(connection_pool=mock_pool)
            assert client.is_available is True



# ---------------------------------------------------------
# 2. CacheService Unit Tests
# ---------------------------------------------------------

def test_cache_service_pipeline_results(cache_service: CacheService) -> None:
    user_query = "주말 미니멀 룩 추천해줘"
    user_id = "user_10"
    result_data = {"type": "single", "items": [{"id": 1}]}

    # Initially cache miss
    assert cache_service.get_pipeline_result(user_query, user_id) is None

    # Set cache
    assert cache_service.set_pipeline_result(user_query, user_id, result_data) is True

    # Cache hit
    cached = cache_service.get_pipeline_result(user_query, user_id)
    assert cached == result_data

    # Invalidate user cache
    assert cache_service.invalidate_user_pipeline(user_id) >= 1
    assert cache_service.get_pipeline_result(user_query, user_id) is None


def test_cache_service_embeddings(cache_service: CacheService) -> None:
    query = "black jacket"
    vector = [0.123, -0.456, 0.789]

    assert cache_service.get_text_embedding(query) is None
    assert cache_service.set_text_embedding(query, vector) is True
    # Case insensitivity check
    assert cache_service.get_text_embedding("BLACK JACKET") == vector


def test_cache_service_search_results(cache_service: CacheService) -> None:
    search_params = {"clip_query_en": "denim pants", "category": "bottom", "top_k": 3}
    search_results = [{"product_id": 123, "score": 0.88}]

    assert cache_service.get_search_result(search_params) is None
    assert cache_service.set_search_result(search_params, search_results) is True
    assert cache_service.get_search_result(search_params) == search_results


def test_cache_service_combo_crud(cache_service: CacheService) -> None:
    combo_id = 42
    combo_data = {"comboId": 42, "totalPrice": 75000, "items": []}

    assert cache_service.get_combo(combo_id) is None
    assert cache_service.set_combo(combo_id, combo_data) is True
    assert cache_service.get_combo(combo_id) == combo_data
    assert cache_service.invalidate_combo(combo_id) is True
    assert cache_service.get_combo(combo_id) is None


# ---------------------------------------------------------
# 3. FashionSearchEngine Integration with CacheService
# ---------------------------------------------------------

def test_search_engine_uses_cached_embedding(cache_service: CacheService) -> None:
    dummy_vector = [0.1] * 512
    cache_service.set_text_embedding("minimal sweater", dummy_vector)

    engine = FashionSearchEngine(cache_service=cache_service)
    # mock model to ensure processor and model are NEVER called on cache hit
    engine.processor = MagicMock()
    engine.model = MagicMock()

    result_vector = engine.encode_text("minimal sweater")
    assert result_vector == dummy_vector
    engine.processor.assert_not_called()
    engine.model.get_text_features.assert_not_called()


def test_search_engine_uses_cached_search_results(cache_service: CacheService) -> None:
    cached_hits = [{"product_id": 777, "composite_score": 0.95}]
    cache_params = {
        "clip_query_en": "black boots",
        "category": "shoes",
        "subcategory": None,
        "season_preferences": None,
        "slot_budget": None,
        "max_price": None,
        "color": "black",
        "fit_type": None,
        "touch_type": None,
        "stretch_type": None,
        "transparency_type": None,
        "thickness_type": None,
        "top_k": 1,
    }
    cache_service.set_search_result(cache_params, cached_hits)

    engine = FashionSearchEngine(cache_service=cache_service)
    engine.client = MagicMock()  # Qdrant client mock

    res = engine.search(
        clip_query_en="black boots",
        category="shoes",
        color="black",
        top_k=1,
    )
    assert res == cached_hits
    engine.client.query_points.assert_not_called()


# ---------------------------------------------------------
# 4. FastAPI Recommendation API & Caching E2E Tests
# ---------------------------------------------------------

def test_recommendation_api_pipeline_caching(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    settings = Settings(
        db_path=":memory:",
        recommendation_service_token=RECOMMENDATION_TOKEN,
        community_service_token=COMMUNITY_TOKEN,
        product_service_token=PRODUCT_TOKEN,
        review_service_token=REVIEW_TOKEN,
        redis_enabled=True,
    )
    redis_client = RedisClient(settings=settings, redis_instance=fake_redis)
    cache_service = CacheService(redis_client=redis_client, settings=settings)

    coordinator = StubCoordinator()
    app.state.settings = settings
    app.state.repository = RecommendationRepository(db_path=":memory:")
    app.state.coordinator = coordinator
    app.state.user_client = StubUserClient()
    app.state.notification_client = StubNotificationClient()
    app.state.redis_client = redis_client
    app.state.cache_service = cache_service

    with TestClient(app) as client:
        # First request -> coordinator runs
        res1 = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "10"},
            json={"query": "오버핏 블랙 셔츠"},
        )
        assert res1.status_code == 202
        assert coordinator.call_count == 1

        # Second request with SAME user and query -> coordinator should NOT be called again (cache hit!)
        res2 = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "10"},
            json={"query": "오버핏 블랙 셔츠"},
        )
        assert res2.status_code == 202
        assert coordinator.call_count == 1  # Still 1! Reused from Redis cache!


def test_recommendation_api_size_feedback_invalidates_cache(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    settings = Settings(
        db_path=":memory:",
        review_service_token=REVIEW_TOKEN,
        redis_enabled=True,
    )
    redis_client = RedisClient(settings=settings, redis_instance=fake_redis)
    cache_service = CacheService(redis_client=redis_client, settings=settings)

    app.state.settings = settings
    app.state.repository = RecommendationRepository(db_path=":memory:")
    app.state.product_client = MagicMock()
    app.state.product_client.find_option_measurement.return_value = None
    app.state.redis_client = redis_client
    app.state.cache_service = cache_service

    # Seed user 15 cache
    cache_service.set_pipeline_result("셔츠 추천", "15", {"type": "single"})
    assert cache_service.get_pipeline_result("셔츠 추천", "15") is not None

    with TestClient(app) as client:
        feedback_res = client.post(
            "/recommendations/size-feedback",
            headers={"X-Service-Token": REVIEW_TOKEN},
            json={
                "userId": 15,
                "productId": 100,
                "optionId": 200,
                "sizeFeedback": "SMALL",
            },
        )
        assert feedback_res.status_code == 202


    # Verification: User 15's cached pipeline recommendations are invalidated
    assert cache_service.get_pipeline_result("셔츠 추천", "15") is None


def test_internal_combo_endpoint_caches_and_returns(
    fake_redis: fakeredis.FakeRedis,
) -> None:
    settings = Settings(
        db_path=":memory:",
        community_service_token=COMMUNITY_TOKEN,
        redis_enabled=True,
    )
    redis_client = RedisClient(settings=settings, redis_instance=fake_redis)
    cache_service = CacheService(redis_client=redis_client, settings=settings)

    mock_repo = MagicMock()
    mock_repo.get_combo.return_value = {
        "comboId": 501,
        "userId": 25,
        "totalPrice": 120000,
        "feedbackSummary": "멋진 코디입니다.",
        "items": [
            {
                "productId": 10,
                "productName": "자켓",
                "price": 80000,
            }
        ],
    }

    app.state.settings = settings
    app.state.repository = mock_repo
    app.state.redis_client = redis_client
    app.state.cache_service = cache_service

    with TestClient(app) as client:
        # First call -> fetches from repo and sets cache
        res1 = client.get(
            "/recommendations/combos/501?userId=25",
            headers={"X-Service-Token": COMMUNITY_TOKEN},
        )
        assert res1.status_code == 200
        assert res1.json()["totalPrice"] == 120000
        assert mock_repo.get_combo.call_count == 1

        # Second call -> hits cache, repo should NOT be queried again
        res2 = client.get(
            "/recommendations/combos/501?userId=25",
            headers={"X-Service-Token": COMMUNITY_TOKEN},
        )
        assert res2.status_code == 200
        assert res2.json()["totalPrice"] == 120000
        assert mock_repo.get_combo.call_count == 1  # Repository was NOT called a 2nd time!


def test_redis_client_serializes_pydantic_model():
    from pydantic import BaseModel
    import fakeredis

    class SampleModel(BaseModel):
        field_a: str = "hello"
        field_b: int = 42

    fake_r = fakeredis.FakeRedis(decode_responses=True)
    client = RedisClient(Settings(), redis_instance=fake_r)

    from datetime import datetime, timezone

    payload = {
        "status": "ok",
        "nested_model": SampleModel(),
        "created_at": datetime(2026, 10, 29, 12, 0, 0, tzinfo=timezone.utc),
    }

    assert client.set("test:pydantic", payload) is True
    cached = client.get("test:pydantic")
    assert cached is not None
    assert cached["status"] == "ok"
    assert cached["nested_model"]["field_a"] == "hello"
    assert cached["nested_model"]["field_b"] == 42
    assert cached["created_at"] == "2026-10-29T12:00:00+00:00"

