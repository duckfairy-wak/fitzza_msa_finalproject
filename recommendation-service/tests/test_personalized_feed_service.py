from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.recommendation import PersonalizedProductItem
from app.services.personalized_feed_service import PersonalizedFeedService
from app.services.user_history_service import (
    UserActionHistory,
    UserHistoryCollector,
)


def _make_dummy_item(pid: int, category: str, wished: bool = False) -> PersonalizedProductItem:
    return PersonalizedProductItem(
        productId=pid,
        productName=f"상품_{pid}",
        brandName="무신사 스탠다드",
        price=29000,
        thumbnailUrl=f"https://img.msscdn.net/{pid}.jpg",
        status="ON_SALE",
        category=category,
        wished=wished,
    )


def test_interleave_categories_balanced():
    """5개 카테고리 모두 16개씩 완비된 경우 80개 정확한 라운드 로빈 순서 검증"""
    categories = ["상의", "하의", "아우터", "신발", "모자"]
    buckets = {}
    base_id = 1000

    for cat in categories:
        buckets[cat] = [
            _make_dummy_item(base_id + i, cat)
            for i in range(16)
        ]
        base_id += 100

    interleaved = PersonalizedFeedService.interleave_categories(
        category_buckets=buckets,
        order=categories,
        limit_per_category=16,
    )

    assert len(interleaved) == 80

    # 첫 5개 순서 검증: 상의[0], 하의[0], 아우터[0], 신발[0], 모자[0]
    expected_categories = ["상의", "하의", "아우터", "신발", "모자"]
    for i in range(5):
        assert interleaved[i].category == expected_categories[i]

    # 두 번째 라운드 5개 검증: 상의[1], 하의[1], 아우터[1], 신발[1], 모자[1]
    for i in range(5):
        assert interleaved[5 + i].category == expected_categories[i]

    # 마지막 아이템은 모자[15]
    assert interleaved[-1].category == "모자"


def test_interleave_categories_unbalanced():
    """모자가 2개만 있고 다른 카테고리는 4개씩 있는 불균형 상태에서의 결합 검증"""
    categories = ["상의", "하의", "아우터", "신발", "모자"]
    buckets = {
        "상의": [_make_dummy_item(100 + i, "상의") for i in range(4)],
        "하의": [_make_dummy_item(200 + i, "하의") for i in range(4)],
        "아우터": [_make_dummy_item(300 + i, "아우터") for i in range(4)],
        "신발": [_make_dummy_item(400 + i, "신발") for i in range(4)],
        "모자": [_make_dummy_item(500 + i, "모자") for i in range(2)],  # 2개만 있음
    }

    interleaved = PersonalizedFeedService.interleave_categories(
        category_buckets=buckets,
        order=categories,
        limit_per_category=4,
    )

    # 4*4 + 2 = 18개
    assert len(interleaved) == 18

    # 라운드 0 (5개): 상의0, 하의0, 아우터0, 신발0, 모자0
    assert [item.category for item in interleaved[:5]] == ["상의", "하의", "아우터", "신발", "모자"]
    # 라운드 1 (5개): 상의1, 하의1, 아우터1, 신발1, 모자1
    assert [item.category for item in interleaved[5:10]] == ["상의", "하의", "아우터", "신발", "모자"]
    # 라운드 2 (4개 - 모자 소진): 상의2, 하의2, 아우터2, 신발2
    assert [item.category for item in interleaved[10:14]] == ["상의", "하의", "아우터", "신발"]
    # 라운드 3 (4개 - 모자 소진): 상의3, 하의3, 아우터3, 신발3
    assert [item.category for item in interleaved[14:18]] == ["상의", "하의", "아우터", "신발"]


def test_search_category_candidates_filtering_and_wished():
    """Qdrant 검색 시 필터 조건, 중복 pid 제거, wished 플래그 정상 세팅 검증"""
    mock_client = MagicMock()

    class MockPoint:
        def __init__(self, pid, name, cat):
            self.payload = {
                "product_id": pid,
                "product_name": name,
                "brand_name": "브랜드",
                "price": 35000,
                "category": cat,
                "image_url": f"https://img/{pid}.jpg",
            }

    # pid 101이 서로 다른 색상 포인트로 2번 들어옴
    mock_points = [
        MockPoint(101, "옥스포드 셔츠 화이트", "상의"),
        MockPoint(101, "옥스포드 셔츠 블루", "상의"),  # 중복 PID
        MockPoint(102, "린넨 셔츠 네이비", "상의"),
    ]
    mock_resp = MagicMock()
    mock_resp.points = mock_points
    mock_client.query_points.return_value = mock_resp

    service = PersonalizedFeedService(qdrant_client=mock_client)
    items = service.search_category_candidates(
        taste_vector=[0.1] * 512,
        category="상의",
        limit=10,
        exclude_pids=[999],
        wishlist_set={101},  # 101번은 찜한 상품
    )

    assert len(items) == 2  # 101 중복 제거되어 2개만 남아야 함
    assert items[0].productId == 101
    assert items[0].wished is True  # 찜 확인
    assert items[1].productId == 102
    assert items[1].wished is False

    # Qdrant query_points 호출 인자 검증
    call_kwargs = mock_client.query_points.call_args.kwargs
    query_filter = call_kwargs["query_filter"]
    assert query_filter.must[0].key == "category"
    assert query_filter.must[0].match.value == "상의"
    assert query_filter.must_not[0].key == "product_id"
    assert query_filter.must_not[0].match.any == [999]


def test_search_category_candidates_qdrant_error():
    """Qdrant 에러 발생 시 빈 리스트 반환 검증"""
    mock_client = MagicMock()
    mock_client.query_points.side_effect = RuntimeError("Qdrant Down")

    service = PersonalizedFeedService(qdrant_client=mock_client)
    items = service.search_category_candidates(
        taste_vector=[0.1] * 512,
        category="아우터",
    )
    assert items == []


@pytest.mark.anyio
async def test_generate_personalized_feed_items_async():
    """비동기 병렬 검색 및 인터리빙 피드 생성 파이프라인 검증"""
    mock_collector = MagicMock()
    mock_history = UserActionHistory(
        user_id=42,
        worldcup_winner_id=10,
        wishlist_product_ids=[20],
        cart_product_ids=[30],
        purchased_product_ids=[40],
    )
    mock_collector.collect_user_history_async = AsyncMock(return_value=mock_history)

    mock_engine = MagicMock()
    mock_engine.compute_user_taste_vector.return_value = [0.05] * 512

    service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        vector_engine=mock_engine,
        history_collector=mock_collector,
    )

    # 5개 카테고리 검색 mock (각각 2개씩 반환)
    def fake_search(taste_vector, category, limit, exclude_pids, wishlist_set):
        return [
            _make_dummy_item(100 + i, category, wished=(100 + i in wishlist_set))
            for i in range(2)
        ]

    with patch.object(service, "search_category_candidates", side_effect=fake_search):
        feed, history = await service.generate_personalized_feed_items(user_id=42)

    assert history.user_id == 42
    # 5개 카테고리 * 2개 = 10개
    assert len(feed) == 10
    assert feed[0].category == "상의"
    assert feed[1].category == "하의"
    assert feed[2].category == "아우터"
    assert feed[3].category == "신발"
    assert feed[4].category == "모자"
    assert feed[5].category == "상의"


@pytest.mark.anyio
async def test_generate_personalized_feed_items_with_real_collector():
    """실제 UserHistoryCollector 인스턴스를 주입하여 collect_user_history_async가 완벽히 동작하는지 검증"""
    from app.clients.order_client import OrderServiceClient
    from app.clients.product_client import ProductServiceClient

    mock_prod = MagicMock(spec=ProductServiceClient)
    mock_prod.get_latest_worldcup_winner_async = AsyncMock(return_value=10)
    mock_prod.get_user_wishlist_product_ids_async = AsyncMock(return_value=[20])

    mock_order = MagicMock(spec=OrderServiceClient)
    mock_order.get_user_cart_product_ids_async = AsyncMock(return_value=[30])
    mock_order.get_user_recent_purchased_product_ids_async = AsyncMock(return_value=[40])

    real_collector = UserHistoryCollector(product_client=mock_prod, order_client=mock_order)

    mock_engine = MagicMock()
    mock_engine.compute_user_taste_vector.return_value = [0.05] * 512

    service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        vector_engine=mock_engine,
        history_collector=real_collector,
    )

    with patch.object(service, "search_category_candidates", return_value=[]):
        feed, history = await service.generate_personalized_feed_items(user_id=42)

    assert history.user_id == 42
    assert feed == []
    assert history.worldcup_winner_id == 10
    assert history.wishlist_product_ids == [20]
    assert history.cart_product_ids == [30]
    assert history.purchased_product_ids == [40]


@pytest.mark.anyio
async def test_get_personalized_feed_page_corrupted_cache_fallback():
    """캐시에 손상된 데이터가 있을 경우 500 에러 대신 경고 후 재생성하는지 검증"""
    service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        vector_engine=MagicMock(),
    )

    mock_cache = MagicMock()
    # 유효하지 않은 스키마 데이터 (productId 누락 등 ValidationError 유발)
    mock_cache.get_personalized_feed.return_value = [{"invalid": "item"}]

    dummy_item = PersonalizedProductItem(
        productId=999,
        productName="새 상품",
        price=10000,
    )
    with patch.object(
        service,
        "generate_personalized_feed_items",
        AsyncMock(return_value=([dummy_item], MagicMock())),
    ):
        page = await service.get_personalized_feed_page(
            user_id=1, page=0, size=10, cache_service=mock_cache
        )

    assert page.totalElements == 1
    assert page.content[0].productId == 999


@pytest.mark.anyio
async def test_product_client_get_product_statuses_async():
    """product-service 상품 상태 일괄 비동기 조회 및 청킹 검증"""
    import httpx
    from app.clients.product_client import ProductServiceClient
    from app.core.config import Settings

    settings = Settings(
        product_service_url="http://mock-product:8081",
        recommendation_service_token="test-recommendation-token-with-sufficient-bytes-12345",
    )
    client = ProductServiceClient(settings=settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"productId": 101, "status": "ON_SALE"},
        {"productId": 102, "status": "SOLD_OUT"},
        {"productId": 103, "status": "HIDDEN"},
    ]

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
        statuses = await client.get_product_statuses_async([101, 102, 103])

    assert statuses == {101: "ON_SALE", 102: "SOLD_OUT", 103: "HIDDEN"}


@pytest.mark.anyio
async def test_personalized_feed_filters_out_non_on_sale_products():
    """SOLD_OUT 및 HIDDEN 상품이 추천 피드에서 제외되고 ON_SALE 상품만 남는지 검증"""
    mock_prod_client = MagicMock()
    # 100: ON_SALE, 101: SOLD_OUT, 102: HIDDEN
    mock_prod_client.get_product_statuses_async = AsyncMock(
        return_value={
            100: "ON_SALE",
            101: "SOLD_OUT",
            102: "HIDDEN",
        }
    )

    mock_collector = MagicMock()
    mock_collector.collect_user_history_async = AsyncMock(return_value=UserActionHistory(user_id=1))
    mock_engine = MagicMock()
    mock_engine.compute_user_taste_vector.return_value = [0.1] * 512

    service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        vector_engine=mock_engine,
        history_collector=mock_collector,
        product_client=mock_prod_client,
    )

    # 각 카테고리별로 100, 101, 102 세 개 상품 반환
    def fake_search(taste_vector, category, limit, exclude_pids, wishlist_set):
        return [
            _make_dummy_item(100, category),
            _make_dummy_item(101, category),
            _make_dummy_item(102, category),
        ]

    with patch.object(service, "search_category_candidates", side_effect=fake_search):
        feed, _ = await service.generate_personalized_feed_items(user_id=1)

    # 101(SOLD_OUT), 102(HIDDEN)은 제외되고 오직 100(ON_SALE)만 남아야 함 (5개 카테고리 * 1개 = 5개)
    assert len(feed) == 5
    for item in feed:
        assert item.productId == 100
        assert item.status == "ON_SALE"


@pytest.mark.anyio
async def test_personalized_feed_fallback_on_product_service_down():
    """product-service 통신 실패 시 가용성 우선 Fallback(기본 ON_SALE 간주) 검증"""
    mock_prod_client = MagicMock()
    # product-service 다운 시 None 반환
    mock_prod_client.get_product_statuses_async = AsyncMock(return_value=None)

    mock_collector = MagicMock()
    mock_collector.collect_user_history_async = AsyncMock(return_value=UserActionHistory(user_id=1))
    mock_engine = MagicMock()
    mock_engine.compute_user_taste_vector.return_value = [0.1] * 512

    service = PersonalizedFeedService(
        qdrant_client=MagicMock(),
        vector_engine=mock_engine,
        history_collector=mock_collector,
        product_client=mock_prod_client,
    )

    def fake_search(taste_vector, category, limit, exclude_pids, wishlist_set):
        return [_make_dummy_item(200 + i, category) for i in range(2)]

    with patch.object(service, "search_category_candidates", side_effect=fake_search):
        feed, _ = await service.generate_personalized_feed_items(user_id=1)

    # 서비스가 중단되지 않고 10개 상품 모두 ON_SALE로 유지되어 반환
    assert len(feed) == 10
    for item in feed:
        assert item.status == "ON_SALE"



