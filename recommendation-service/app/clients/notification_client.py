import httpx

from app.core.config import Settings, get_settings

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"
RECOMMENDATION_DONE_TYPE = "RECOMMENDATION_DONE"
MAX_CONTENT_LENGTH = 500


class NotificationServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.notification_service_url.strip()
            and self.settings.recommendation_service_token.strip()
        )

    def send_recommendation_done(
        self,
        user_id: int,
        request_id: int,
        content: str = "추천 결과가 나왔어요.",
        request_id_header: str | None = None,
    ) -> bool:
        if not self.is_configured:
            return False

        base_url = self.settings.notification_service_url.rstrip("/")
        url = f"{base_url}/notifications/events"
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.recommendation_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        safe_content = (content or "추천 결과가 나왔어요.").strip()[:MAX_CONTENT_LENGTH]
        body = {
            "eventId": f"recommendation-{request_id}-done",
            "type": RECOMMENDATION_DONE_TYPE,
            "userId": int(user_id),
            "targetId": str(request_id),
            "content": safe_content,
        }

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                response = client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return True
        except Exception as exc:
            print(
                f"[WARN] notification-service RECOMMENDATION_DONE 전송 실패 "
                f"(requestId={request_id}, userId={user_id}): {type(exc).__name__}: {exc}"
            )
            return False
