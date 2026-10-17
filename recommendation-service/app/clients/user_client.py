from typing import Any

import httpx

from app.core.config import Settings, get_settings

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"


class UserServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.user_service_url.strip()
            and self.settings.recommendation_service_token.strip()
        )

    def get_user_body(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            return {}

        base_url = self.settings.user_service_url.rstrip("/")
        url = f"{base_url}/users/{user_id}/body"
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.recommendation_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                response = client.get(url, headers=headers)
                if response.status_code == 404:
                    return {}
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            print(
                f"[WARN] user-service 신체 정보 조회 실패 (userId={user_id}): "
                f"{type(exc).__name__}: {exc}"
            )
            return {}
