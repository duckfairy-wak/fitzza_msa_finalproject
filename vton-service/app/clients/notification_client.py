"""notification-service HTTP 클라이언트."""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

SERVICE_TOKEN_HEADER = "X-Service-Token"
REQUEST_ID_HEADER = "X-Request-Id"

FITTING_DONE_TYPE = "FITTING_DONE"
FITTING_FAILED_TYPE = "FITTING_FAILED"
MAX_CONTENT_LENGTH = 500


class NotificationServiceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.notification_service_url.strip()
            and self.settings.vton_service_token.strip()
        )

    def send_fitting_event(
        self,
        event_type: Literal["FITTING_DONE", "FITTING_FAILED"],
        user_id: int,
        fitting_id: int,
        content: str,
        request_id_header: str | None = None,
    ) -> bool:
        """notification-service로 피팅 완료 또는 실패 FCM 이벤트를 발송합니다."""
        if not self.is_configured:
            return False

        base_url = self.settings.notification_service_url.rstrip("/")
        url = f"{base_url}/notifications/events"
        headers = {
            SERVICE_TOKEN_HEADER: self.settings.vton_service_token,
        }
        if request_id_header:
            headers[REQUEST_ID_HEADER] = request_id_header

        safe_content = (content or "").strip()[:MAX_CONTENT_LENGTH]
        suffix = "done" if event_type == FITTING_DONE_TYPE else "failed"
        body = {
            "eventId": f"fitting-{fitting_id}-{suffix}",
            "type": event_type,
            "userId": int(user_id),
            "targetId": str(fitting_id),
            "content": safe_content,
        }

        try:
            with httpx.Client(timeout=self.settings.http_timeout_seconds) as client:
                response = client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return True
        except Exception as exc:
            logger.warning(
                "notification-service %s 전송 실패 (fittingId=%s, userId=%s): %s: %s",
                event_type,
                fitting_id,
                user_id,
                type(exc).__name__,
                exc,
            )
            return False

    def send_fitting_done(
        self,
        user_id: int,
        fitting_id: int,
        content: str = "가상 피팅이 완료되었습니다.",
        request_id_header: str | None = None,
    ) -> bool:
        return self.send_fitting_event(
            FITTING_DONE_TYPE,
            user_id=user_id,
            fitting_id=fitting_id,
            content=content,
            request_id_header=request_id_header,
        )

    def send_fitting_failed(
        self,
        user_id: int,
        fitting_id: int,
        content: str = "요청하신 가상 피팅이 실패했어요.",
        request_id_header: str | None = None,
    ) -> bool:
        return self.send_fitting_event(
            FITTING_FAILED_TYPE,
            user_id=user_id,
            fitting_id=fitting_id,
            content=content,
            request_id_header=request_id_header,
        )
