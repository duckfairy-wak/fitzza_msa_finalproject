from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.clients.order_client import OrderServiceClient
from app.clients.product_client import ProductServiceClient
from app.core.config import Settings
from app.services.user_history_service import UserActionHistory, UserHistoryCollector


@pytest.fixture
def mock_settings():
    return Settings(
        product_service_url="http://mock-product:8081",
        order_service_url="http://mock-order:8082",
        recommendation_service_token="test-token",
        http_timeout_seconds=2.0,
    )


@pytest.mark.anyio
async def test_product_client_get_latest_worldcup_winner_success(mock_settings):
    client = ProductServiceClient(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "worldcupHistoryId": 1,
        "winnerProduct": {"productId": 1024, "productName": "베이직 오버핏 맨투맨"},
    }

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        winner_id = await client.get_latest_worldcup_winner_async(user_id=7)
        assert winner_id == 1024
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "/api/worldcups/latest" in args[0]
        assert kwargs["headers"]["X-User-Id"] == "7"


@pytest.mark.anyio
async def test_product_client_get_latest_worldcup_winner_404_fallback(mock_settings):
    client = ProductServiceClient(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        winner_id = await client.get_latest_worldcup_winner_async(user_id=7)
        assert winner_id is None


@pytest.mark.anyio
async def test_product_client_get_user_wishlist_product_ids_success(mock_settings):
    client = ProductServiceClient(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "content": [
            {"wishlistId": 1, "itemId": 101},
            {"wishlistId": 2, "itemId": 102},
            {"wishlistId": 3, "itemId": 101},  # 중복
        ],
        "page": 0,
        "totalPages": 1,
    }

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        pids = await client.get_user_wishlist_product_ids_async(user_id=7)
        assert pids == [101, 102]


@pytest.mark.anyio
async def test_order_client_get_user_cart_product_ids_success(mock_settings):
    client = OrderServiceClient(settings=mock_settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"cartId": 1, "productId": 201},
        {"cartId": 2, "productId": 202},
        {"cartId": 3, "productId": 201},  # 중복
    ]

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        pids = await client.get_user_cart_product_ids_async(user_id=7)
        assert pids == [201, 202]
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "/api/carts" in args[0]
        assert kwargs["headers"]["X-User-Id"] == "7"


@pytest.mark.anyio
async def test_order_client_get_user_recent_purchased_product_ids_success(mock_settings):
    client = OrderServiceClient(settings=mock_settings)

    # 1. /api/orders 응답 mock (최근 주문 2건)
    mock_orders_resp = MagicMock()
    mock_orders_resp.status_code = 200
    mock_orders_resp.json.return_value = {
        "content": [
            {"orderId": 11, "orderStatus": "COMPLETED"},
            {"orderId": 12, "orderStatus": "SHIPPING"},
            {"orderId": 13, "orderStatus": "CANCELED"},  # 취소된 주문은 제외되어야 함
            {"orderId": 14, "orderStatus": "PENDING"},   # 미결제 주문도 제외되어야 함
        ],
        "page": 0,
    }

    # 2. /api/orders/{orderId} 응답 mock
    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/api/orders/11" in url:
            resp.json.return_value = {
                "orderId": 11,
                "items": [{"productId": 301}, {"productId": 302}],
            }
        elif "/api/orders/12" in url:
            resp.json.return_value = {
                "orderId": 12,
                "items": [{"productId": 302}, {"productId": 303}],  # 302 중복
            }
        elif "/api/orders" in url:
            return mock_orders_resp
        return resp

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = side_effect
        purchased_pids = await client.get_user_recent_purchased_product_ids_async(
            user_id=7, limit=5
        )
        assert purchased_pids == [301, 302, 303]


@pytest.mark.anyio
async def test_user_history_collector_concurrent_aggregation():
    mock_prod = MagicMock(spec=ProductServiceClient)
    mock_prod.get_latest_worldcup_winner_async = AsyncMock(return_value=1000)
    mock_prod.get_user_wishlist_product_ids_async = AsyncMock(return_value=[101, 102])

    mock_order = MagicMock(spec=OrderServiceClient)
    mock_order.get_user_cart_product_ids_async = AsyncMock(return_value=[201])
    mock_order.get_user_recent_purchased_product_ids_async = AsyncMock(
        return_value=[301, 302]
    )

    collector = UserHistoryCollector(
        product_client=mock_prod,
        order_client=mock_order,
    )

    history = await collector.collect(user_id=7)

    assert history.user_id == 7
    assert history.worldcup_winner_id == 1000
    assert history.wishlist_product_ids == [101, 102]
    assert history.cart_product_ids == [201]
    assert history.purchased_product_ids == [301, 302]
    assert history.has_any_history is True


@pytest.mark.anyio
async def test_user_history_collector_guest_user():
    collector = UserHistoryCollector()
    history = await collector.collect(user_id=0)
    assert history.user_id == 0
    assert history.worldcup_winner_id is None
    assert history.wishlist_product_ids == []
    assert history.cart_product_ids == []
    assert history.purchased_product_ids == []
    assert history.has_any_history is False


@pytest.mark.anyio
async def test_user_history_collector_exception_resilience():
    # 타 서비스가 통신 에러를 던져도 안전하게 빈 값으로 집계되는지 검증
    mock_prod = MagicMock(spec=ProductServiceClient)
    mock_prod.get_latest_worldcup_winner_async = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    mock_prod.get_user_wishlist_product_ids_async = AsyncMock(
        side_effect=httpx.TimeoutException("Timeout")
    )

    mock_order = MagicMock(spec=OrderServiceClient)
    mock_order.get_user_cart_product_ids_async = AsyncMock(return_value=[201])
    mock_order.get_user_recent_purchased_product_ids_async = AsyncMock(
        side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
    )

    collector = UserHistoryCollector(
        product_client=mock_prod,
        order_client=mock_order,
    )

    history = await collector.collect(user_id=7)
    assert history.user_id == 7
    assert history.worldcup_winner_id is None
    assert history.wishlist_product_ids == []
    assert history.cart_product_ids == [201]  # 성공한 것만 정상 반영
    assert history.purchased_product_ids == []
    assert history.has_any_history is True


@pytest.mark.anyio
async def test_user_history_collector_user_id_1_mock_fallback():
    """외부 연동이 비어있을 때 user_id=1에 대해 ENABLE_DEV_MOCK_HISTORY=True인 경우에만 Mock 주입되는지 검증"""
    mock_prod = MagicMock(spec=ProductServiceClient)
    mock_prod.get_latest_worldcup_winner_async = AsyncMock(return_value=None)
    mock_prod.get_user_wishlist_product_ids_async = AsyncMock(return_value=[])

    mock_order = MagicMock(spec=OrderServiceClient)
    mock_order.get_user_cart_product_ids_async = AsyncMock(return_value=[])
    mock_order.get_user_recent_purchased_product_ids_async = AsyncMock(return_value=[])

    collector = UserHistoryCollector(
        product_client=mock_prod,
        order_client=mock_order,
    )

    # 1. False 설정 시: Mock 주입되지 않고 빈 이력 반환
    from app.core.config import Settings
    with patch("app.services.user_history_service.get_settings", return_value=Settings(enable_dev_mock_history=False)):
        history_default = await collector.collect(user_id=1)
        assert history_default.user_id == 1
        assert history_default.worldcup_winner_id is None
        assert history_default.wishlist_product_ids == []
        assert history_default.cart_product_ids == []
        assert history_default.purchased_product_ids == []
        assert history_default.has_any_history is False

    # 2. ENABLE_DEV_MOCK_HISTORY=True 인 경우 Mock 데이터 정상 주입
    from app.core.config import Settings
    mock_settings = Settings(enable_dev_mock_history=True)
    with patch("app.services.user_history_service.get_settings", return_value=mock_settings):
        history_enabled = await collector.collect(user_id=1)
        assert history_enabled.user_id == 1
        assert history_enabled.worldcup_winner_id == 1786878
        assert history_enabled.wishlist_product_ids == [1951470, 1176331]
        assert history_enabled.cart_product_ids == [1973481, 1311988]
        assert history_enabled.purchased_product_ids == [2039021, 1312035]
        assert history_enabled.has_any_history is True


