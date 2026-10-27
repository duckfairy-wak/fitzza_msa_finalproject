import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

from app.services.size_spec_normalizer import (
    normalize_measurement_spec as _normalize_spec,
)

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"


def normalize_measurement_spec(
    raw_spec: dict[str, Any] | None,
    category: str | None = None,
) -> dict[str, float]:
    return _normalize_spec(raw_spec, category=category)


class ProductServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.product_service_url.strip()
            and self.settings.recommendation_service_token.strip()
        )

    def get_product_measurements(
        self,
        product_ids: list[int],
        request_id_header: str | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        distinct_ids = sorted({int(pid) for pid in product_ids if pid and int(pid) > 0})
        if not distinct_ids or not self.is_configured:
            return {}

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/products/measurements"
        params = {"productIds": ",".join(str(pid) for pid in distinct_ids)}
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.recommendation_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    return {}

                measurements_by_product: dict[int, list[dict[str, Any]]] = {}
                for entry in payload:
                    if not isinstance(entry, dict):
                        continue
                    pid = entry.get("productId")
                    if pid is None:
                        continue
                    options = entry.get("options") or []
                    parsed_options: list[dict[str, Any]] = []
                    for opt in options:
                        if not isinstance(opt, dict):
                            continue
                        spec = normalize_measurement_spec(opt.get("measurementSpec"))
                        if not spec:
                            continue
                        parsed_options.append(
                            {
                                "option_id": opt.get("optionId"),
                                "color": opt.get("color"),
                                "size": opt.get("size") or "FREE",
                                "measurements": spec,
                            }
                        )
                    measurements_by_product[int(pid)] = parsed_options
                return measurements_by_product
        except Exception as exc:
            logger.warning(
                "product-service 실측 조회 실패 (productIds=%s): %s: %s",
                distinct_ids,
                type(exc).__name__,
                exc,
            )
            return {}

    def find_option_measurement(
        self,
        product_id: int,
        option_id: int,
        request_id_header: str | None = None,
    ) -> dict[str, float] | None:
        measurements_by_product = self.get_product_measurements(
            [product_id],
            request_id_header=request_id_header,
        )
        options = measurements_by_product.get(int(product_id), [])
        for option in options:
            try:
                if int(option.get("option_id")) == int(option_id):
                    return option.get("measurements")
            except (TypeError, ValueError):
                continue
        return None

    def get_latest_worldcup_winner(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> int | None:
        """최근 이상형 월드컵 1등 상품 ID를 동기 조회합니다. (없거나 오류 시 None)"""
        if not self.settings.product_service_url.strip() or user_id <= 0:
            return None

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/api/worldcups/latest"
        headers = {"X-User-Id": str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    winner = payload.get("winnerProduct")
                    if isinstance(winner, dict) and winner.get("productId"):
                        return int(winner["productId"])
                return None
        except Exception as exc:
            logger.warning(
                "product-service 월드컵 우승 상품 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return None

    async def get_latest_worldcup_winner_async(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> int | None:
        """최근 이상형 월드컵 1등 상품 ID를 비동기 조회합니다. (없거나 오류 시 None)"""
        if not self.settings.product_service_url.strip() or user_id <= 0:
            return None

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/api/worldcups/latest"
        headers = {"X-User-Id": str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    winner = payload.get("winnerProduct")
                    if isinstance(winner, dict) and winner.get("productId"):
                        return int(winner["productId"])
                return None
        except Exception as exc:
            logger.warning(
                "product-service 월드컵 우승 상품 비동기 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return None

    def get_user_wishlist_product_ids(
        self,
        user_id: int,
        size: int = 50,
        request_id_header: str | None = None,
    ) -> list[int]:
        """사용자가 찜한 상품 ID 목록을 동기 조회합니다. (오류 시 빈 리스트)"""
        if not self.settings.product_service_url.strip() or user_id <= 0:
            return []

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/api/wishlists"
        params = {"page": 0, "size": min(max(size, 1), 100)}
        headers = {"X-User-Id": str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                resp = client.get(url, params=params, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                payload = resp.json()
                content = payload.get("content") if isinstance(payload, dict) else []
                if isinstance(content, list):
                    product_ids = []
                    for item in content:
                        if isinstance(item, dict) and item.get("itemId"):
                            try:
                                product_ids.append(int(item["itemId"]))
                            except (ValueError, TypeError):
                                pass
                    return list(dict.fromkeys(product_ids))
                return []
        except Exception as exc:
            logger.warning(
                "product-service 찜 목록 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

    async def get_user_wishlist_product_ids_async(
        self,
        user_id: int,
        size: int = 50,
        request_id_header: str | None = None,
    ) -> list[int]:
        """사용자가 찜한 상품 ID 목록을 비동기 조회합니다. (오류 시 빈 리스트)"""
        if not self.settings.product_service_url.strip() or user_id <= 0:
            return []

        base_url = self.settings.product_service_url.rstrip("/")
        url = f"{base_url}/api/wishlists"
        params = {"page": 0, "size": min(max(size, 1), 100)}
        headers = {"X-User-Id": str(user_id)}
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            async with httpx.AsyncClient(timeout=self.settings.http_timeout_seconds) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 404:
                    return []
                resp.raise_for_status()
                payload = resp.json()
                content = payload.get("content") if isinstance(payload, dict) else []
                if isinstance(content, list):
                    product_ids = []
                    for item in content:
                        if isinstance(item, dict) and item.get("itemId"):
                            try:
                                product_ids.append(int(item["itemId"]))
                            except (ValueError, TypeError):
                                pass
                    return list(dict.fromkeys(product_ids))
                return []
        except Exception as exc:
            logger.warning(
                "product-service 찜 목록 비동기 조회 실패 (userId=%s): %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
            return []

