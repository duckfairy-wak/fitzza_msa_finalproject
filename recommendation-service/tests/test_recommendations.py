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

        if self.mode == "empty_coordination":
            return {
                "type": "coordination",
                "query": user_query,
                "tpo": "데이트룩 코디",
                "intent": None,
                "excluded_categories": ["top", "shoes"],
                "comment": "요청하신 조건에 맞는 추천 조합을 찾지 못했습니다. 검색 조건을 조금 완화해 다시 시도해주세요.",
                "outfits": [],
            }

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
        redis_enabled=False,
    )
    app.state.repository = RecommendationRepository(db_path=":memory:")
    app.state.coordinator = StubCoordinator(mode="coordination")
    app.state.user_client = StubUserClient()
    app.state.product_client = StubProductClient()
    app.state.notification_client = StubNotificationClient()
    app.state.redis_client = None
    app.state.cache_service = None
    app.state.size_resolver = None
    app.state.qdrant_client = None



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
        assert detail["queryText"] == "성수동 주말 나들이 코디 추천해줘"
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
        assert combo["items"][0]["recommendedSize"] == "L"
        assert combo["items"][0]["availableSizes"] is None
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
        assert detail["requestId"] == request_id
        assert detail["queryText"] == "검정 가디건 단품 추천해줘"
        assert detail["status"] == "DONE"
        assert detail["searchType"] == "SINGLE"
        assert len(detail["items"]) == 1
        assert detail["items"][0]["productId"] == 101
        assert detail["items"][0]["color"] == "블랙"
        assert detail["items"][0]["recommendedSize"] == "L"
        assert detail["items"][0]["availableSizes"] is None
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
        assert data["size"] == 10
        assert data["totalElements"] == 2
        assert data["totalPages"] == 1
        assert data["hasNext"] is False
        assert [item["queryText"] for item in data["content"]] == [
            "두 번째 질문",
            "첫 번째 질문",
        ]

        # 페이징 size=1 -> hasNext is True 확인
        paged_res = client.get(
            "/api/v1/recommendations?page=0&size=1",
            headers={"X-User-Id": "7"},
        )
        assert paged_res.status_code == 200
        paged_data = paged_res.json()
        assert paged_data["page"] == 0
        assert paged_data["size"] == 1
        assert paged_data["totalElements"] == 2
        assert paged_data["totalPages"] == 2
        assert paged_data["hasNext"] is True
        assert len(paged_data["content"]) == 1


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


def test_verify_service_token_allows_shared_token_across_callers() -> None:
    shared_token = "shared-service-token-at-least-32-bytes-long"
    settings = Settings(
        community_service_token=shared_token,
        product_service_token=shared_token,
        review_service_token=shared_token,
    )
    assert settings.verify_service_token(shared_token, ("community",)) is True
    assert settings.verify_service_token(shared_token, ("product",)) is True
    assert settings.verify_service_token(shared_token, ("review",)) is True


def test_find_option_measurement_normalizes_int_and_returns_none_on_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.clients.product_client import ProductServiceClient

    client = ProductServiceClient(Settings())
    monkeypatch.setattr(
        client,
        "get_product_measurements",
        lambda product_ids, request_id_header=None: {
            101: [
                {
                    "option_id": "5001",
                    "color": "블랙",
                    "size": "L",
                    "measurements": {"총장": 71.0, "어깨너비": 51.0},
                }
            ]
        },
    )

    assert client.find_option_measurement(101, 5001) == {"총장": 71.0, "어깨너비": 51.0}
    assert client.find_option_measurement(101, 9999) is None


def test_empty_coordination_recommendation_saves_empty_combos() -> None:
    app.state.coordinator = StubCoordinator(mode="empty_coordination")

    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "15"},
            json={"query": "상의 하의 신발 풀세트 코디 추천해줘"},
        )
        assert post_res.status_code == 202
        request_id = post_res.json()["requestId"]

        detail_res = client.get(
            f"/api/v1/recommendations/{request_id}",
            headers={"X-User-Id": "15"},
        )
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["status"] == "DONE"
        assert detail["searchType"] == "COMBO"
        assert detail["combos"] == []
        assert "조건에 맞는 추천 조합을 찾지 못했습니다" in detail["message"]


def test_coordinator_empty_coordination_fallback_logic(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock
    from app.services.coordinator import FashionPipelineCoordinator
    from app.services.query_parser import ParsedIntent, SlotQuery

    coordinator = FashionPipelineCoordinator.__new__(FashionPipelineCoordinator)
    coordinator.parser = MagicMock()
    coordinator.engine = MagicMock()
    coordinator.harmonizer = MagicMock()
    coordinator.responder = MagicMock()
    coordinator.size_resolver = MagicMock()

    # 1. 3개 슬롯(top, bottom, shoes) 요청 중 top 1개만 검색되고 나머지 2개는 0개인 경우 (살아남은 슬롯 1개 이하)
    intent = ParsedIntent(
        search_type="coordination",
        season_preferences=["봄"],
        tpo_summary="캐주얼 코디",
        slots=[
            SlotQuery(category="top", clip_query_en="shirt", slot_budget=40000),
            SlotQuery(category="bottom", clip_query_en="slacks", slot_budget=40000),
            SlotQuery(category="shoes", clip_query_en="sneakers", slot_budget=40000),
        ],
    )
    coordinator.parser.parse.return_value = intent

    def search_side_effect(slot, season_preferences=None, top_k=5):
        if slot.category == "top":
            return [{"product_id": 101, "product_name": "상의"}]
        return []

    coordinator._search_slot_items = MagicMock(side_effect=search_side_effect)
    coordinator._attach_size_info = MagicMock(side_effect=lambda items, slot, user_id: items)

    result = coordinator.run("상의 하의 신발 코디해줘", user_id="1")
    assert result["type"] == "coordination"
    assert result["outfits"] == []
    assert set(result["excluded_categories"]) == {"bottom", "shoes"}
    assert "조건에 맞는 추천 조합을 찾지 못했습니다" in result["comment"]
    # harmonizer나 responder가 불필요하게 호출되지 않아야 함
    coordinator.harmonizer.select_best_outfits.assert_not_called()
    coordinator.responder.generate_coordination_response.assert_not_called()
    coordinator.responder.generate_single_response.assert_not_called()


def test_extract_sizes_list_logic() -> None:
    from app.api.recommendations import _extract_sizes_list

    # 1. Qdrant payload 구조 (sequence 순서대로 리스트 추출)
    qdrant_sizes = [
        {"size": "small", "sequence": 0, "measurements": {"top_length": 70}},
        {"size": "medium", "sequence": 1, "measurements": {"top_length": 75}},
        {"size": "large", "sequence": 2, "measurements": {"top_length": 78}},
    ]
    assert _extract_sizes_list({"sizes": qdrant_sizes}) == ["small", "medium", "large"]

    # 2. 원사이즈 (FREE)
    free_sizes = [{"size": "FREE", "sequence": 0}]
    assert _extract_sizes_list({"sizes": free_sizes}) == ["FREE"]

    # 3. 신발 사이즈 목록
    shoes_sizes = [{"size": "260"}, {"size": "265"}, {"size": "270"}]
    assert _extract_sizes_list({"sizes": shoes_sizes}) == ["260", "265", "270"]

    # 4. 문자열 리스트로 들어온 경우도 정상 지원
    assert _extract_sizes_list({"sizes": ["S", "M", "L"]}) == ["S", "M", "L"]

    # 5. 빈 리스트이거나 None이거나 없는 경우 -> None 반환
    assert _extract_sizes_list({"sizes": []}) is None
    assert _extract_sizes_list({"sizes": None}) is None
    assert _extract_sizes_list({}) is None
    assert _extract_sizes_list({"sizes": [{"size": "  "}, {"size": None}]}) is None


def test_map_product_item_includes_sizes() -> None:
    from app.api.recommendations import _map_product_item

    # availableSizes가 있는 경우
    item_with_sizes = {
        "product_id": 101,
        "product_name": "테스트 셔츠",
        "price": 30000,
        "size_recommendation": {"size_label": "medium"},
        "sizes": [
            {"size": "small", "sequence": 0},
            {"size": "medium", "sequence": 1},
            {"size": "large", "sequence": 2},
        ],
    }
    mapped = _map_product_item(item_with_sizes)
    assert mapped["recommendedSize"] == "medium"
    assert mapped["availableSizes"] == ["small", "medium", "large"]

    # sizes가 없는 경우
    item_without_sizes = {
        "product_id": 102,
        "product_name": "사이즈 없는 모자",
        "price": 20000,
    }
    mapped_none = _map_product_item(item_without_sizes)
    assert mapped_none["recommendedSize"] is None
    assert mapped_none["availableSizes"] is None


def test_recommendation_detail_with_null_query_text_falls_back_to_empty_string() -> None:
    from unittest.mock import patch

    with TestClient(app) as client:
        post_res = client.post(
            "/api/v1/recommendations",
            headers={"X-User-Id": "15"},
            json={"query": "테스트 코디"},
        )
        assert post_res.status_code == 202
        request_id = post_res.json()["requestId"]

        repo = app.state.repository
        original_get_request = repo.get_request

        def mock_get_request(req_id: int):
            data = original_get_request(req_id)
            if data and req_id == request_id:
                data["queryText"] = None
            return data

        with patch.object(repo, "get_request", side_effect=mock_get_request):
            detail_res = client.get(
                f"/api/v1/recommendations/{request_id}",
                headers={"X-User-Id": "15"},
            )
            assert detail_res.status_code == 200
            assert detail_res.json()["queryText"] == ""


def test_recommendation_request_stores_token_metrics() -> None:
    repo = RecommendationRepository(db_path=":memory:")
    req_id = repo.create_request(user_id=1, query_text="가을 미니멀 룩 추천해줘")

    # 1. 단품 완료 시 토큰 저장 확인
    repo.complete_single_request(
        request_id=req_id,
        tpo_summary="가을 미니멀 단품",
        items=[{"product_id": 101, "product_name": "니트", "price": 45000}],
        message="가을 니트 추천합니다.",
        prompt_tokens=450,
        completion_tokens=220,
    )
    data = repo.get_request(req_id)
    assert data is not None
    assert data["promptTokens"] == 450
    assert data["completionTokens"] == 220

    # 2. 코디 완료 시 토큰 저장 확인
    req_id_combo = repo.create_request(user_id=1, query_text="가을 코디 추천해줘")
    repo.complete_combo_request(
        request_id=req_id_combo,
        user_id=1,
        tpo_summary="가을 미니멀 코디",
        combos=[{"items": [{"product_id": 101, "price": 45000}], "totalPrice": 45000}],
        message="코디 추천입니다.",
        prompt_tokens=850,
        completion_tokens=430,
    )
    combo_data = repo.get_request(req_id_combo)
    assert combo_data is not None
    assert combo_data["promptTokens"] == 850
    assert combo_data["completionTokens"] == 430


def test_process_recommendation_request_zeros_tokens_on_cache_hit() -> None:
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    from app.api.recommendations import process_recommendation_request

    mock_app = SimpleNamespace()
    mock_app.state = SimpleNamespace()
    mock_repo = RecommendationRepository(db_path=":memory:")
    mock_app.state.repository = mock_repo
    mock_app.state.settings = Settings(db_path=":memory:")

    mock_user_client = MagicMock()
    mock_user_client.get_user_body.return_value = None
    mock_app.state.user_client = mock_user_client

    mock_notif_client = MagicMock()
    mock_app.state.notification_client = mock_notif_client

    # CacheService가 토큰이 포함된 캐시 결과를 반환하도록 설정
    mock_cache = MagicMock()
    cached_payload = {
        "type": "single",
        "tpo": "출근룩",
        "comment": "캐시된 결과",
        "results": [{"product_id": 101, "product_name": "셔츠", "price": 30000}],
        "prompt_tokens": 1200,
        "completion_tokens": 600,
    }
    mock_cache.get_pipeline_result.return_value = cached_payload
    mock_app.state.cache_service = mock_cache

    req_id = mock_repo.create_request(user_id=1, query_text="캐시 테스트 질의")
    process_recommendation_request(
        app=mock_app,
        request_id=req_id,
        user_id=1,
        query_text="캐시 테스트 질의",
    )

    saved = mock_repo.get_request(req_id)
    assert saved is not None
    assert saved["promptTokens"] == 0
    assert saved["completionTokens"] == 0


def test_get_product_size_recommendation_from_qdrant_and_body_profile() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.services.size_resolver import SizeProfileResolver

    resolver = SizeProfileResolver()
    resolver.mock_db.setdefault("other_users_fits", []).append(
        {
            "subcategory": "반소매 티셔츠",
            "height": 175.0,
            "weight": 68.0,
            "measurement_spec": {"총장": 70.0, "어깨너비": 50.0, "가슴단면": 58.0, "소매길이": 62.0},
        }
    )
    app.state.size_resolver = resolver

    mock_qdrant = MagicMock()
    mock_point = SimpleNamespace(
        payload={
            "product_id": 1024,
            "product_name": "릴렉스드 핏 크루 넥 반소매 티셔츠",
            "category": "상의",
            "subcategory": "반소매 티셔츠",
            "features": {"핏": ["레귤러"]},
            "sizes": [
                {
                    "size": "S",
                    "measurements": {"총장": 66.0, "어깨너비": 46.0, "가슴단면": 53.0, "소매길이": 59.0},
                },
                {
                    "size": "M",
                    "measurements": {"총장": 68.0, "어깨너비": 48.0, "가슴단면": 55.5, "소매길이": 60.5},
                },
                {
                    "size": "L",
                    "measurements": {"총장": 70.0, "어깨너비": 50.0, "가슴단면": 58.0, "소매길이": 62.0},
                },
                {
                    "size": "XL",
                    "measurements": {"총장": 72.0, "어깨너비": 52.0, "가슴단면": 60.5, "소매길이": 63.5},
                },
            ],
        }
    )
    mock_qdrant.scroll.return_value = ([mock_point], None)
    app.state.qdrant_client = mock_qdrant

    with TestClient(app) as client:
        res = client.get(
            "/api/recommendations/1024/size",
            headers={"X-User-Id": "7"},
        )
        assert res.status_code == 200
        data = res.json()
        assert set(data.keys()) == {"recommendedSize", "fitPercent", "evidence"}
        assert data["recommendedSize"] == "L"
        assert data["evidence"] == "유사 체형 사용자의 실측 데이터를 기준으로 추천된 사이즈입니다."
        assert data["fitPercent"] == 100.0


def test_get_product_size_recommendation_uses_learned_preference_after_size_feedback() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    mock_qdrant = MagicMock()
    mock_point = SimpleNamespace(
        payload={
            "product_id": 2048,
            "product_name": "옥스포드 오버핏 셔츠",
            "category": "상의",
            "subcategory": "셔츠/블라우스",
            "features": {"핏": ["오버 사이즈"]},
            "sizes": [
                {
                    "size": "M",
                    "measurements": {"총장": 71.0, "어깨너비": 51.0, "가슴단면": 59.0, "소매길이": 61.0},
                },
                {
                    "size": "L",
                    "measurements": {"총장": 74.0, "어깨너비": 53.0, "가슴단면": 62.0, "소매길이": 63.0},
                },
            ],
        }
    )
    mock_qdrant.scroll.return_value = ([mock_point], None)
    app.state.qdrant_client = mock_qdrant

    with TestClient(app) as client:
        # 1. review-service가 설문 결과(FIT)를 전송 (StubProductClient는 71/51/59 M사이즈 실측 반환)
        fb_res = client.post(
            "/recommendations/size-feedback",
            headers={"X-Service-Token": REVIEW_TOKEN},
            json={
                "userId": 77,
                "productId": 2048,
                "optionId": 501,
                "sizeFeedback": "FIT",
            },
        )
        assert fb_res.status_code == 202

        # 2. 이후 동일 서브카테고리 상품 상세페이지 사이즈 추천 조회 시 1순위 learned_preference로 M 추천
        size_res = client.get(
            "/api/recommendations/2048/size",
            headers={"X-User-Id": "77"},
        )
        assert size_res.status_code == 200
        body = size_res.json()
        assert set(body.keys()) == {"recommendedSize", "fitPercent", "evidence"}
        assert body["recommendedSize"] == "M"
        assert body["evidence"] == "기존 구매·설문 기반 선호 실측과 가장 유사한 사이즈입니다."
        assert body["fitPercent"] == 100.0


def test_get_product_size_recommendation_edge_cases() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    class EmptyUserClient:
        def get_user_body(self, user_id: int, request_id_header: str | None = None) -> dict[str, Any]:
            return {}

    class EmptyProductClient:
        def get_product_measurements(self, product_ids: list[int], request_id_header: str | None = None) -> dict[int, list[dict[str, Any]]]:
            return {}

    app.state.user_client = EmptyUserClient()
    app.state.product_client = EmptyProductClient()

    with TestClient(app) as client:
        # 1. 존재하지 않는 상품 -> 404 PRODUCT_NOT_FOUND
        not_found_res = client.get(
            "/api/recommendations/99999/size",
            headers={"X-User-Id": "999"},
        )
        assert not_found_res.status_code == 404
        assert not_found_res.json()["code"] == "PRODUCT_NOT_FOUND"

        # 2. 단일 사이즈(FREE) 상품 -> 200 OK & recommendedSize=None
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = (
            [
                SimpleNamespace(
                    payload={
                        "product_id": 3001,
                        "product_name": "프리사이즈 볼캡",
                        "category": "모자",
                        "subcategory": "캡/야구모자",
                        "sizes": [{"size": "FREE", "measurements": {"머리둘레": 58.0}}],
                    }
                )
            ],
            None,
        )
        app.state.qdrant_client = mock_qdrant

        free_res = client.get(
            "/api/recommendations/3001/size",
            headers={"X-User-Id": "999"},
        )
        assert free_res.status_code == 200
        free_body = free_res.json()
        assert free_body == {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "단일 사이즈(FREE)로 제공되는 상품입니다.",
        }

        # 3. 신체 정보 및 이력이 전혀 없는 유저 -> 200 OK & recommendedSize=None
        mock_qdrant.scroll.return_value = (
            [
                SimpleNamespace(
                    payload={
                        "product_id": 3002,
                        "product_name": "데님 팬츠",
                        "category": "하의",
                        "subcategory": "데님 팬츠",
                        "sizes": [
                            {"size": "S", "measurements": {"총장": 100.0, "허리단면": 38.0}},
                            {"size": "M", "measurements": {"총장": 102.0, "허리단면": 40.0}},
                        ],
                    }
                )
            ],
            None,
        )
        no_profile_res = client.get(
            "/api/recommendations/3002/size",
            headers={"X-User-Id": "999"},
        )
        assert no_profile_res.status_code == 200
        no_profile_body = no_profile_res.json()
        assert no_profile_body == {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "체형 정보를 등록하시면 맞춤 사이즈를 추천해 드립니다.",
        }

        # 4. 유효하지 않은 productId (0 이하) -> 400 INVALID_REQUEST
        invalid_id_res = client.get(
            "/api/recommendations/0/size",
            headers={"X-User-Id": "999"},
        )
        assert invalid_id_res.status_code == 400
        assert invalid_id_res.json()["code"] == "INVALID_REQUEST"


def test_coordinator_attach_size_info_uses_learned_preference_from_repository() -> None:
    from unittest.mock import MagicMock
    from app.services.coordinator import FashionPipelineCoordinator
    from app.services.query_parser import SlotQuery

    mock_repo = MagicMock()
    mock_repo.get_user_size_preference.return_value = {
        "총장": 73.0,
        "어깨너비": 52.0,
        "가슴단면": 60.0,
    }

    coordinator = FashionPipelineCoordinator.__new__(FashionPipelineCoordinator)
    coordinator.repository = mock_repo
    coordinator.size_resolver = MagicMock()
    coordinator.size_resolver.resolve_and_calculate_size.return_value = {
        "source_type": "learned_preference",
        "recommendation": {"size": "L"},
    }

    items = [{"product_id": 999, "name": "오버핏 셔츠"}]
    slot = SlotQuery(
        category="top",
        subcategory="셔츠/블라우스",
        clip_query_en="oversized shirt",
        fit_type="오버 사이즈",
    )

    result = coordinator._attach_size_info(items=items, slot=slot, user_id="user_77")

    mock_repo.get_user_size_preference.assert_called_once_with(
        user_id="user_77",
        subcategory="셔츠/블라우스",
    )
    coordinator.size_resolver.resolve_and_calculate_size.assert_called_once_with(
        user_id="user_77",
        subcategory="셔츠/블라우스",
        fit_type="오버 사이즈",
        candidate_products=[{"product_id": 999, "name": "오버핏 셔츠", "size_recommendation": {"size": "L"}, "fit_source_type": "learned_preference"}],
        category_type="top",
        learned_preference={"총장": 73.0, "어깨너비": 52.0, "가슴단면": 60.0},
    )
    assert result[0]["size_recommendation"] == {"size": "L"}
    assert result[0]["fit_source_type"] == "learned_preference"


def test_list_recommendations_and_detail_declarative_validation() -> None:
    with TestClient(app) as client:
        # page < 0
        res_page_neg = client.get("/api/v1/recommendations?page=-1", headers={"X-User-Id": "1"})
        assert res_page_neg.status_code == 400
        assert res_page_neg.json()["code"] == "INVALID_REQUEST"

        # size < 1
        res_size_zero = client.get("/api/v1/recommendations?size=0", headers={"X-User-Id": "1"})
        assert res_size_zero.status_code == 400
        assert res_size_zero.json()["code"] == "INVALID_REQUEST"

        # size > 100
        res_size_large = client.get("/api/v1/recommendations?size=101", headers={"X-User-Id": "1"})
        assert res_size_large.status_code == 400
        assert res_size_large.json()["code"] == "INVALID_REQUEST"

        # requestId <= 0 in GET /{requestId}
        res_detail_zero = client.get("/api/v1/recommendations/0", headers={"X-User-Id": "1"})
        assert res_detail_zero.status_code == 400
        assert res_detail_zero.json()["code"] == "INVALID_REQUEST"

        res_detail_neg = client.get("/api/v1/recommendations/-10", headers={"X-User-Id": "1"})
        assert res_detail_neg.status_code == 400
        assert res_detail_neg.json()["code"] == "INVALID_REQUEST"


def test_llm_services_token_contextvars_concurrency() -> None:
    import asyncio
    from app.services.query_parser import QueryParser
    from app.services.harmonizer import OutfitHarmonizer
    from app.services.response_generator import ResponseGenerator

    parser = QueryParser()
    harmonizer = OutfitHarmonizer.__new__(OutfitHarmonizer)
    responder = ResponseGenerator()

    async def task_a() -> tuple[int, int, int]:
        parser.last_prompt_tokens = 100
        harmonizer.last_prompt_tokens = 200
        responder.last_prompt_tokens = 300
        await asyncio.sleep(0.02)
        return (
            parser.last_prompt_tokens,
            harmonizer.last_prompt_tokens,
            responder.last_prompt_tokens,
        )

    async def task_b() -> tuple[int, int, int]:
        await asyncio.sleep(0.01)
        parser.last_prompt_tokens = 999
        harmonizer.last_prompt_tokens = 888
        responder.last_prompt_tokens = 777
        await asyncio.sleep(0.02)
        return (
            parser.last_prompt_tokens,
            harmonizer.last_prompt_tokens,
            responder.last_prompt_tokens,
        )

    async def runner() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
        return await asyncio.gather(task_a(), task_b())

    res_a, res_b = asyncio.run(runner())
    # Task A's tokens must remain completely isolated from Task B
    assert res_a == (100, 200, 300)
    assert res_b == (999, 888, 777)


