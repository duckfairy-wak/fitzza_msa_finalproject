import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.api.vton import set_dependencies_for_tests
from app.clients.sqs_client import SqsClient, SqsClientError
from app.core.config import Settings
from app.core.database import VtonRepository
from app.main import app
from app.worker import VtonWorker


@pytest.fixture
def mock_boto_sqs():
    mock_client = MagicMock()
    mock_client.send_message.return_value = {"MessageId": "msg-12345"}
    mock_client.receive_message.return_value = {
        "Messages": [
            {
                "MessageId": "msg-12345",
                "ReceiptHandle": "receipt-token-abc",
                "Attributes": {"ApproximateReceiveCount": "2"},
                "Body": json.dumps(
                    {
                        "fitting_id": 1,
                        "user_id": 42,
                        "photo_id": None,
                        "product_ids": [101, 102],
                        "result_image_url": "/api/vton/1/image",
                        "request_id_header": "req-trace-1",
                    }
                ),
            }
        ]
    }
    mock_client.delete_message.return_value = {}
    mock_client.change_message_visibility.return_value = {}
    return mock_client


@pytest.fixture
def sqs_settings():
    return Settings(
        queue_backend="sqs",
        aws_sqs_queue_url="https://sqs.ap-northeast-2.amazonaws.com/123456789012/fitzza-vton-queue",
        aws_sqs_dlq_url="https://sqs.ap-northeast-2.amazonaws.com/123456789012/fitzza-vton-dlq",
        sqs_visibility_timeout=300,
        sqs_wait_time_seconds=20,
        sqs_max_receive_count=3,
    )


@pytest.fixture(autouse=True)
def cleanup_vton_dependencies():
    yield
    set_dependencies_for_tests(None, None, None, None)


# ---------------------------------------------------------------------------
# 1. SqsClient Unit Tests
# ---------------------------------------------------------------------------

def test_sqs_client_send_message_success(mock_boto_sqs, sqs_settings):
    client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)

    payload = {"fitting_id": 10, "user_id": 5}
    msg_id = client.send_message(payload)

    assert msg_id == "msg-12345"
    mock_boto_sqs.send_message.assert_called_once()
    call_kwargs = mock_boto_sqs.send_message.call_args.kwargs
    assert call_kwargs["QueueUrl"] == sqs_settings.aws_sqs_queue_url
    assert json.loads(call_kwargs["MessageBody"]) == payload


def test_sqs_client_receive_messages_success(mock_boto_sqs, sqs_settings):
    client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)

    messages = client.receive_messages(max_messages=1)
    assert len(messages) == 1
    msg = messages[0]
    assert msg["message_id"] == "msg-12345"
    assert msg["receipt_handle"] == "receipt-token-abc"
    assert msg["body"]["fitting_id"] == 1
    assert msg["body"]["user_id"] == 42
    assert msg["receive_count"] == 2
    assert mock_boto_sqs.receive_message.call_args.kwargs["AttributeNames"] == [
        "ApproximateReceiveCount"
    ]


def test_sqs_client_delete_message_success(mock_boto_sqs, sqs_settings):
    client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)

    res = client.delete_message("receipt-token-abc")
    assert res is True
    mock_boto_sqs.delete_message.assert_called_once_with(
        QueueUrl=sqs_settings.aws_sqs_queue_url,
        ReceiptHandle="receipt-token-abc",
    )


def test_sqs_client_change_visibility(mock_boto_sqs, sqs_settings):
    client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)

    res = client.change_message_visibility("receipt-token-abc", visibility_timeout=60)
    assert res is True
    mock_boto_sqs.change_message_visibility.assert_called_once_with(
        QueueUrl=sqs_settings.aws_sqs_queue_url,
        ReceiptHandle="receipt-token-abc",
        VisibilityTimeout=60,
    )


def test_sqs_client_raises_on_boto_error(mock_boto_sqs, sqs_settings):
    mock_boto_sqs.send_message.side_effect = ClientError(
        {"Error": {"Code": "QueueDoesNotExist", "Message": "Queue not found"}},
        "SendMessage",
    )
    client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)

    with pytest.raises(SqsClientError):
        client.send_message({"foo": "bar"})


# ---------------------------------------------------------------------------
# 2. API Producer Routing Test (QUEUE_BACKEND=sqs vs memory)
# ---------------------------------------------------------------------------

def test_api_produces_to_sqs_when_backend_is_sqs(tmp_path, mock_boto_sqs):
    db_file = tmp_path / "vton_test.db"
    settings = Settings(
        db_path=str(db_file),
        queue_backend="sqs",
        aws_sqs_queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/queue",
    )
    repo = VtonRepository(db_path=str(db_file))
    mock_sqs_client = SqsClient(settings=settings, sqs_client=mock_boto_sqs)

    set_dependencies_for_tests(
        repo=repo,
        sqs_client=mock_sqs_client,
    )

    with patch("app.api.vton.get_settings", return_value=settings):
        with patch("app.api.vton._run_background_vton") as mock_bg_vton:
            with TestClient(app) as client:
                res = client.post(
                    "/api/vton",
                    headers={"X-User-Id": "10", "X-Request-Id": "trace-sqs-test"},
                    json={"productIds": [101]},
                )
                assert res.status_code == 202
                data = res.json()
                assert data["status"] == "PENDING"
                fitting_id = data["fittingId"]

                # SQS producer should have sent message
                mock_boto_sqs.send_message.assert_called_once()
                call_body = json.loads(mock_boto_sqs.send_message.call_args.kwargs["MessageBody"])
                assert call_body["fitting_id"] == fitting_id
                assert call_body["user_id"] == 10
                assert call_body["product_ids"] == [101]
                assert call_body["request_id_header"] == "trace-sqs-test"

                # In-memory background task was NOT invoked
                mock_bg_vton.assert_not_called()


# ---------------------------------------------------------------------------
# 3. VtonWorker Consumer Tests
# ---------------------------------------------------------------------------

def test_vton_worker_process_message_success(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    msg = {
        "message_id": "msg-1",
        "receipt_handle": "handle-123",
        "body": {
            "fitting_id": 20,
            "user_id": 7,
            "photo_id": None,
            "product_ids": [201],
            "result_image_url": "/api/vton/20/image",
            "request_id_header": "req-trace-worker",
        },
    }

    with patch("app.worker._run_background_vton", return_value=True) as mock_run_vton:
        success = worker.process_message(msg)
        assert success is True
        mock_run_vton.assert_called_once_with(
            fitting_id=20,
            user_id=7,
            photo_id=None,
            product_ids=[201],
            result_image_url="/api/vton/20/image",
            request_id_header="req-trace-worker",
            user_face_bytes=None,
            finalize_failure=False,
        )
        # Message was deleted after success
        mock_boto_sqs.delete_message.assert_called_once_with(
            QueueUrl=sqs_settings.aws_sqs_queue_url,
            ReceiptHandle="handle-123",
        )


def test_vton_worker_process_message_failure_leaves_message_for_redrive(
    mock_boto_sqs, sqs_settings
):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    msg = {
        "message_id": "msg-err",
        "receipt_handle": "handle-err",
        "receive_count": 2,
        "body": {
            "fitting_id": 99,
            "user_id": 7,
            "product_ids": [201],
        },
    }

    with patch("app.worker._run_background_vton", side_effect=RuntimeError("OpenAI API Down")):
        success = worker.process_message(msg)
        assert success is False

        mock_boto_sqs.send_message.assert_not_called()
        mock_boto_sqs.delete_message.assert_not_called()


def test_vton_worker_treats_reported_pipeline_failure_as_failure(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)
    msg = {
        "receipt_handle": "handle-failed",
        "body": {"fitting_id": 100, "user_id": 7, "product_ids": [201]},
    }

    with patch("app.worker._run_background_vton", return_value=False):
        success = worker.process_message(msg)

    assert success is False
    mock_boto_sqs.send_message.assert_not_called()
    mock_boto_sqs.delete_message.assert_not_called()


def test_vton_worker_finalizes_failure_only_on_last_receive(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)
    msg = {
        "receipt_handle": "handle-final-attempt",
        "receive_count": 3,
        "body": {"fitting_id": 102, "user_id": 7, "product_ids": [201]},
    }

    with patch("app.worker._run_background_vton", return_value=False) as mock_run_vton:
        success = worker.process_message(msg)

    assert success is False
    assert mock_run_vton.call_args.kwargs["finalize_failure"] is True
    mock_boto_sqs.delete_message.assert_not_called()


def test_vton_worker_keeps_source_message_until_sqs_redrives(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)
    msg = {
        "receipt_handle": "handle-retry",
        "body": {"fitting_id": 101, "user_id": 7, "product_ids": [201]},
    }

    with patch("app.worker._run_background_vton", return_value=False):
        success = worker.process_message(msg)

    assert success is False
    mock_boto_sqs.delete_message.assert_not_called()


def test_vton_worker_run_stops_after_max_iterations(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    with patch.object(worker, "process_message") as mock_proc:
        worker.run(max_iterations=1)
        assert mock_proc.call_count == 1
        assert worker.is_running is True


def test_vton_worker_handles_invalid_message_payload(mock_boto_sqs, sqs_settings):
    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    # Missing fitting_id
    bad_msg = {
        "message_id": "bad-1",
        "receipt_handle": "handle-bad",
        "body": {"foo": "bar"},
    }
    success = worker.process_message(bad_msg)
    assert success is False
    # SQS moves poison messages to the configured DLQ after maxReceiveCount.
    mock_boto_sqs.delete_message.assert_not_called()


def test_api_marks_fitting_failed_and_returns_502_when_sqs_send_fails(tmp_path, mock_boto_sqs):
    db_file = tmp_path / "vton_sqs_fail.db"
    settings = Settings(
        db_path=str(db_file),
        queue_backend="sqs",
        aws_sqs_queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/queue",
    )
    repo = VtonRepository(db_path=str(db_file))
    mock_boto_sqs.send_message.side_effect = ClientError(
        {"Error": {"Code": "ServiceUnavailable", "Message": "SQS unavailable"}},
        "SendMessage",
    )
    mock_sqs_client = SqsClient(settings=settings, sqs_client=mock_boto_sqs)

    set_dependencies_for_tests(
        repo=repo,
        sqs_client=mock_sqs_client,
    )

    with patch("app.api.vton.get_settings", return_value=settings):
        with TestClient(app) as client:
            res = client.post(
                "/api/vton",
                headers={"X-User-Id": "10"},
                json={"productIds": [101]},
            )
            assert res.status_code == 502
            items, total = repo.get_user_fittings(user_id=10, limit=10, offset=0)
            assert total == 1
            assert items[0]["status"] == "FAILED"


def test_vton_worker_deletes_message_immediately_on_validation_error(tmp_path, mock_boto_sqs, sqs_settings):
    from app.services.vton_generator import VtonValidationError

    db_file = tmp_path / "vton_val_err.db"
    repo = VtonRepository(db_path=str(db_file))
    mock_prod = MagicMock()
    mock_notif = MagicMock()
    mock_prod.resolve_product_item.side_effect = VtonValidationError("동일 카테고리 중복 피팅 불가")

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod,
        notification_client=mock_notif,
    )
    fitting_id = repo.create_fitting(user_id=7, photo_id=None, product_ids=[101, 102])

    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    msg = {
        "message_id": "msg-val-err",
        "receipt_handle": "handle-val-err",
        "receive_count": 1,
        "body": {
            "fitting_id": fitting_id,
            "user_id": 7,
            "photo_id": None,
            "product_ids": [101, 102],
        },
    }

    success = worker.process_message(msg)
    assert success is False

    detail = repo.get_fitting_detail(fitting_id)
    assert detail is not None
    assert detail["status"] == "FAILED"
    assert "동일 카테고리 중복 피팅 불가" in detail["errorMessage"]
    mock_notif.send_fitting_failed.assert_called_once()
    mock_boto_sqs.delete_message.assert_called_once_with(
        QueueUrl=sqs_settings.aws_sqs_queue_url,
        ReceiptHandle="handle-val-err",
    )


def test_vton_worker_restores_int_keys_after_json_roundtrip(tmp_path, mock_boto_sqs, sqs_settings):
    """SQS 직렬화/역직렬화(json.dumps -> json.loads) 시 문자열 키로 변환된 item_image_urls가
    워커에서 정수 키로 정상 복원되어 배경 피팅 파이프라인으로 전달되는지 검증."""
    db_file = tmp_path / "vton_roundtrip.db"
    repo = VtonRepository(db_path=str(db_file))
    fitting_id = repo.create_fitting(user_id=42, photo_id=None, product_ids=[101, 202])

    sqs_client = SqsClient(settings=sqs_settings, sqs_client=mock_boto_sqs)
    worker = VtonWorker(settings=sqs_settings, sqs_client=sqs_client)

    original_payload = {
        "fitting_id": fitting_id,
        "user_id": 42,
        "photo_id": None,
        "product_ids": [101, 202],
        "item_image_urls": {
            101: "https://cdn.example.com/color-101.jpg",
            202: "https://cdn.example.com/color-202.jpg",
        },
    }

    # SQS 전송 및 수신 시 발생하는 JSON 왕복 (정수 키가 문자열 "101", "202"로 변환됨)
    serialized_body = json.dumps(original_payload)
    deserialized_body = json.loads(serialized_body)
    assert "101" in deserialized_body["item_image_urls"]

    msg = {
        "message_id": "msg-roundtrip",
        "receipt_handle": "handle-roundtrip",
        "receive_count": 1,
        "body": deserialized_body,
    }

    with patch("app.worker._run_background_vton", return_value=True) as mock_bg_vton:
        success = worker.process_message(msg)
        assert success is True
        mock_bg_vton.assert_called_once()
        called_item_image_urls = mock_bg_vton.call_args.kwargs.get("item_image_urls")
        assert called_item_image_urls == {
            101: "https://cdn.example.com/color-101.jpg",
            202: "https://cdn.example.com/color-202.jpg",
        }
