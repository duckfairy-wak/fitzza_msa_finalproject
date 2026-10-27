"""order-service HTTP 클라이언트."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

USER_ID_HEADER = "X-User-Id"
REQUEST_ID_HEADER = "X-Request-Id"


class OrderServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.order_service_url.strip())

    def get_user_cart_product_ids(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> list[int]:
        """사용자의 장바구니에 담긴 상품 ID 목록을 동기 조회합니다. (오류 시 빈 리스트)"""
        if not self.is_configured or user_id <= 0:
            return []

        base_url = self.settings.order_service_url.rstrip("/")
        url = f"{base_url}/api/carts"
        headers = {USER_ID_HEADER: str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, list):
                    product_ids = []
                    for item in payload:
                        if isinstance(item, dict) and item.get("productId"):
                            try:
                                product_ids.append(int(item["productId"]))
                            except (ValueError, TypeError):
                                pass
                    return list(dict.fromkeys(product_ids))
                return []
        except Exception as exc:
            logger.warning(
                "order-service 장바구니 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

    async def get_user_cart_product_ids_async(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> list[int]:
        """사용자의 장바구니에 담긴 상품 ID 목록을 비동기 조회합니다. (오류 시 빈 리스트)"""
        if not self.is_configured or user_id <= 0:
            return []

        base_url = self.settings.order_service_url.rstrip("/")
        url = f"{base_url}/api/carts"
        headers = {USER_ID_HEADER: str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, list):
                    product_ids = []
                    for item in payload:
                        if isinstance(item, dict) and item.get("productId"):
                            try:
                                product_ids.append(int(item["productId"]))
                            except (ValueError, TypeError):
                                pass
                    return list(dict.fromkeys(product_ids))
                return []
        except Exception as exc:
            logger.warning(
                "order-service 장바구니 비동기 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

    async def _fetch_order_detail_product_ids_async(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        order_id: int,
        user_id: int,
        request_id_header: str | None = None,
    ) -> list[int]:
        """단건 주문 상세를 비동기 조회하여 상품 ID 목록을 반환합니다."""
        url = f"{base_url}/api/orders/{order_id}"
        headers = {USER_ID_HEADER: str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("items") if isinstance(payload, dict) else []
            pids = []
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("productId"):
                        try:
                            pids.append(int(item["productId"]))
                        except (ValueError, TypeError):
                            pass
            return pids
        except Exception as exc:
            logger.warning(
                "order-service 주문 상세 조회 실패 (orderId=%s, userId=%s): %s: %s",
                order_id,
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

    async def get_user_recent_purchased_product_ids_async(
        self,
        user_id: int,
        limit: int = 5,
        request_id_header: str | None = None,
    ) -> list[int]:
        """최근 구매 완료 주문 목록(최대 limit건)에서 상품 ID 목록을 비동기 병렬 조회합니다."""
        if not self.is_configured or user_id <= 0:
            return []

        base_url = self.settings.order_service_url.rstrip("/")
        url = f"{base_url}/api/orders"
        params = {"page": 0, "size": min(max(limit, 1), 20)}
        headers = {USER_ID_HEADER: str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                # 1. 최근 주문 목록 조회
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                payload = resp.json()
                content = payload.get("content") if isinstance(payload, dict) else []
                if not isinstance(content, list) or not content:
                    return []

                # 완료/유효 주문 ID 추출 (최대 limit개)
                order_ids: list[int] = []
                for o in content:
                    if isinstance(o, dict) and o.get("orderId"):
                        # 결제 완료 또는 배송/완료된 정상 구매 주문만 대상
                        if o.get("orderStatus") in {"PAID", "SHIPPING", "COMPLETED"}:
                            order_ids.append(int(o["orderId"]))
                    if len(order_ids) >= limit:
                        break

                if not order_ids:
                    return []

                # 2. 주문 상세 병렬 조회 (asyncio.gather)
                tasks = [
                    self._fetch_order_detail_product_ids_async(
                        client=client,
                        base_url=base_url,
                        order_id=oid,
                        user_id=user_id,
                        request_id_header=request_id_header,
                    )
                    for oid in order_ids
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                all_product_ids: list[int] = []
                for res in results:
                    if isinstance(res, list):
                        all_product_ids.extend(res)

                return list(dict.fromkeys(all_product_ids))
        except Exception as exc:
            logger.warning(
                "order-service 최근 주문 비동기 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

    def get_user_recent_purchased_product_ids(
        self,
        user_id: int,
        limit: int = 5,
        request_id_header: str | None = None,
    ) -> list[int]:
        """동기 환경에서 비동기 병렬 조회를 안전하게 실행합니다."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 이미 이벤트 루프가 돌고 있다면 새로운 스레드 또는 태스크 생성
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    return executor.submit(
                        asyncio.run,
                        self.get_user_recent_purchased_product_ids_async(
                            user_id=user_id,
                            limit=limit,
                            request_id_header=request_id_header,
                        ),
                    ).result()
            return loop.run_until_complete(
                self.get_user_recent_purchased_product_ids_async(
                    user_id=user_id,
                    limit=limit,
                    request_id_header=request_id_header,
                )
            )
        except RuntimeError:
            return asyncio.run(
                self.get_user_recent_purchased_product_ids_async(
                    user_id=user_id,
                    limit=limit,
                    request_id_header=request_id_header,
                )
            )
