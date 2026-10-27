from __future__ import annotations

import json
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SqsClientError(Exception):
    """SQS 연동 중 발생한 예외."""


class SqsClient:
    """AWS SQS 메시지 큐 클라이언트 (LocalStack 및 AWS 호환)."""

    def __init__(
        self,
        settings: Settings | None = None,
        sqs_client: Any = None,
    ) -> None:
        self.settings = settings or get_settings()

        if sqs_client is not None:
            self._client = sqs_client
        else:
            client_kwargs: dict[str, Any] = {
                "region_name": self.settings.aws_region,
            }
            if self.settings.aws_access_key_id and self.settings.aws_secret_access_key:
                client_kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
            if self.settings.aws_endpoint_url.strip():
                client_kwargs["endpoint_url"] = self.settings.aws_endpoint_url.strip()

            try:
                self._client = boto3.client("sqs", **client_kwargs)
            except Exception as exc:
                logger.error("SQS 클라이언트 초기화 실패: %s", exc, exc_info=True)
                raise SqsClientError(f"SQS 클라이언트 초기화 실패: {exc}") from exc

    def _resolve_queue_url(self, queue_url: str | None) -> str:
        url = (queue_url or self.settings.aws_sqs_queue_url).strip()
        if not url:
            raise SqsClientError("AWS_SQS_QUEUE_URL이 설정되지 않았습니다.")
        return url

    def send_message(
        self,
        payload: dict[str, Any],
        queue_url: str | None = None,
        message_attributes: dict[str, Any] | None = None,
    ) -> str:
        """SQS 큐에 JSON 메시지를 발행합니다."""
        target_url = self._resolve_queue_url(queue_url)
        try:
            body_str = json.dumps(payload, ensure_ascii=False)
            kwargs: dict[str, Any] = {
                "QueueUrl": target_url,
                "MessageBody": body_str,
            }
            if message_attributes:
                kwargs["MessageAttributes"] = message_attributes

            response = self._client.send_message(**kwargs)
            message_id = str(response.get("MessageId", ""))
            logger.info("SQS 메시지 발행 성공 (messageId=%s, queueUrl=%s)", message_id, target_url)
            return message_id
        except (ClientError, BotoCoreError, Exception) as exc:
            logger.error("SQS 메시지 발행 실패 (queueUrl=%s): %s", target_url, exc, exc_info=True)
            raise SqsClientError(f"SQS 메시지 발행 실패: {exc}") from exc

    def receive_messages(
        self,
        max_messages: int | None = None,
        wait_time_seconds: int | None = None,
        visibility_timeout: int | None = None,
        queue_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """SQS 큐에서 메시지를 Long Polling 방식으로 수신합니다."""
        target_url = self._resolve_queue_url(queue_url)
        max_n = max_messages if max_messages is not None else self.settings.sqs_max_number_of_messages
        wait_sec = wait_time_seconds if wait_time_seconds is not None else self.settings.sqs_wait_time_seconds
        vis_timeout = (
            visibility_timeout
            if visibility_timeout is not None
            else self.settings.sqs_visibility_timeout
        )

        try:
            response = self._client.receive_message(
                QueueUrl=target_url,
                MaxNumberOfMessages=max(1, min(max_n, 10)),
                WaitTimeSeconds=max(0, min(wait_sec, 20)),
                VisibilityTimeout=vis_timeout,
                AttributeNames=["ApproximateReceiveCount"],
                MessageAttributeNames=["All"],
            )

            raw_messages = response.get("Messages", [])
            results: list[dict[str, Any]] = []

            for msg in raw_messages:
                body_raw = msg.get("Body", "{}")
                try:
                    parsed_body = json.loads(body_raw)
                except (json.JSONDecodeError, TypeError):
                    parsed_body = body_raw

                results.append(
                    {
                        "message_id": msg.get("MessageId", ""),
                        "receipt_handle": msg.get("ReceiptHandle", ""),
                        "body": parsed_body,
                        "receive_count": int(
                            msg.get("Attributes", {}).get("ApproximateReceiveCount", "1")
                        ),
                        "raw_message": msg,
                    }
                )

            return results
        except (ClientError, BotoCoreError, Exception) as exc:
            logger.error("SQS 메시지 수신 실패 (queueUrl=%s): %s", target_url, exc, exc_info=True)
            raise SqsClientError(f"SQS 메시지 수신 실패: {exc}") from exc

    def delete_message(
        self,
        receipt_handle: str,
        queue_url: str | None = None,
    ) -> bool:
        """처리 완료된 메시지를 SQS 큐에서 삭제합니다."""
        target_url = self._resolve_queue_url(queue_url)
        try:
            self._client.delete_message(
                QueueUrl=target_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info("SQS 메시지 삭제 성공 (receiptHandle=%s...)", receipt_handle[:16])
            return True
        except (ClientError, BotoCoreError, Exception) as exc:
            logger.error(
                "SQS 메시지 삭제 실패 (queueUrl=%s, handle=%s...): %s",
                target_url,
                receipt_handle[:16],
                exc,
                exc_info=True,
            )
            raise SqsClientError(f"SQS 메시지 삭제 실패: {exc}") from exc

    def change_message_visibility(
        self,
        receipt_handle: str,
        visibility_timeout: int,
        queue_url: str | None = None,
    ) -> bool:
        """메시지 처리 시간 연장을 위해 VisibilityTimeout을 변경합니다."""
        target_url = self._resolve_queue_url(queue_url)
        try:
            self._client.change_message_visibility(
                QueueUrl=target_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
            return True
        except (ClientError, BotoCoreError, Exception) as exc:
            logger.warning("SQS 가시성 타임아웃 변경 실패: %s", exc)
            return False
