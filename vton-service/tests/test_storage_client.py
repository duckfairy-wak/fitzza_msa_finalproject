"""Tests for StorageClient and AWS S3 / CloudFront storage integration."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from PIL import Image

from app.api.vton import set_dependencies_for_tests
from app.clients.notification_client import NotificationServiceClient
from app.clients.product_client import ProductServiceClient
from app.clients.storage_client import StorageClient
from app.core.config import Settings, reset_settings_for_tests
from app.core.database import VtonRepository
from app.main import app


def _create_sample_png() -> bytes:
    img = Image.new("RGBA", (50, 50), (0, 255, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# StorageClient Unit Tests
# ---------------------------------------------------------------------------


def test_storage_client_properties() -> None:
    s_local = Settings(storage_backend="local")
    client_local = StorageClient(s_local)
    assert not client_local.is_s3

    s_s3 = Settings(storage_backend="s3")
    client_s3 = StorageClient(s_s3)
    assert client_s3.is_s3

    s_aws = Settings(storage_backend="aws")
    client_aws = StorageClient(s_aws)
    assert client_aws.is_s3


def test_extract_s3_key() -> None:
    settings = Settings(
        aws_s3_bucket_name="fitzza-assets",
        cloudfront_domain="https://d123.cloudfront.net",
    )
    client = StorageClient(settings)

    # Simple keys
    assert client._extract_s3_key("photos/user_1.png") == "photos/user_1.png"
    assert client._extract_s3_key("/photos/user_1.png") == "photos/user_1.png"

    # CloudFront URLs
    assert (
        client._extract_s3_key("https://d123.cloudfront.net/photos/user_1.png")
        == "photos/user_1.png"
    )

    # S3 standard URLs
    assert (
        client._extract_s3_key(
            "https://fitzza-assets.s3.ap-northeast-2.amazonaws.com/fittings/10.png"
        )
        == "fittings/10.png"
    )

    # LocalStack path-style URLs
    assert (
        client._extract_s3_key("http://localhost:4566/fitzza-assets/fittings/10.png")
        == "fittings/10.png"
    )


def test_get_public_url() -> None:
    # 1. CloudFront with https prefix
    s1 = Settings(
        cloudfront_domain="https://cdn.fitzza.com",
        aws_s3_bucket_name="fitzza-bucket",
    )
    c1 = StorageClient(s1)
    assert c1.get_public_url("fittings/1.png") == "https://cdn.fitzza.com/fittings/1.png"

    # 2. CloudFront without protocol prefix
    s2 = Settings(
        cloudfront_domain="d1234.cloudfront.net",
        aws_s3_bucket_name="fitzza-bucket",
    )
    c2 = StorageClient(s2)
    assert (
        c2.get_public_url("fittings/1.png") == "https://d1234.cloudfront.net/fittings/1.png"
    )

    # 3. LocalStack Endpoint URL
    s3 = Settings(
        cloudfront_domain="",
        aws_endpoint_url="http://localhost:4566",
        aws_s3_bucket_name="fitzza-test",
    )
    c3 = StorageClient(s3)
    assert (
        c3.get_public_url("fittings/1.png")
        == "http://localhost:4566/fitzza-test/fittings/1.png"
    )

    # 4. Standard S3 URL
    s4 = Settings(
        cloudfront_domain="",
        aws_endpoint_url="",
        aws_s3_bucket_name="fitzza-prod",
        aws_region="ap-northeast-2",
    )
    c4 = StorageClient(s4)
    assert (
        c4.get_public_url("fittings/1.png")
        == "https://fitzza-prod.s3.ap-northeast-2.amazonaws.com/fittings/1.png"
    )


def test_get_presigned_url() -> None:
    # 1. S3 모드에서 presigned URL 정상 생성 및 만료 시간 확인
    s_s3 = Settings(
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-prod",
        aws_region="ap-northeast-2",
    )
    c_s3 = StorageClient(s_s3)
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = (
        "https://fitzza-prod.s3.ap-northeast-2.amazonaws.com/fittings/1.png?AWSAccessKeyId=KEY&Signature=SIG&Expires=3600"
    )
    c_s3._s3_client = mock_s3

    # 키 형태 전달 시
    url = c_s3.get_presigned_url("fittings/1.png", expires_in=3600)
    assert "Expires=3600" in url
    mock_s3.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "fitzza-prod", "Key": "fittings/1.png"},
        ExpiresIn=3600,
    )

    # 전체 S3 URL 전달 시에도 S3 Key만 추출하여 서명
    url2 = c_s3.get_presigned_url(
        "https://fitzza-prod.s3.ap-northeast-2.amazonaws.com/fittings/1.png",
        expires_in=1800,
    )
    assert "Expires=3600" in url2
    mock_s3.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "fitzza-prod", "Key": "fittings/1.png"},
        ExpiresIn=1800,
    )

    # 2. CloudFront 도메인 설정 시 영구 CDN 캐싱 URL 반환
    s_cf = Settings(
        storage_backend="s3",
        cloudfront_domain="https://cdn.fitzza.site",
        aws_s3_bucket_name="fitzza-prod",
    )
    c_cf = StorageClient(s_cf)
    cf_url = c_cf.get_presigned_url("fittings/1.png")
    assert cf_url == "https://cdn.fitzza.site/fittings/1.png"

    # 3. 로컬 스토리지 모드 시 원본 경로/URL 반환 (Fallback)
    s_local = Settings(storage_backend="local")
    c_local = StorageClient(s_local)
    assert c_local.get_presigned_url("/data/fittings/1.png") == "/data/fittings/1.png"

    # 로컬 모드인데 cloudfront_domain이 설정되어 있어도 로컬 경로 반환
    s_local_cf = Settings(
        storage_backend="local",
        cloudfront_domain="https://cdn.fitzza.site",
    )
    c_local_cf = StorageClient(s_local_cf)
    assert c_local_cf.get_presigned_url("/data/fittings/1.png") == "/data/fittings/1.png"

    # 4. 빈 값 / None 전달 시 빈 문자열 반환
    assert c_s3.get_presigned_url("") == ""
    assert c_s3.get_presigned_url(None) == ""

    # 5. 레거시 엔드포인트 URL(/api/vton/42/image) 전달 시 fittings/42.png로 매핑되어 서명
    _ = c_s3.get_presigned_url("/api/vton/42/image", expires_in=3600)
    mock_s3.generate_presigned_url.assert_called_with(
        ClientMethod="get_object",
        Params={"Bucket": "fitzza-prod", "Key": "fittings/42.png"},
        ExpiresIn=3600,
    )


def test_local_storage_crud(tmp_path: Path) -> None:
    storage_dir = tmp_path / "data" / "fittings"
    storage_dir.mkdir(parents=True)
    settings = Settings(
        storage_backend="local",
        storage_dir=str(storage_dir),
    )
    client = StorageClient(settings)
    data = b"sample_png_bytes"

    # Upload
    stored_path = client.upload_bytes("photos/test_user.png", data)
    assert Path(stored_path).is_file()
    assert Path(stored_path).read_bytes() == data

    # Download via path
    downloaded = client.download_bytes(stored_path)
    assert downloaded == data

    # Download via relative key
    downloaded_key = client.download_bytes("photos/test_user.png")
    assert downloaded_key == data

    # Download non-existent raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        client.download_bytes("photos/non_existent.png")

    # Delete
    assert client.delete_object(stored_path) is True
    assert not Path(stored_path).exists()
    assert client.delete_object(stored_path) is False


def test_s3_storage_upload_and_download_mocked() -> None:
    settings = Settings(
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-test-bucket",
        cloudfront_domain="https://cdn.fitzza.com",
    )
    client = StorageClient(settings)

    mock_s3 = MagicMock()
    client._s3_client = mock_s3

    # Upload
    url = client.upload_bytes("photos/1/user.png", b"image-data", content_type="image/png")
    assert url == "https://cdn.fitzza.com/photos/1/user.png"
    mock_s3.put_object.assert_called_once_with(
        Bucket="fitzza-test-bucket",
        Key="photos/1/user.png",
        Body=b"image-data",
        ContentType="image/png",
    )

    # Download
    mock_body = MagicMock()
    mock_body.read.return_value = b"downloaded-image-data"
    mock_s3.get_object.return_value = {"Body": mock_body}

    downloaded = client.download_bytes("photos/1/user.png")
    assert downloaded == b"downloaded-image-data"
    mock_s3.get_object.assert_called_once_with(
        Bucket="fitzza-test-bucket",
        Key="photos/1/user.png",
    )

    # Delete
    assert client.delete_object("photos/1/user.png") is True
    mock_s3.delete_object.assert_called_once_with(
        Bucket="fitzza-test-bucket",
        Key="photos/1/user.png",
    )


def test_s3_storage_exceptions() -> None:
    settings = Settings(storage_backend="s3", aws_s3_bucket_name="fitzza-test")
    client = StorageClient(settings)
    mock_s3 = MagicMock()
    client._s3_client = mock_s3

    # Upload error raises IOError
    mock_s3.put_object.side_effect = Exception("AWS Network Error")
    with pytest.raises(IOError, match="스토리지 업로드 실패"):
        client.upload_bytes("test.png", b"bytes")

    # Download NoSuchKey raises FileNotFoundError
    client_err_404 = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Key not found"}},
        "GetObject",
    )
    mock_s3.get_object.side_effect = client_err_404
    with pytest.raises(FileNotFoundError, match="스토리지에서 파일을 찾을 수 없습니다"):
        client.download_bytes("non_existent.png")

    # Download other error raises IOError
    client_err_500 = ClientError(
        {"Error": {"Code": "InternalError", "Message": "S3 Down"}},
        "GetObject",
    )
    mock_s3.get_object.side_effect = client_err_500
    with pytest.raises(IOError, match="스토리지 다운로드 오류"):
        client.download_bytes("error.png")

    # Delete error returns False
    mock_s3.delete_object.side_effect = Exception("Delete failure")
    assert client.delete_object("test.png") is False


# ---------------------------------------------------------------------------
# API Integration Tests with StorageClient
# ---------------------------------------------------------------------------


def test_api_s3_upload_and_serving(tmp_path: Path) -> None:
    settings = Settings(
        db_path=":memory:",
        storage_backend="s3",
        aws_s3_bucket_name="fitzza-test-bucket",
        cloudfront_domain="https://cdn.fitzza.com",
        storage_dir=str(tmp_path / "fittings"),
        photos_dir=str(tmp_path / "photos"),
        community_service_token="community-secret-token-32bytes-long-padding!",
        vton_service_token="vton-secret-token-32bytes-long-padding-ok!",
        product_service_url="http://localhost:8082",
        notification_service_url="http://localhost:8086",
    )
    reset_settings_for_tests(settings)

    repo = VtonRepository(db_path=":memory:")
    prod_client = ProductServiceClient(settings)
    notif_client = NotificationServiceClient(settings)
    storage_client = StorageClient(settings)

    mock_s3 = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = _create_sample_png()
    mock_s3.get_object.return_value = {"Body": mock_body}
    storage_client._s3_client = mock_s3

    set_dependencies_for_tests(
        repo=repo,
        product_client=prod_client,
        notification_client=notif_client,
        storage_client=storage_client,
    )

    client = TestClient(app)

    # 1. Request fitting with userImage via multipart form
    png_data = _create_sample_png()
    with patch("app.api.vton.generate_tryon_image", return_value=_create_sample_png()):
        response = client.post(
            "/api/vton",
            headers={"X-User-Id": "100"},
            data={"productIds": "[101]"},
            files={"userImage": ("face.png", png_data, "image/png")},
        )
        assert response.status_code == 202
        fitting_id = response.json()["fittingId"]

    # Verify S3 put_object was called for both user photo and completed fitting
    assert mock_s3.put_object.call_count == 2
    first_call_args = mock_s3.put_object.call_args_list[0][1]
    assert first_call_args["Bucket"] == "fitzza-test-bucket"
    assert first_call_args["Key"].startswith("user-images/100/user_100_")

    second_call_args = mock_s3.put_object.call_args_list[1][1]
    assert second_call_args["Bucket"] == "fitzza-test-bucket"
    assert second_call_args["Key"] == f"fittings/{fitting_id}.png"

    # 2. Get fitting user image via GET /api/vton/{fittingId}/user-image
    user_img_resp = client.get(
        f"/api/vton/{fitting_id}/user-image",
        headers={"X-User-Id": "100"},
    )
    assert user_img_resp.status_code == 200
    assert user_img_resp.headers["content-type"] == "image/png"
    assert len(user_img_resp.content) > 0

    # 3. Mark fitting completed and get fitting image from S3 (with IDOR protection checks)
    repo.mark_completed(
        fitting_id,
        result_image_url=f"https://cdn.fitzza.com/fittings/{fitting_id}.png",
    )
    # 3-1. 비인증 요청 시 401 Unauthorized
    resp_unauth = client.get(f"/api/vton/{fitting_id}/image")
    assert resp_unauth.status_code == 401

    # 3-2. 타 사용자 요청 시 403 Forbidden
    resp_forbidden = client.get(
        f"/api/vton/{fitting_id}/image",
        headers={"X-User-Id": "999"},
    )
    assert resp_forbidden.status_code == 403

    # 3-3. 본인 요청 시 S3 307 Temporary Redirect
    fit_img_resp = client.get(
        f"/api/vton/{fitting_id}/image",
        headers={"X-User-Id": "100"},
        follow_redirects=False,
    )
    assert fit_img_resp.status_code == 307
    assert fit_img_resp.headers["location"] == f"https://cdn.fitzza.com/fittings/{fitting_id}.png"
    assert fit_img_resp.headers["cache-control"] == "no-cache, no-store, must-revalidate"

    # Cleanup dependencies
    set_dependencies_for_tests(None, None, None, None)
    reset_settings_for_tests(None)
