from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import TryOnRequest, app, create_job


@pytest.fixture
def job_payload() -> dict[str, str]:
    return {
        "user_id": "12345678-1234-4678-9234-567812345678",
        "person_image_url": "https://images.example.com/person.png",
        "product_image_url": "https://images.example.com/product.png",
    }


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_request_accepts_http_image_urls(job_payload: dict[str, str], scheme: str) -> None:
    job_payload["person_image_url"] = f"{scheme}://images.example.com/person.png"
    job_payload["product_image_url"] = f"{scheme}://images.example.com/product.png"

    request = TryOnRequest(**job_payload)

    assert request.user_id == UUID(job_payload["user_id"])
    assert str(request.person_image_url) == job_payload["person_image_url"]
    assert str(request.product_image_url) == job_payload["product_image_url"]


@pytest.mark.parametrize("field", ["user_id", "person_image_url", "product_image_url"])
def test_request_requires_every_field(job_payload: dict[str, str], field: str) -> None:
    del job_payload[field]

    with pytest.raises(ValidationError) as error:
        TryOnRequest(**job_payload)

    assert any(item["loc"] == (field,) for item in error.value.errors())


@pytest.mark.parametrize("field", ["person_image_url", "product_image_url"])
@pytest.mark.parametrize("url", [None, "", "/image.png", "ftp://images.example.com/a.png"])
def test_request_rejects_invalid_image_urls(
    job_payload: dict[str, str], field: str, url: object
) -> None:
    payload = {**job_payload, field: url}

    with pytest.raises(ValidationError) as error:
        TryOnRequest(**payload)

    assert any(item["loc"] == (field,) for item in error.value.errors())


@pytest.mark.parametrize("user_id", [None, "", "not-a-uuid"])
def test_request_rejects_invalid_user_ids(
    job_payload: dict[str, str], user_id: object
) -> None:
    with pytest.raises(ValidationError) as error:
        TryOnRequest(**{**job_payload, "user_id": user_id})

    assert any(item["loc"] == ("user_id",) for item in error.value.errors())


def test_create_job_returns_a_new_queued_job_for_each_call(job_payload: dict[str, str]) -> None:
    request = TryOnRequest(**job_payload)

    first = create_job(request)
    second = create_job(request)

    assert first.state == second.state == "QUEUED"
    assert first.job_id.version == second.job_id.version == 4
    assert first.job_id != second.job_id


def test_post_job_accepts_request_and_serializes_queued_job(job_payload: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/tryon/jobs", json=job_payload)

    assert response.status_code == 202
    payload = response.json()
    assert set(payload) == {"job_id", "state"}
    assert payload["state"] == "QUEUED"
    assert UUID(payload["job_id"]).version == 4


@pytest.mark.parametrize("field", ["user_id", "person_image_url", "product_image_url"])
def test_post_job_reports_missing_fields(job_payload: dict[str, str], field: str) -> None:
    del job_payload[field]
    with TestClient(app) as client:
        response = client.post("/api/v1/tryon/jobs", json=job_payload)

    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "not-a-uuid"),
        ("person_image_url", "ftp://images.example.com/person.png"),
        ("product_image_url", "/product.png"),
    ],
)
def test_post_job_reports_invalid_fields(
    job_payload: dict[str, str], field: str, value: str
) -> None:
    job_payload[field] = value
    with TestClient(app) as client:
        response = client.post("/api/v1/tryon/jobs", json=job_payload)

    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])


def test_post_job_requires_a_body() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/tryon/jobs")

    assert response.status_code == 422
    assert any(error["loc"] == ["body"] for error in response.json()["detail"])
