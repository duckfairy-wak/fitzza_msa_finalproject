"""사용자 행동 이력(월드컵 1등, 찜, 장바구니, 구매) 통합 수집 서비스."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

from app.clients.order_client import OrderServiceClient
from app.clients.product_client import ProductServiceClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class UserActionHistory:
    user_id: int
    worldcup_winner_id: int | None = None
    wishlist_product_ids: list[int] = field(default_factory=list)
    cart_product_ids: list[int] = field(default_factory=list)
    purchased_product_ids: list[int] = field(default_factory=list)

    @property
    def has_any_history(self) -> bool:
        """어떤 행동 이력이라도 존재하는지 여부 (Cold-Start 판별용)."""
        return bool(
            self.worldcup_winner_id
            or self.wishlist_product_ids
            or self.cart_product_ids
            or self.purchased_product_ids
        )


class UserHistoryCollector:
    """product-service 및 order-service를 비동기 병렬 호출하여 유저 행동 이력을 집계합니다."""

    def __init__(
        self,
        product_client: ProductServiceClient | None = None,
        order_client: OrderServiceClient | None = None,
    ) -> None:
        self.product_client = product_client or ProductServiceClient()
        self.order_client = order_client or OrderServiceClient()

    async def collect(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> UserActionHistory:
        """사용자 ID로 4개 이력 데이터를 asyncio.gather로 동시 병렬 수집합니다."""
        if user_id <= 0:
            return UserActionHistory(user_id=user_id)

        # 4개 통신 태스크를 병렬로 동시 실행
        tasks = [
            self.product_client.get_latest_worldcup_winner_async(
                user_id=user_id,
                request_id_header=request_id_header,
            ),
            self.product_client.get_user_wishlist_product_ids_async(
                user_id=user_id,
                request_id_header=request_id_header,
            ),
            self.order_client.get_user_cart_product_ids_async(
                user_id=user_id,
                request_id_header=request_id_header,
            ),
            self.order_client.get_user_recent_purchased_product_ids_async(
                user_id=user_id,
                limit=5,
                request_id_header=request_id_header,
            ),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 1. 월드컵 우승 상품
        res_worldcup = results[0]
        worldcup_winner_id: int | None = None
        if isinstance(res_worldcup, int):
            worldcup_winner_id = res_worldcup
        elif isinstance(res_worldcup, Exception):
            logger.warning("월드컵 이력 비동기 수집 예외: %s", res_worldcup)

        # 2. 찜 목록
        res_wishlist = results[1]
        wishlist_ids: list[int] = []
        if isinstance(res_wishlist, list):
            wishlist_ids = res_wishlist
        elif isinstance(res_wishlist, Exception):
            logger.warning("찜 목록 비동기 수집 예외: %s", res_wishlist)

        # 3. 장바구니
        res_cart = results[2]
        cart_ids: list[int] = []
        if isinstance(res_cart, list):
            cart_ids = res_cart
        elif isinstance(res_cart, Exception):
            logger.warning("장바구니 비동기 수집 예외: %s", res_cart)

        # 4. 최근 구매 내역 (5건)
        res_purchased = results[3]
        purchased_ids: list[int] = []
        if isinstance(res_purchased, list):
            purchased_ids = res_purchased
        elif isinstance(res_purchased, Exception):
            logger.warning("구매 내역 비동기 수집 예외: %s", res_purchased)

        # 개발/Swagger 테스트용 Fallback: ENABLE_DEV_MOCK_HISTORY=True이고 외부 마이크로서비스 연동 데이터가 없고 user_id == 1인 경우 대표 카탈로그 상품 Mock 주입
        if (
            get_settings().enable_dev_mock_history
            and user_id == 1
            and worldcup_winner_id is None
            and not wishlist_ids
            and not cart_ids
            and not purchased_ids
        ):
            worldcup_winner_id = 1786878  # 대표 상의 (월드컵 1등)
            wishlist_ids = [1951470, 1176331]  # 찜 2건 (상의, 하의)
            cart_ids = [1973481, 1311988]  # 장바구니 2건 (상의, 하의)
            purchased_ids = [2039021, 1312035]  # 최근 구매 2건 (상의, 하의 -> 피드 제외 대상)
            logger.info("userId=1 로컬 개발/Swagger 테스트용 4대 Mock 행동 이력을 주입했습니다.")

        logger.info(
            "유저 행동 이력 수집 완료 (userId=%s, 월드컵=%s, 찜=%d건, 장바구니=%d건, 구매=%d건)",
            user_id,
            worldcup_winner_id,
            len(wishlist_ids),
            len(cart_ids),
            len(purchased_ids),
        )

        return UserActionHistory(
            user_id=user_id,
            worldcup_winner_id=worldcup_winner_id,
            wishlist_product_ids=wishlist_ids,
            cart_product_ids=cart_ids,
            purchased_product_ids=purchased_ids,
        )

    async def collect_user_history_async(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> UserActionHistory:
        """collect 메서드의 명시적 비동기 별칭."""
        return await self.collect(user_id=user_id, request_id_header=request_id_header)

    collect_async = collect_user_history_async

