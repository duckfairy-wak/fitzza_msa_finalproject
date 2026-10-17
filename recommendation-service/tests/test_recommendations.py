from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.clients.product_client import normalize_measurement_spec
from app.core.config import Settings
from app.core.database import RecommendationRepository
from app.main import app

COMMUNITY_TOKEN = "test-only-community-service-token-32b"
PRODUCT_TOKEN = "test-only-product-service-token-32b!"
REVIEW_TOKEN = "test-only-review-service-token-32-b!"
RECOMMENDATION_TOKEN = "test-only-recommendation-token-32-b!"


class StubSizeResolver:
    def __init__(self) -> None:
        self.registered_bodies: list[dict[str, Any]] = []

    def register_user_body(
        self,
        user_id: str,
        height: float | None = None,
        weight: float | None = None,
    ) -> None:
        self.registered_bodies.append(
            {"user_id": user_id, "height": height, "weight": weight}
        )


class StubCoordinator:
    def __init__(self, mode: str = "coordination") -> None:
        self.mode = mode
        self.size_resolver = StubSizeResolver()
        self.calls: list[tuple[str, str]] = []

    def run(self, user_query: str, user_id: str = "user_001") -> dict[str, Any]:
        self.calls.append((user_query, user_id))
        if self.mode == "error":
            raise RuntimeError("Simulated LLM failure")

        if self.mode == "single":
            return {
                "type": "single",
                "query": user_query,
                "tpo": "주말 캐주얼 단품",
                "excluded_categories": [],
                "comment": "요청하신 블랙 가디건 단품 추천입니다.",
                "results": [
                    {
                        "product_id": 101,
                        "product_name": "릴렉스드 가디건",
                        "brand_name": "무신사 스탠다드",
                        "category": "outer",
                        "subcategory": "가디건",
                        "price": 49900,
                        "image_url": "https://cdn.example.com/101.jpg",
                        "color_raw": "블랙",
                        "color_normalized": ["black"],
                        "size_recommendation": {
                            "size_label": "L",
                            "predicted_fit_score": 0.92,
                        },
                        "fit_source_type": "learned_preference",
                    }
                ],
            }

        return {
            "type": "coordination",
            "query": user_query,
            "tpo": "성수동 주말 나들이 미니멀",
            "excluded_categories": [],
            "comment": "성수동 나들이에 어울리는 세미 미니멀 코디 2가지입니다.",
            "outfits": [
                {
                    "harmony_score": 92,
                    "final_score": 92.0,
                    "budget_penalty": 0.0,
                    "pass_status": True,
                    "violated_rules": [],
                    "verdict": "블랙과 크림의 안정적인 배색으로 깔끔한 무드를 연출합니다.",
                    "styling_tip": "블랙과 크림의 안정적인 배색으로 깔끔한 무드를 연출합니다.",
                    "total_price": 88900,
                    "items": [
                        {
                            "product_id": 201,
                            "product_name": "옥스포드 셔츠",
                            "brand_name": "비슬로우",
                            "category": "top",
                            "subcategory": "셔츠/블라우스",
                            "price": 39000,
                            "image_url": "https://cdn.example.com/201.jpg",
                            "color_raw": "크림",
                            "size_recommendation": {
                                "size_label": "L",
                                "predicted_fit_score": 0.95,
                            },
                            "fit_source_type": "similar_body_profile",
                        },
                        {
                            "product_id": 202,
                            "product_name": "와이드 히든 슬랙스",
                            "brand_name": "무신사 스탠다드",
                            "category": "bottom",
                            "subcategory": "슈트 팬츠/슬랙스",
                            "price": 49900,
                            "image_url": "https://cdn.example.com/202.jpg",
                            "color_raw": "블랙",
                            "size_recommendation": {
                                "size_label": "32",
                                "predicted_fit_score": 0.88,
                            },
                            "fit_source_type": "recent_purchase",
                        },
                    ],
                }
            ],
        }


class StubUserClient:
    def get_user_body(
        self,
        user_id: int,
        request_id_header: str | None = None,
    ) -> dict[str, Any]:
        return {"height": 175.0, "weight": 68.0, "preferredFit": "OVERFIT"}


class StubProductClient:
    def find_option_measurement(
        self,
        product_id: int,
        option_id: int,
        request_id_header: str | None = None,
    ) -> dict[str, float] | None:
        return {"총장": 71.0, "어깨너비": 51.0, "가슴단면": 59.0}


class StubNotificationClient:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def send_recommendation_done(
        self,
        user_id: int,
        request_id: int,
        content: str = "",
        request_id_header: str | None = None,
    ) -> bool:
        self.events.append(
            {
                "eventId": f"recommendation-{request_id}-done",
                "type": "RECOMMENDATION_DONE",
                "userId": user_id,
                "targetId": str(request_id),
                "content": content,
                "requestIdHeader": request_id_header,
            }
        )
        return True


@pytest.fixture(autouse=True)
def configure_test_state() -> None:
    app.state.settings = Settings(
        db_path=":memory:",
        recommendation_service_token=RECOMMENDATION_TOKEN,
        community_service_token=COMMUNITY_TOKEN,
        product_service_token=PRODUCT_TOKEN,
        review_service_token=REVIEW_TOKEN,
    )
    app.state.repository = RecommendationRepository(db_path=":memory:")
    app.state.coordinator = StubCoordinator(mode="coordination")
    app.state.user_client = StubUserClient()
    app.state.product_client = StubProductClient()
    app.state.notification_client = StubNotificationClient()


def test_post_recommendations_returns_accepted_and_triggers_fcm_notification() -> None:
    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7", "X-Request-Id": "req-trace-1"},
            json={"query": "성수동 주말 나들이 코디 추천해줘"},
        )

        assert post_res.status_code == 202
        body = post_res.json()
        assert body["status"] == "PROCESSING"
        request_id = body["requestId"]
        assert isinstance(request_id, int)

        events = app.state.notification_client.events
        assert len(events) == 1
        assert events[0]["type"] == "RECOMMENDATION_DONE"
        assert events[0]["userId"] == 7
        assert events[0]["targetId"] == str(request_id)
        assert events[0]["requestIdHeader"] == "req-trace-1"

        detail_res = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "7"},
        )
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["requestId"] == request_id
        assert detail["status"] == "DONE"
        assert detail["searchType"] == "COMBO"
        assert detail["tpoSummary"] == "성수동 주말 나들이 미니멀"
        assert len(detail["combos"]) == 1
        combo = detail["combos"][0]
        assert combo["comboId"] >= 1
        assert combo["totalPrice"] == 88900
        assert combo["passStatus"] == "PASS"
        assert combo["harmonyScore"] == 92.0
        assert len(combo["items"]) == 2
        assert combo["items"][0]["productId"] == 201
        assert combo["items"][0]["size"] == "L"
        assert combo["items"][0]["fitPercent"] == 95.0


def test_single_item_recommendation_saves_items_and_notifies_fcm() -> None:
    app.state.coordinator = StubCoordinator(mode="single")

    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "12"},
            json={"query": "검정 가디건 단품 추천해줘"},
        )
        assert post_res.status_code == 202
        request_id = post_res.json()["requestId"]

        detail_res = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "12"},
        )
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["status"] == "DONE"
        assert detail["searchType"] == "SINGLE"
        assert len(detail["items"]) == 1
        assert detail["items"][0]["productId"] == 101
        assert detail["items"][0]["color"] == "블랙"
        assert detail["items"][0]["size"] == "L"
        assert detail["items"][0]["fitPercent"] == 92.0
        assert detail["combos"] == []


def test_failed_recommendation_marks_status_failed_and_still_sends_fcm_done() -> None:
    app.state.coordinator = StubCoordinator(mode="error")

    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json={"query": "오류 테스트"},
        )
        assert post_res.status_code == 202
        request_id = post_res.json()["requestId"]

        assert len(app.state.notification_client.events) == 1
        assert app.state.notification_client.events[0]["type"] == "RECOMMENDATION_DONE"

        detail_res = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "7"},
        )
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["status"] == "FAILED"
        assert detail["message"] is not None


@pytest.mark.parametrize("invalid_user_id", [None, "", " ", "abc", "0", "-5"])
def test_public_endpoints_require_authenticated_user_header(
    invalid_user_id: str | None,
) -> None:
    headers = {} if invalid_user_id is None else {"X-User-Id": invalid_user_id}
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/recommendations",
            headers=headers,
            json={"query": "코디 추천"},
        )
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize("payload", [{}, {"query": ""}, {"query": "   "}])
def test_post_recommendations_rejects_blank_or_missing_query(payload: dict) -> None:
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json=payload,
        )
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_get_recommendation_detail_enforces_ownership_and_existence() -> None:
    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json={"query": "코디 추천"},
        )
        request_id = post_res.json()["requestId"]

        other_user_res = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "99"},
        )
        assert other_user_res.status_code == 403
        assert other_user_res.json()["code"] == "NOT_OWNER"

        missing_res = client.get(
            "/api/v1/recommendations/99999",
            headers={"X-User-Id": "7"},
        )
        assert missing_res.status_code == 404
        assert missing_res.json()["code"] == "RECOMMENDATION_NOT_FOUND"


def test_list_recommendations_returns_user_history_newest_first() -> None:
    with TestClient(app) as client:
        client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json={"query": "첫 번째 질문"},
        )
        client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json={"query": "두 번째 질문"},
        )
        client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "8"},
            json={"query": "다른 사용자 질문"},
        )

        list_res = client.get(
            "/api/v1/recommendations?page=0&size=10",
            headers={"X-User-Id": "7"},
        )
        assert list_res.status_code == 200
        data = list_res.json()
        assert data["page"] == 0
        assert data["totalPages"] == 1
        assert [item["queryText"] for item in data["content"]] == [
            "두 번째 질문",
            "첫 번째 질문",
        ]


def test_internal_combo_lookup_verifies_service_token_and_ownership() -> None:
    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "7"},
            json={"query": "성수동 코디"},
        )
        request_id = post_res.json()["requestId"]
        detail = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "7"},
        ).json()
        combo_id = detail["combos"][0]["comboId"]

        unauth_res = client.get(
            f"/recommendations/combos/{combo_id}?userId=7",
            headers={"X-Service-Token": REVIEW_TOKEN},
        )
        assert unauth_res.status_code == 401
        assert unauth_res.json()["code"] == "UNAUTHENTICATED"

        owner_res = client.get(
            f"/recommendations/combos/{combo_id}?userId=7",
            headers={"X-Service-Token": COMMUNITY_TOKEN},
        )
        assert owner_res.status_code == 200
        owner_body = owner_res.json()
        assert owner_body["owned"] is True
        assert owner_body["totalPrice"] == 88900
        assert len(owner_body["items"]) == 2
        assert owner_body["items"][0]["productId"] == 201

        other_res = client.get(
            f"/recommendations/combos/{combo_id}?userId=99",
            headers={"X-Service-Token": PRODUCT_TOKEN},
        )
        assert other_res.status_code == 200
        assert other_res.json() == {
            "owned": False,
            "items": [],
            "totalPrice": None,
            "feedbackSummary": None,
        }

        missing_res = client.get(
            "/recommendations/combos/99999?userId=7",
            headers={"X-Service-Token": COMMUNITY_TOKEN},
        )
        assert missing_res.status_code == 404
        assert missing_res.json()["code"] == "COMBO_NOT_FOUND"


def test_internal_size_feedback_accepts_review_service_token() -> None:
    with TestClient(app) as client:
        forbidden_res = client.post(
            "/recommendations/size-feedback",
            headers={"X-Service-Token": COMMUNITY_TOKEN},
            json={
                "userId": 7,
                "productId": 201,
                "optionId": 501,
                "sizeFeedback": "FIT",
            },
        )
        assert forbidden_res.status_code == 401

        ok_res = client.post(
            "/recommendations/size-feedback",
            headers={"X-Service-Token": REVIEW_TOKEN},
            json={
                "userId": 7,
                "productId": 201,
                "optionId": 501,
                "sizeFeedback": "SMALL",
            },
        )
        assert ok_res.status_code == 202


def test_normalize_measurement_spec_keeps_korean_keys() -> None:
    spec = normalize_measurement_spec(
        {"총장": 72, "어깨너비": 52.5, "가슴단면": 60, "소매길이": 63}
    )
    assert spec == {
        "총장": 72.0,
        "어깨너비": 52.5,
        "가슴단면": 60.0,
        "소매길이": 63.0,
    }


def test_settings_builds_postgres_dsn_from_env_fields() -> None:
    settings = Settings(
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="fitzza",
        postgres_user="fitzza",
        postgres_password="fitzza_local",
        postgres_schema="recommendation",
    )
    assert (
        settings.get_postgres_dsn()
        == "postgresql://fitzza:fitzza_local@postgres:5432/fitzza"
    )
    assert settings.postgres_schema == "recommendation"
