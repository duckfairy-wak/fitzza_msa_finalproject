from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any, Optional

from app.clients.sqs_client import SqsClient, SqsClientError
from app.core.config import Settings, get_settings
from app.core.tracing import setup_tracing
from app.services.vton_generator import VtonValidationError
from app.services.vton_processor import (
    _run_background_vton,
    get_last_vton_error,
    get_notification_client,
    get_repo,
)

logger = logging.getLogger("vton_worker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [vton-worker] %(message)s",
)


class VtonWorker:
    """AWS SQS 대기열을 소비(Consume/Polling)하여 가상 피팅 작업을 처리하는 독립 실행형 워커."""

    def __init__(
        self,
        settings: Settings | None = None,
        sqs_client: SqsClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sqs_client = sqs_client or SqsClient(settings=self.settings)
        self.is_running = False

    def process_message(self, message: dict[str, Any]) -> bool:
        """단일 SQS 메시지를 수신하여 비동기 피팅을 수행하고 메시지를 삭제합니다."""
        receipt_handle = message.get("receipt_handle")
        payload = message.get("body")
        receive_count = message.get("receive_count", 1)

        if not isinstance(payload, dict):
            logger.error(
                "잘못된 SQS 메시지 페이로드 수신 (attempt=%s): %s",
                receive_count,
                payload,
            )
            return False

        fitting_id = payload.get("fitting_id")
        user_id = payload.get("user_id")
        photo_id = payload.get("photo_id")
        product_ids = payload.get("product_ids") or []
        result_image_url = payload.get("result_image_url") or f"/api/vton/{fitting_id}/image"
        request_id_header = payload.get("request_id_header")
        raw_item_image_urls = payload.get("item_image_urls")
        item_image_urls: dict[int, str] | None = None
        if isinstance(raw_item_image_urls, dict):
            item_image_urls = {}
            for k, v in raw_item_image_urls.items():
                try:
                    item_image_urls[int(k)] = str(v)
                except (ValueError, TypeError):
                    pass
        finalize_failure = receive_count >= self.settings.sqs_max_receive_count

        if fitting_id is None or user_id is None:
            logger.error(
                "필수 식별자 누락 (fitting_id=%s, user_id=%s, attempt=%s)",
                fitting_id,
                user_id,
                receive_count,
            )
            return False

        logger.info(
            "SQS 피팅 작업 수신 -> 처리 시작 (fittingId=%s, userId=%s, products=%s, attempt=%s)",
            fitting_id,
            user_id,
            product_ids,
            receive_count,
        )

        try:
            # 1. 실제 비동기 피팅 파이프라인 수행 (OpenAI 이미지 생성 -> S3 업로드 -> DB 상태 갱신 -> FCM 알림)
            vton_kwargs: dict[str, Any] = {
                "fitting_id": fitting_id,
                "user_id": user_id,
                "photo_id": photo_id,
                "product_ids": product_ids,
                "result_image_url": result_image_url,
                "request_id_header": request_id_header,
                "user_face_bytes": None,  # 워커 프로세스는 저장된 S3/로컬 파일 참조
                "finalize_failure": finalize_failure,
            }
            if item_image_urls:
                vton_kwargs["item_image_urls"] = item_image_urls
            completed = _run_background_vton(**vton_kwargs)
            if not completed:
                last_err = get_last_vton_error()
                if isinstance(last_err, VtonValidationError):
                    raise last_err
                raise RuntimeError("VTON background pipeline reported failure")

            # 2. 작업 성공 시 SQS 대기열에서 메시지 삭제
            if receipt_handle:
                self.sqs_client.delete_message(receipt_handle)

            logger.info("SQS 피팅 작업 성공 및 메시지 삭제 완료 (fittingId=%s)", fitting_id)
            return True

        except VtonValidationError as val_exc:
            logger.warning(
                "SQS 피팅 작업 검증 오류 발생(재시도 불가) -> 즉시 FAILED 처리 및 메시지 삭제 "
                "(fittingId=%s, attempt=%s): %s",
                fitting_id,
                receive_count,
                val_exc,
            )
            if get_last_vton_error() is None:
                try:
                    get_repo().update_fitting_failed(
                        fitting_id=fitting_id,
                        error_message=str(val_exc),
                    )
                    get_notification_client().send_fitting_failed(
                        user_id=user_id,
                        fitting_id=fitting_id,
                        request_id_header=request_id_header,
                    )
                except Exception as db_exc:
                    logger.warning(
                        "검증 오류 상태 기록 중 예외 발생 (fittingId=%s): %s",
                        fitting_id,
                        db_exc,
                    )
            if receipt_handle:
                self.sqs_client.delete_message(receipt_handle)
            return False

        except Exception as exc:
            logger.error(
                "SQS 피팅 작업 실행 중 예외 발생; 메시지를 삭제하지 않아 SQS 재시도/DLQ 정책을 따릅니다 "
                "(fittingId=%s, attempt=%s): %s",
                fitting_id,
                receive_count,
                exc,
                exc_info=True,
            )
            return False

    def run(self, max_iterations: Optional[int] = None) -> None:
        """워커 메인 루프 (Long Polling)."""
        self.is_running = True
        logger.info(
            "VTON SQS Worker 가동 시작 (queueUrl=%s, waitTime=%ds)",
            self.settings.aws_sqs_queue_url,
            self.settings.sqs_wait_time_seconds,
        )

        iterations = 0
        while self.is_running:
            if max_iterations is not None and iterations >= max_iterations:
                logger.info("최대 반복 횟수(%d) 도달로 워커를 정상 종료합니다.", max_iterations)
                break

            iterations += 1
            try:
                messages = self.sqs_client.receive_messages(
                    max_messages=self.settings.sqs_max_number_of_messages,
                    wait_time_seconds=self.settings.sqs_wait_time_seconds,
                    visibility_timeout=self.settings.sqs_visibility_timeout,
                )

                if not messages:
                    logger.debug("대기 중인 SQS 메시지 없음 (polling 계속)")
                    continue

                for msg in messages:
                    if not self.is_running:
                        break
                    self.process_message(msg)

            except SqsClientError as sqs_err:
                logger.warning("SQS 수신 일시적 실패 (재시도 대기): %s", sqs_err)
                time.sleep(2.0)
            except Exception as unhandled:
                logger.error("워커 메인 루프 예기치 않은 오류: %s", unhandled, exc_info=True)
                time.sleep(1.0)

        logger.info("VTON SQS Worker 종료 완료.")

    def stop(self) -> None:
        """워커를 안전하게 정지합니다."""
        logger.info("워커 종료 신호 수신, 현재 작업 완료 후 종료합니다...")
        self.is_running = False


def main() -> None:
    # 워커는 SQS 메시지로 작업을 받아 HTTP 요청이 없으므로 httpx 호출만 추적한다(API 요청과는 별개 trace).
    setup_tracing("vton-worker")
    worker = VtonWorker()

    def _sig_handler(signum: int, _frame: Any) -> None:
        logger.info("시스템 시그널(%s) 수신", signum)
        worker.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        worker.run()
    except Exception as exc:
        logger.critical("워커 프로세스 비정상 종료: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
