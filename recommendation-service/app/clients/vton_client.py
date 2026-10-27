import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"


class VtonServiceClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.vton_service_url.strip()
            and self.settings.recommendation_service_token.strip()
        )

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self.settings.http_timeout_seconds)
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __enter__(self) -> "VtonServiceClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_token_usage_in_range(
        self,
        start_iso: str,
        end_iso: str,
        request_id_header: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        vton-service의 내부 API(GET /vton/token-usage)를 호출하여
        지정 기간 동안 완료된 가상 피팅의 OpenAI 토큰 사용량 목록을 가져옵니다.
        """
        if not self.is_configured:
            return []

        base_url = self.settings.vton_service_url.rstrip("/")
        url = f"{base_url}/vton/token-usage"
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.recommendation_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        params = {
            "startDate": start_iso,
            "endDate": end_iso,
        }

        try:
            client = self._get_client()
            response = client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                logger.warning(
                    "vton-service 토큰 사용량 조회 응답 오류 (status=%s): %s",
                    response.status_code,
                    response.text,
                )
                return []
            data = response.json()
            records = data.get("records") if isinstance(data, dict) else []
            return records if isinstance(records, list) else []
        except Exception as exc:
            logger.warning(
                "vton-service 토큰 사용량 조회 HTTP 통신 실패: %s: %s",
                type(exc).__name__,
                exc,
            )
            return []
