"""vton-service 비동기 API 엔드포인트 및 클라이언트 테스트."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api.vton import (
    _run_background_vton,
    set_dependencies_for_tests,
)
from app.clients.notification_client import NotificationServiceClient
from app.clients.product_client import ProductServiceClient
from app.core.config import Settings, reset_settings_for_tests
from app.core.database import VtonRepository
from app.main import app


def _create_sample_png() -> bytes:
    img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path: Path):
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=":memory:",
        storage_dir=str(test_storage),
        community_service_token="community-secret-token-32bytes-long-padding!",
        vton_service_token="vton-secret-token-32bytes-long-padding-ok!",
        product_service_url="http://localhost:8082",
        notification_service_url="http://localhost:8086",
        public_base_url="http://api.fitzza.com",
    )
    reset_settings_for_tests(settings)
    repo = VtonRepository(db_path=":memory:")
    prod_client = ProductServiceClient(settings)
    notif_client = NotificationServiceClient(settings)
    set_dependencies_for_tests(
        repo=repo,
        product_client=prod_client,
        notification_client=notif_client,
    )
    yield
    set_dependencies_for_tests(None, None, None)
    reset_settings_for_tests(None)


def test_post_vton_requires_x_user_id() -> None:
    client = TestClient(app)
    resp = client.post("/api/vton", json={"productIds": [101]})
    assert resp.status_code == 401  # Header 누락 시 401 Unauthorized


def test_post_vton_enforces_product_limit() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/vton",
        json={"productIds": [1, 2, 3, 4, 5, 6]},
        headers={"X-User-Id": "1"},
    )
    assert resp.status_code == 400  # RequestValidationError 핸들러로 400 반환
    assert resp.json()["code"] == "INVALID_REQUEST"


def test_post_vton_returns_202_accepted() -> None:
    client = TestClient(app)
    with patch("app.api.vton._run_background_vton") as mock_bg:
        resp = client.post(
            "/api/vton",
            json={"photoId": None, "productIds": [101, 102]},
            headers={"X-User-Id": "7"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "fittingId" in body
        assert body["status"] == "PENDING"
        assert mock_bg.called


def test_background_vton_success_flow(tmp_path: Path) -> None:
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    mock_prod_client.resolve_product_item.side_effect = [
        {
            "productId": 101,
            "productName": "티셔츠",
            "price": 20000,
            "imageUrl": "https://cdn.example.com/top.png",
            "categoryName": "상의",
            "imageBytes": _create_sample_png(),
        },
        {
            "productId": 201,
            "productName": "바지",
            "price": 30000,
            "imageUrl": "https://cdn.example.com/bottom.png",
            "categoryName": "하의",
            "imageBytes": _create_sample_png(),
        },
    ]

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=None, product_ids=[101, 201])
    result_url = f"http://api.fitzza.com/api/vton/{fitting_id}/image"

    with patch("app.api.vton.generate_tryon_image", return_value=_create_sample_png()):
        completed = _run_background_vton(
            fitting_id=fitting_id,
            user_id=7,
            photo_id=None,
            product_ids=[101, 201],
            result_image_url=result_url,
        )

    assert completed is True
    detail = repo.get_fitting_detail(fitting_id)
    assert detail is not None
    assert detail["status"] == "COMPLETED"
    assert detail["resultImageUrl"] == result_url
    assert len(detail["products"]) == 2
    assert detail["products"][0]["productName"] == "티셔츠"

    mock_notif_client.send_fitting_done.assert_called_once()


def test_background_vton_failure_flow() -> None:
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    mock_prod_client.resolve_product_item.side_effect = RuntimeError("OpenAI error")

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=1, product_ids=[101])

    completed = _run_background_vton(
        fitting_id=fitting_id,
        user_id=7,
        photo_id=1,
        product_ids=[101],
        result_image_url="http://dummy/image",
    )

    assert completed is False
    detail = repo.get_fitting_detail(fitting_id)
    assert detail is not None
    assert detail["status"] == "FAILED"
    assert "가상 피팅 생성 중 오류가 발생했습니다." in detail["errorMessage"]

    mock_notif_client.send_fitting_failed.assert_called_once()


def test_background_vton_duplicate_category_flow() -> None:
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    mock_prod_client.resolve_product_item.side_effect = [
        {
            "productId": 101,
            "productName": "상의 1",
            "price": 20000,
            "imageUrl": "https://cdn.example.com/top1.png",
            "categoryName": "상의",
            "imageBytes": _create_sample_png(),
        },
        {
            "productId": 102,
            "productName": "상의 2",
            "price": 25000,
            "imageUrl": "https://cdn.example.com/top2.png",
            "categoryName": "상의",
            "imageBytes": _create_sample_png(),
        },
    ]

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=None, product_ids=[101, 102])

    completed = _run_background_vton(
        fitting_id=fitting_id,
        user_id=7,
        photo_id=None,
        product_ids=[101, 102],
        result_image_url="/api/vton/1/image",
    )

    assert completed is False
    detail = repo.get_fitting_detail(fitting_id)
    assert detail is not None
    assert detail["status"] == "FAILED"
    assert "같은 카테고리(상의)의 상품은 하나만 피팅할 수 있습니다." in detail["errorMessage"]
    mock_notif_client.send_fitting_failed.assert_called_once()


def test_get_fitting_detail_owner_and_forbidden() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    fitting_id = repo.create_fitting(user_id=7, photo_id=1, product_ids=[101])
    repo.save_fitting_products(
        fitting_id,
        [
            {
                "productId": 101,
                "productName": "상의 상품",
                "price": 15000,
                "imageUrl": "https://img.png",
                "categoryName": "상의",
            }
        ],
    )
    repo.mark_completed(fitting_id, "http://api.fitzza.com/api/vton/1/image")

    # 본인 요청 (200 OK)
    resp = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["fittingId"] == fitting_id
    assert data["status"] == "COMPLETED"
    assert len(data["products"]) == 1

    # 타인 요청 (403 Forbidden)
    resp_other = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "999"})
    assert resp_other.status_code == 403

    # 없는 피팅 (404 Not Found)
    resp_404 = client.get("/api/vton/99999", headers={"X-User-Id": "7"})
    assert resp_404.status_code == 404


def test_get_fitting_image_serving(tmp_path: Path) -> None:
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=":memory:",
        storage_dir=str(test_storage),
    )
    reset_settings_for_tests(settings)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    fitting_id = repo.create_fitting(user_id=7, photo_id=1, product_ids=[101])
    repo.mark_completed(fitting_id, f"/api/vton/{fitting_id}/image")

    # 아직 파일이 디스크에 없음 -> 404
    client = TestClient(app)
    resp_missing = client.get(f"/api/vton/{fitting_id}/image")
    assert resp_missing.status_code == 404

    # 이미지 파일 저장 후 요청 -> 200 image/png
    img_bytes = _create_sample_png()
    (test_storage / f"{fitting_id}.png").write_bytes(img_bytes)

    resp_ok = client.get(f"/api/vton/{fitting_id}/image")
    assert resp_ok.status_code == 200
    assert resp_ok.headers["content-type"] == "image/png"
    assert resp_ok.content == img_bytes


def test_internal_fitting_endpoint_for_community() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    fitting_id = repo.create_fitting(user_id=7, photo_id=1, product_ids=[101])
    repo.save_fitting_products(
        fitting_id,
        [
            {
                "productId": 101,
                "productName": "테스트 셔츠",
                "price": 39000,
                "imageUrl": "https://cdn.example.com/1.png",
                "categoryName": "상의",
            }
        ],
    )
    repo.mark_completed(fitting_id, "http://api.fitzza.com/api/vton/1/image")

    token = "community-secret-token-32bytes-long-padding!"

    # 1. 정상 호출 - 본인 (owned=True)
    resp = client.get(
        f"/fittings/{fitting_id}?userId=7",
        headers={"X-Service-Token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["owned"] is True
    assert data["status"] == "COMPLETED"
    assert data["resultImageUrl"] == "http://api.fitzza.com/api/vton/1/image"
    assert len(data["products"]) == 1
    assert data["products"][0]["productId"] == 101

    # 2. 타인 피팅 조회 (owned=False)
    resp_other = client.get(
        f"/fittings/{fitting_id}?userId=999",
        headers={"X-Service-Token": token},
    )
    assert resp_other.status_code == 200
    assert resp_other.json()["owned"] is False

    # 3. 없는 피팅 (404)
    resp_404 = client.get(
        "/fittings/99999?userId=7",
        headers={"X-Service-Token": token},
    )
    assert resp_404.status_code == 404

    # 4. 토큰 누락 또는 유효하지 않은 토큰 (401)
    resp_unauth = client.get(
        f"/fittings/{fitting_id}?userId=7",
        headers={"X-Service-Token": "invalid-token"},
    )
    assert resp_unauth.status_code == 401


def test_delete_fitting_and_defend_access(tmp_path: Path) -> None:
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=":memory:",
        storage_dir=str(test_storage),
    )
    reset_settings_for_tests(settings)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)
    client = TestClient(app)

    fitting_id = repo.create_fitting(user_id=7, photo_id=1, product_ids=[101])
    repo.mark_completed(fitting_id, f"/api/vton/{fitting_id}/image")
    img_bytes = _create_sample_png()
    (test_storage / f"{fitting_id}.png").write_bytes(img_bytes)

    # 1. 삭제 전 정상 조회 가능
    resp = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp.status_code == 200
    resp_img = client.get(f"/api/vton/{fitting_id}/image")
    assert resp_img.status_code == 200

    # 2. 타인이 삭제 요청 시 403 Forbidden
    resp_forbid = client.delete(f"/api/vton/{fitting_id}", headers={"X-User-Id": "999"})
    assert resp_forbid.status_code == 403

    # 2-1. X-User-Id 누락 시 401 Unauthorized
    resp_no_auth = client.delete(f"/api/vton/{fitting_id}")
    assert resp_no_auth.status_code == 401

    # 3. 본인이 정상 삭제 (204 No Content)
    resp_del = client.delete(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp_del.status_code == 204

    # 4. 삭제 후 상세 조회 차단 (404 Not Found)
    resp_get_after = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp_get_after.status_code == 404

    # 5. 삭제 후 이미지 서빙 차단 (404 Not Found)
    resp_img_after = client.get(f"/api/vton/{fitting_id}/image")
    assert resp_img_after.status_code == 404

    # 6. 이미 삭제된 피팅 재삭제 시도 시 404 Not Found
    resp_del_again = client.delete(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp_del_again.status_code == 404


def test_list_user_fittings_flow() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    # 1. 인증 헤더 누락 시 401 Unauthorized
    resp_no_auth = client.get("/api/vton")
    assert resp_no_auth.status_code == 401

    # 2. 사용자 7에 대한 피팅 생성 3건 (하나는 삭제 처리)
    f1 = repo.create_fitting(user_id=7, photo_id=None, product_ids=[101])
    f2 = repo.create_fitting(user_id=7, photo_id=None, product_ids=[102])
    f3 = repo.create_fitting(user_id=7, photo_id=None, product_ids=[103])
    # 다른 사용자(8) 피팅 1건
    f_other = repo.create_fitting(user_id=8, photo_id=None, product_ids=[201])
    # f2는 소프트 삭제
    repo.delete_fitting(f2, user_id=7)

    # 3. 사용자 7 목록 조회 (삭제된 f2 제외, 총 2건)
    resp = client.get("/api/vton?limit=10&offset=0", headers={"X-User-Id": "7"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalCount"] == 2
    assert len(data["items"]) == 2
    # 최신순 정렬 확인 (f3, f1)
    ids = [item["fittingId"] for item in data["items"]]
    assert ids == [f3, f1]

    # 4. 페이징 확인 (limit=1, offset=1)
    resp_paged = client.get("/api/vton?limit=1&offset=1", headers={"X-User-Id": "7"})
    assert resp_paged.status_code == 200
    paged_data = resp_paged.json()
    assert paged_data["totalCount"] == 2
    assert len(paged_data["items"]) == 1
    assert paged_data["items"][0]["fittingId"] == f1


def test_post_vton_multipart_user_image_flow() -> None:
    client = TestClient(app)
    img_bytes = _create_sample_png()

    with patch("app.api.vton._run_background_vton") as mock_bg:
        resp = client.post(
            "/api/vton",
            data={"productIds": "[101, 102]"},
            files={"userImage": ("my_face.png", img_bytes, "image/png")},
            headers={"X-User-Id": "7"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "fittingId" in data
        assert data["status"] == "PENDING"
        assert mock_bg.called


def test_post_vton_multipart_validations() -> None:
    client = TestClient(app)
    img_bytes = _create_sample_png()

    # 1. X-User-Id 누락 시 401 Unauthorized
    resp_no_auth = client.post(
        "/api/vton",
        data={"productIds": "[101]"},
        files={"userImage": ("photo.png", img_bytes, "image/png")},
    )
    assert resp_no_auth.status_code == 401

    # 2. productIds 누락 시 400 Bad Request
    resp_no_pids = client.post(
        "/api/vton",
        files={"userImage": ("photo.png", img_bytes, "image/png")},
        headers={"X-User-Id": "7"},
    )
    assert resp_no_pids.status_code == 400

    # 3. 손상된/유효하지 않은 이미지 데이터 시 400 Bad Request
    resp_corrupt = client.post(
        "/api/vton",
        data={"productIds": "[101]"},
        files={"userImage": ("corrupt.png", b"not-a-real-png", "image/png")},
        headers={"X-User-Id": "7"},
    )
    assert resp_corrupt.status_code == 400
    assert "유효하지 않은 이미지" in resp_corrupt.json()["message"]

    # 4. 최대 용량(15MB) 초과 시 400 Bad Request
    with patch("app.api.vton.MAX_PHOTO_SIZE_BYTES", 100):
        resp_too_large = client.post(
            "/api/vton",
            data={"productIds": "[101]"},
            files={"userImage": ("large.png", img_bytes, "image/png")},
            headers={"X-User-Id": "7"},
        )
        assert resp_too_large.status_code == 400
        assert "15MB" in resp_too_large.json()["message"]

    # 5. 비정상 타입의 productIds (null, float 등) 시 400 Bad Request
    resp_invalid_type = client.post(
        "/api/vton",
        data={"productIds": "[null]"},
        files={"userImage": ("photo.png", img_bytes, "image/png")},
        headers={"X-User-Id": "7"},
    )
    assert resp_invalid_type.status_code == 400

    # 6. 상품 개수 초과(6개) 시 400 차단 및 사진 파일 미저장 확인 (고아 파일 누수 방지)
    test_photos = Path("data/photos")
    before_count = len(list(test_photos.glob("user_7_*.png"))) if test_photos.exists() else 0
    resp_exceed = client.post(
        "/api/vton",
        data={"productIds": "[1, 2, 3, 4, 5, 6]"},
        files={"userImage": ("should_not_save.png", img_bytes, "image/png")},
        headers={"X-User-Id": "7"},
    )
    assert resp_exceed.status_code == 400
    after_count = len(list(test_photos.glob("user_7_*.png"))) if test_photos.exists() else 0
    assert after_count == before_count


def test_post_vton_non_object_json_returns_400() -> None:
    client = TestClient(app)
    # 배열 형태의 JSON 본문 (객체가 아님) 전송 시 500이 아닌 400 반환
    resp_arr = client.post(
        "/api/vton",
        json=[101, 102],
        headers={"X-User-Id": "7"},
    )
    assert resp_arr.status_code == 400

    # null 또는 문자열 전송 시 400 반환
    resp_str = client.post(
        "/api/vton",
        json="just_a_string",
        headers={"X-User-Id": "7"},
    )
    assert resp_str.status_code == 400


def test_get_fitting_not_found() -> None:
    client = TestClient(app)
    resp = client.get("/api/vton/999999", headers={"X-User-Id": "7"})
    assert resp.status_code == 404
    assert "존재하지 않는" in resp.json()["message"]


def test_post_vton_with_photo_id_ownership_validation(tmp_path: Path) -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    test_photos = tmp_path / "photos"
    test_photos.mkdir(parents=True, exist_ok=True)
    sample_file = test_photos / "sample.png"
    sample_file.write_bytes(_create_sample_png())

    # 사용자 7의 사진 레코드 생성
    photo_record = repo.save_user_photo(user_id=7, file_path=str(sample_file))
    photo_id = photo_record["photoId"]

    # 1. 타인(사용자 99)이 해당 photoId로 피팅 요청 시 404 차단
    resp_other = client.post(
        "/api/vton",
        json={"photoId": photo_id, "productIds": [101]},
        headers={"X-User-Id": "99"},
    )
    assert resp_other.status_code == 404

    # 2. 존재하지 않는 photoId 요청 시 404 차단
    resp_none = client.post(
        "/api/vton",
        json={"photoId": 88888, "productIds": [101]},
        headers={"X-User-Id": "7"},
    )
    assert resp_none.status_code == 404

    # 3. 본인(사용자 7)의 정상 photoId 요청 시 202 Accepted
    with patch("app.api.vton._run_background_vton"):
        resp_ok = client.post(
            "/api/vton",
            json={"photoId": photo_id, "productIds": [101]},
            headers={"X-User-Id": "7"},
        )
        assert resp_ok.status_code == 202


def test_get_fitting_user_image_flow(tmp_path: Path) -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    test_photos = tmp_path / "photos"
    test_photos.mkdir(parents=True, exist_ok=True)
    sample_file = test_photos / "sample_face.png"
    sample_bytes = _create_sample_png()
    sample_file.write_bytes(sample_bytes)

    # 1. 사진 레코드 및 피팅 생성
    photo_record = repo.save_user_photo(user_id=7, file_path=str(sample_file))
    photo_id = photo_record["photoId"]
    fitting_id = repo.create_fitting(user_id=7, photo_id=photo_id, product_ids=[101])

    # 2. GET /api/vton/{fittingId} 상세 조회 시 userImageUrl이 올바른 경로인지 확인
    resp_detail = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
    assert resp_detail.status_code == 200
    detail_data = resp_detail.json()
    assert detail_data["userImageUrl"].endswith(f"/api/vton/{fitting_id}/user-image")

    # 3. 인증 헤더 누락 시 401 Unauthorized
    resp_no_auth = client.get(f"/api/vton/{fitting_id}/user-image")
    assert resp_no_auth.status_code == 401

    # 4. 타인(사용자 99) 조회 시 403 Forbidden (IDOR 방어)
    resp_other = client.get(f"/api/vton/{fitting_id}/user-image", headers={"X-User-Id": "99"})
    assert resp_other.status_code == 403

    # 5. 본인(사용자 7)의 GET /api/vton/{fittingId}/user-image로 실제 이미지 파일 스트리밍 확인 (200 OK)
    resp_img = client.get(f"/api/vton/{fitting_id}/user-image", headers={"X-User-Id": "7"})
    assert resp_img.status_code == 200
    assert resp_img.headers["content-type"] == "image/png"
    assert resp_img.content == sample_bytes

    # 6. 사진 없이 생성된 피팅(photoId=None)의 경우 404 Not Found
    fitting_no_photo = repo.create_fitting(user_id=7, photo_id=None, product_ids=[102])
    resp_no_img = client.get(f"/api/vton/{fitting_no_photo}/user-image", headers={"X-User-Id": "7"})
    assert resp_no_img.status_code == 404
    assert "등록한 이미지가 없습니다" in resp_no_img.json()["message"]

    # 7. 존재하지 않는 fittingId 요청 시 404 Not Found
    resp_none = client.get("/api/vton/999999/user-image", headers={"X-User-Id": "7"})
    assert resp_none.status_code == 404


def test_background_vton_uses_custom_user_photo_bytes(tmp_path: Path) -> None:
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    test_photos = tmp_path / "photos"
    test_photos.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        db_path=":memory:",
        storage_dir=str(test_storage),
        photos_dir=str(test_photos),
    )
    reset_settings_for_tests(settings)
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    user_photo_file = test_photos / "user_7_body.png"
    user_photo_bytes = _create_sample_png()
    user_photo_file.write_bytes(user_photo_bytes)
    photo_record = repo.save_user_photo(user_id=7, file_path=str(user_photo_file))
    photo_id = photo_record["photoId"]

    mock_prod_client.resolve_product_item.return_value = {
        "productId": 101,
        "productName": "상의",
        "price": 20000,
        "imageUrl": "https://cdn.example.com/top.png",
        "categoryName": "상의",
        "imageBytes": _create_sample_png(),
    }

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=photo_id, product_ids=[101])

    with patch("app.api.vton.generate_tryon_image", return_value=_create_sample_png()) as mock_generate:
        _run_background_vton(
            fitting_id=fitting_id,
            user_id=7,
            photo_id=photo_id,
            product_ids=[101],
            result_image_url="/api/vton/1/image",
        )

        assert mock_generate.called
        kwargs = mock_generate.call_args.kwargs
        # 남성 서비스 기본 마네킹(avatar.png) 유지, 사용자 사진은 얼굴 블렌딩(user_face_bytes)에 사용
        assert kwargs["user_face_bytes"] == user_photo_bytes
        # avatar_bytes=None으로 넘겨서 기본 avatar.png를 내부 로드하도록 함
        assert kwargs["avatar_bytes"] is None
        mock_notif_client.send_fitting_done.assert_called_once()


def test_background_vton_fallback_bottom_when_missing(tmp_path: Path) -> None:
    test_storage = tmp_path / "fittings"
    test_storage.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=":memory:",
        storage_dir=str(test_storage),
    )
    reset_settings_for_tests(settings)
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    # 오직 상의(101)만 요청한 경우
    mock_prod_client.resolve_product_item.return_value = {
        "productId": 101,
        "productName": "기본 상의",
        "price": 25000,
        "imageUrl": "https://cdn.example.com/top.png",
        "categoryName": "상의",
        "imageBytes": _create_sample_png(),
    }

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=None, product_ids=[101])

    with patch("app.api.vton.generate_tryon_image", return_value=_create_sample_png()) as mock_generate:
        _run_background_vton(
            fitting_id=fitting_id,
            user_id=7,
            photo_id=None,
            product_ids=[101],
            result_image_url="/api/vton/1/image",
        )

        assert mock_generate.called
        kwargs = mock_generate.call_args.kwargs
        categories = kwargs["categories"]
        # AI 생성에는 상의 1개 + 기본 하의 폴백 1개 = 총 2개 전달
        assert "상의" in categories
        assert "하의" in categories

        # DB에는 사용자가 실제 요청한 상의(101)만 저장되고, 폴백 하의(0번 가짜 상품)는 저장되지 않아야 함
        detail = repo.get_fitting_detail(fitting_id)
        assert detail is not None
        assert len(detail["products"]) == 1
        assert detail["products"][0]["productId"] == 101


def test_background_vton_fails_when_user_photo_file_missing() -> None:
    repo = VtonRepository(db_path=":memory:")
    mock_prod_client = MagicMock(spec=ProductServiceClient)
    mock_notif_client = MagicMock(spec=NotificationServiceClient)

    # 존재하지 않는 경로로 사진 메타데이터 저장
    photo_record = repo.save_user_photo(user_id=7, file_path="/non/existent/path/photo.png")
    photo_id = photo_record["photoId"]

    mock_prod_client.resolve_product_item.return_value = {
        "productId": 101,
        "productName": "상의",
        "price": 20000,
        "imageUrl": "https://cdn.example.com/top.png",
        "categoryName": "상의",
        "imageBytes": _create_sample_png(),
    }

    set_dependencies_for_tests(
        repo=repo,
        product_client=mock_prod_client,
        notification_client=mock_notif_client,
    )

    fitting_id = repo.create_fitting(user_id=7, photo_id=photo_id, product_ids=[101])

    with patch("app.api.vton.generate_tryon_image") as mock_generate:
        _run_background_vton(
            fitting_id=fitting_id,
            user_id=7,
            photo_id=photo_id,
            product_ids=[101],
            result_image_url="/api/vton/1/image",
        )

        # 사진 파일 로드 실패 시 마네킹으로 대체하지 않고 피팅 실패 처리되어야 함
        mock_generate.assert_not_called()
        detail = repo.get_fitting_detail(fitting_id)
        assert detail is not None
        assert detail["status"] == "FAILED"
        mock_notif_client.send_fitting_failed.assert_called_once()


def test_clothing_transfer_exceeds_max_images() -> None:
    client = TestClient(app)
    img_bytes = _create_sample_png()
    files = [
        ("clothing_images", (f"item_{i}.png", img_bytes, "image/png"))
        for i in range(6)
    ]
    resp = client.post(
        "/api/vton/clothing-transfer",
        data={"categories_json": '["상의"]'},
        files=files,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["status"] == 400
    assert body["code"] == "BAD_REQUEST"
    assert "최대 5개" in body["message"]


def test_post_vton_with_custom_items_and_image_urls() -> None:
    client = TestClient(app)
    custom_url = "https://image.msscdn.net/images/goods_img/green_sample.jpg"

    with patch("app.api.vton._run_background_vton") as mock_bg:
        resp = client.post(
            "/api/vton",
            json={
                "items": [
                    {"productId": 101, "imageUrl": custom_url},
                    {"productId": 201, "imageUrl": "https://image.msscdn.net/black.jpg"},
                ]
            },
            headers={"X-User-Id": "7"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "fittingId" in data
        assert data["status"] == "PENDING"

        mock_bg.assert_called_once()
        kwargs = mock_bg.call_args.kwargs
        assert kwargs["product_ids"] == [101, 201]
        assert kwargs["item_image_urls"] == {
            101: custom_url,
            201: "https://image.msscdn.net/black.jpg",
        }


def test_resolve_product_item_prefers_override_image_url() -> None:
    client = ProductServiceClient()
    override_url = "https://image.msscdn.net/images/goods_img/green.jpg"
    fake_png = _create_sample_png()

    with patch.object(client, "fetch_product_image_bytes", return_value=fake_png) as mock_fetch, \
         patch.object(client, "get_product", return_value={
             "productName": "무신사 스탠다드 후드티",
             "price": 45000,
             "thumbnailUrl": "https://default-thumbnail.jpg",
             "categoryL1Name": "상의",
         }):
        item = client.resolve_product_item(
            product_id=101,
            override_image_url=override_url,
        )

        assert item["productId"] == 101
        assert item["productName"] == "무신사 스탠다드 후드티"
        assert item["price"] == 45000
        assert item["imageUrl"] == override_url
        assert item["imageBytes"] == fake_png
        mock_fetch.assert_called_once_with(override_url)


def test_resolve_product_item_prefers_normal_price() -> None:
    client = ProductServiceClient()
    fake_png = _create_sample_png()

    # normalPrice가 있을 때 우선 반영되는지 검증
    with patch.object(client, "fetch_product_image_bytes", return_value=fake_png), \
         patch.object(client, "get_product", return_value={
             "productName": "와이드 슬랙스",
             "price": 26100,        # 세일가
             "normalPrice": 29000,  # 정가 (우선순위)
             "thumbnailUrl": "https://default-thumbnail.jpg",
             "categoryL1Name": "하의",
         }):
        item = client.resolve_product_item(product_id=202)
        assert item["productId"] == 202
        assert item["price"] == 29000  # normalPrice 반영 확인
        assert item["categoryName"] == "하의"

    # normalPrice가 없거나 0일 때 세일가(price)로 폴백되는지 검증
    with patch.object(client, "fetch_product_image_bytes", return_value=fake_png), \
         patch.object(client, "get_product", return_value={
             "productName": "와이드 슬랙스",
             "price": 26100,
             "normalPrice": None,
             "thumbnailUrl": "https://default-thumbnail.jpg",
             "categoryL1Name": "하의",
         }):
        item = client.resolve_product_item(product_id=202)
        assert item["price"] == 26100  # price 폴백 확인



def test_post_vton_with_request_id_json_and_get_detail() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    with patch("app.api.vton._run_background_vton"):
        resp = client.post(
            "/api/vton",
            json={
                "items": [{"productId": 101}],
                "requestId": 6,
            },
            headers={"X-User-Id": "7"},
        )
        assert resp.status_code == 202
        fitting_id = resp.json()["fittingId"]

        # 상세 조회 검증
        detail_resp = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["fittingId"] == fitting_id
        assert detail_data["requestId"] == 6

        # 목록 조회 검증
        list_resp = client.get("/api/vton", headers={"X-User-Id": "7"})
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert len(list_data["items"]) >= 1
        assert list_data["items"][0]["requestId"] == 6


def test_post_vton_with_request_id_multipart_and_get_detail() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    fake_png = _create_sample_png()
    files = {"userImage": ("face.png", fake_png, "image/png")}
    data = {
        "items": json.dumps([{"productId": 101}]),
        "requestId": "15",
    }

    with patch("app.api.vton._run_background_vton"):
        resp = client.post(
            "/api/vton",
            data=data,
            files=files,
            headers={"X-User-Id": "7"},
        )
        assert resp.status_code == 202
        fitting_id = resp.json()["fittingId"]

        detail_resp = client.get(f"/api/vton/{fitting_id}", headers={"X-User-Id": "7"})
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["fittingId"] == fitting_id
        assert detail_data["requestId"] == 15


def test_post_vton_with_invalid_multipart_request_id_returns_400() -> None:
    client = TestClient(app)
    repo = VtonRepository(db_path=":memory:")
    set_dependencies_for_tests(repo=repo)

    fake_png = _create_sample_png()
    files = {"userImage": ("face.png", fake_png, "image/png")}
    data = {
        "items": json.dumps([{"productId": 101}]),
        "requestId": "invalid_number",
    }

    resp = client.post(
        "/api/vton",
        data=data,
        files=files,
        headers={"X-User-Id": "7"},
    )
    assert resp.status_code == 400
    assert "requestId" in resp.json()["message"]





