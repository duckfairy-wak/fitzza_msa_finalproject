from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import RecommendationRequest, app, recommend

USER_ID = "12345678-1234-4678-9234-567812345678"


def test_request_defaults_to_ten_recommendations() -> None:
    request = RecommendationRequest(user_id=USER_ID)

    assert request.user_id == UUID(USER_ID)
    assert request.limit == 10


@pytest.mark.parametrize("limit", [1, 10, 100])
def test_recommend_returns_empty_placeholder_for_valid_limits(limit: int) -> None:
    request = RecommendationRequest(user_id=USER_ID, limit=limit)

    response = recommend(request)

    assert response.user_id == UUID(USER_ID)
    assert response.product_ids == []


@pytest.mark.parametrize("limit", [0, -1, 101, None, "many", 1.5])
def test_request_rejects_invalid_limits(limit: object) -> None:
    with pytest.raises(ValidationError) as error:
        RecommendationRequest(user_id=USER_ID, limit=limit)

    assert any(item["loc"] == ("limit",) for item in error.value.errors())


@pytest.mark.parametrize("user_id", [None, "", "not-a-uuid"])
def test_request_rejects_invalid_user_ids(user_id: object) -> None:
    with pytest.raises(ValidationError) as error:
        RecommendationRequest(user_id=user_id)

    assert any(item["loc"] == ("user_id",) for item in error.value.errors())


def test_recommendations_do_not_share_product_lists_between_users() -> None:
    first = recommend(RecommendationRequest(user_id=USER_ID))
    first.product_ids.append(UUID("00000000-0000-0000-0000-000000000001"))
    second_user = UUID("87654321-4321-4876-9234-567812345678")

    second = recommend(RecommendationRequest(user_id=second_user))

    assert second.user_id == second_user
    assert second.product_ids == []


@pytest.mark.parametrize("options", [{}, {"limit": 1}, {"limit": 100}])
def test_post_recommendations_serializes_the_response(options: dict) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/recommendations", json={"user_id": USER_ID, **options}
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID, "product_ids": []}


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "user_id"),
        ({"user_id": "not-a-uuid"}, "user_id"),
        ({"user_id": USER_ID, "limit": 0}, "limit"),
        ({"user_id": USER_ID, "limit": 101}, "limit"),
        ({"user_id": USER_ID, "limit": None}, "limit"),
    ],
)
def test_post_recommendations_reports_invalid_fields(payload: dict, field: str) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/recommendations", json=payload)

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", field] for error in response.json()["detail"]
    )


def test_post_recommendations_requires_a_body() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/recommendations")

    assert response.status_code == 422
    assert any(error["loc"] == ["body"] for error in response.json()["detail"])
