from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.database import KST, RecommendationRepository
from app.main import app
from app.schemas.analytics import AnalyticsResponse


@pytest.fixture
def repo():
    return RecommendationRepository(db_path=":memory:")


def test_analytics_empty_db(repo):
    # Test with Tuesday 2026-10-27 15:00:00 KST (Oct 1, 2026 is Thursday -> Oct 27 is Tuesday of Week 5)
    ref_dt = datetime(2026, 10, 27, 15, 0, 0, tzinfo=KST)
    data = repo.get_analytics_data(reference_dt=ref_dt)
    assert "daily" in data
    assert "weekly" in data
    assert "monthly" in data
    assert "yearly" in data

    # Check daily
    daily = data["daily"]
    assert daily["label"] == "일간"
    assert daily["startDate"] == "2026-10-27"
    assert daily["endDate"] == "2026-10-27"
    assert len(daily["usage"]) == 6  # 00시, 04시, 08시, 12시, 16시, 20시
    for u in daily["usage"]:
        assert u["input"] == 0
        assert u["output"] == 0
    assert daily["keywords"] == []
    assert daily["products"] == []

    # Check weekly: Tuesday -> only ["월", "화"] (#3)
    weekly = data["weekly"]
    assert weekly["label"] == "주간"
    assert weekly["startDate"] == "2026-10-26"
    assert weekly["endDate"] == "2026-10-27"
    assert [u["label"] for u in weekly["usage"]] == ["월", "화"]
    for u in weekly["usage"]:
        assert u["input"] == 0
        assert u["output"] == 0

    # Check monthly: Oct 1 ~ Oct 27 (#4), calendar weeks 1주 ~ 5주 (#5)
    monthly = data["monthly"]
    assert monthly["label"] == "월간"
    assert monthly["startDate"] == "2026-10-01"
    assert monthly["endDate"] == "2026-10-27"
    assert [u["label"] for u in monthly["usage"]] == ["1주", "2주", "3주", "4주", "5주"]

    # Check yearly: Jan 1 ~ Oct 27, 1월 ~ 10월
    yearly = data["yearly"]
    assert yearly["label"] == "연간"
    assert yearly["startDate"] == "2026-01-01"
    assert yearly["endDate"] == "2026-10-27"
    assert len(yearly["usage"]) == 10  # 1월 ~ 10월 (현재 월까지)
    assert yearly["usage"][-1]["label"] == "10월"


def test_analytics_calendar_weeks_and_partial_month(repo):
    # Reference date: 2026-10-07 (Wednesday) KST
    # 2026-10-01 is Thursday -> 1주: 10/1(목)~10/4(일), 2주: 10/5(월)~10/7(수, 현재 날짜)
    ref_dt = datetime(2026, 10, 7, 14, 0, 0, tzinfo=KST)
    analytics = repo.get_analytics_data(reference_dt=ref_dt)

    weekly = analytics["weekly"]
    assert weekly["startDate"] == "2026-10-05"
    assert weekly["endDate"] == "2026-10-07"
    assert [u["label"] for u in weekly["usage"]] == ["월", "화", "수"]

    monthly = analytics["monthly"]
    assert monthly["startDate"] == "2026-10-01"
    assert monthly["endDate"] == "2026-10-07"
    assert [u["label"] for u in monthly["usage"]] == ["1주", "2주"]


def test_analytics_data_aggregation_and_vton_tokens(repo):
    # Reference date: 2026-10-06 14:30:00 KST (Tuesday, 2주 of Oct)
    # 2026-10-06 14:30:00 KST == 2026-10-06 05:30:00 UTC
    ref_dt = datetime(2026, 10, 6, 14, 30, 0, tzinfo=KST)

    # 1. Request 1: Single request at 14:10 KST (05:10 UTC) on 2026-10-06 (화, 2주)
    req1_id = repo.create_request(user_id=1, query_text="깔끔한 출근룩 미니멀 스타일 추천해줘")
    repo.complete_single_request(
        request_id=req1_id,
        tpo_summary="출근룩, 미니멀",
        items=[
            {"productId": 101, "productName": "릴렉스드 셔츠", "brandName": "무신사 스탠다드", "price": 35000},
            {"productId": 102, "productName": "슬림 슬랙스", "brandName": "슬로우애시드", "price": 49000},
        ],
        message="성공",
        prompt_tokens=1500,
        completion_tokens=500,
    )
    with repo._lock:
        conn = repo._get_sqlite_connection()
        conn.execute(
            "UPDATE recommendation_requests SET created_at = '2026-10-06T05:10:00Z' WHERE request_id = ?",
            (req1_id,),
        )
        conn.commit()

    # 2. Request 2: Combo request at 08:30 KST on 2026-10-02 (금, 1주: Oct 1 Thu ~ Oct 4 Sun)
    # 2026-10-02 08:30:00 KST == 2026-10-01 23:30:00 UTC
    req2_id = repo.create_request(user_id=2, query_text="데이트룩 캐주얼 코디")
    repo.complete_combo_request(
        request_id=req2_id,
        user_id=2,
        tpo_summary="데이트룩, 캐주얼",
        combos=[
            {
                "items": [
                    {"productId": 101, "productName": "릴렉스드 셔츠", "brandName": "무신사 스탠다드", "price": 35000},
                    {"productId": 103, "productName": "오버핏 블레이저", "brandName": "드로우핏", "price": 120000},
                ],
                "totalPrice": 155000,
            }
        ],
        message="성공",
        prompt_tokens=2000,
        completion_tokens=800,
    )
    with repo._lock:
        conn = repo._get_sqlite_connection()
        conn.execute(
            "UPDATE recommendation_requests SET created_at = '2026-10-01T23:30:00Z' WHERE request_id = ?",
            (req2_id,),
        )
        # 3. Create VTON fittings table in SQLite to test VTON OpenAI token aggregation (#6)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fittings (
                fitting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        # VTON completed at 2026-10-06 14:20 KST (05:20 UTC) -> slot 12시, 화, 2주, 10월
        conn.execute(
            """
            INSERT INTO fittings (status, prompt_tokens, completion_tokens, created_at)
            VALUES ('COMPLETED', 600, 1200, '2026-10-06T05:20:00Z')
            """
        )
        conn.commit()

    analytics = repo.get_analytics_data(reference_dt=ref_dt)

    # Check daily (2026-10-06 KST)
    daily = analytics["daily"]
    usage_by_label = {u["label"]: u for u in daily["usage"]}
    # 12시 slot should have req1 (1500/500) + VTON (600/1200) = 2100 / 1700
    assert usage_by_label["12시"]["input"] == 2100
    assert usage_by_label["12시"]["output"] == 1700
    assert usage_by_label["00시"]["input"] == 0

    # Check weekly (2026-10-05 Mon ~ 2026-10-06 Tue)
    weekly = analytics["weekly"]
    assert [u["label"] for u in weekly["usage"]] == ["월", "화"]
    weekly_by_label = {u["label"]: u for u in weekly["usage"]}
    assert weekly_by_label["월"]["input"] == 0
    assert weekly_by_label["화"]["input"] == 2100
    assert weekly_by_label["화"]["output"] == 1700

    # Check monthly (2026-10-01 Thu ~ 2026-10-06 Tue -> 1주 and 2주)
    monthly = analytics["monthly"]
    assert [u["label"] for u in monthly["usage"]] == ["1주", "2주"]
    monthly_by_label = {u["label"]: u for u in monthly["usage"]}
    # 1주 (Oct 1~4) has req2 (2000/800)
    assert monthly_by_label["1주"]["input"] == 2000
    assert monthly_by_label["1주"]["output"] == 800
    # 2주 (Oct 5~6) has req1 + VTON (2100/1700)
    assert monthly_by_label["2주"]["input"] == 2100
    assert monthly_by_label["2주"]["output"] == 1700

    # Check monthly keywords & products
    kw_names = [k["name"] for k in monthly["keywords"]]
    assert "출근룩" in kw_names
    assert "미니멀" in kw_names
    assert "데이트룩" in kw_names
    assert "캐주얼" in kw_names

    products = monthly["products"]
    shirt = next((p for p in products if p["name"] == "릴렉스드 셔츠"), None)
    assert shirt is not None
    assert shirt["count"] == 2
    assert shirt["brand"] == "무신사 스탠다드"


def test_analytics_api_endpoint():
    client = TestClient(app)
    fake_repo = RecommendationRepository(db_path=":memory:")
    app.state.repository = fake_repo

    # Seed data
    req_id = fake_repo.create_request(user_id=1, query_text="가을 코디 추천")
    fake_repo.complete_single_request(
        request_id=req_id,
        tpo_summary="가을 코디",
        items=[{"productId": 1, "productName": "트렌치 코트", "brandName": "스파오", "price": 89000}],
        message="성공",
        prompt_tokens=1000,
        completion_tokens=400,
    )

    # 1. Unauthenticated request -> 401 UNAUTHORIZED
    unauth_res = client.get("/api/recommendations/analytics")
    assert unauth_res.status_code == 401
    assert unauth_res.json()["code"] == "UNAUTHENTICATED"

    # 2. Non-admin user (e.g., userId=1) -> 403 FORBIDDEN
    forbidden_res = client.get(
        "/api/recommendations/analytics",
        headers={"X-User-Id": "1"},
    )
    assert forbidden_res.status_code == 403
    assert forbidden_res.json()["code"] == "FORBIDDEN"

    # 3. Admin user (fitzzaadm, userId=4) -> 200 OK
    res = client.get(
        "/api/recommendations/analytics",
        headers={"X-User-Id": "4"},
    )
    assert res.status_code == 200
    body = res.json()
    validated = AnalyticsResponse(**body)
    assert validated.daily.label == "일간"
    assert validated.weekly.label == "주간"
    assert validated.monthly.label == "월간"
    assert validated.yearly.label == "연간"

    today_kst_str = datetime.now(KST).strftime("%Y-%m-%d")
    assert validated.daily.startDate == today_kst_str
    assert validated.daily.endDate == today_kst_str
    assert validated.weekly.endDate == today_kst_str
    assert validated.monthly.endDate == today_kst_str

    # 4. Gateway backward compatibility path /api/v1/recommendations/analytics with admin header
    compat_res = client.get(
        "/api/v1/recommendations/analytics",
        headers={"X-User-Id": "4"},
    )
    assert compat_res.status_code == 200


def test_analytics_with_mocked_vton_client(repo):
    ref_dt = datetime(2026, 10, 27, 14, 0, 0, tzinfo=KST)

    class MockVtonClient:
        is_configured = True

        def get_token_usage_in_range(self, start_iso: str, end_iso: str):
            return [
                {
                    "promptTokens": 800,
                    "completionTokens": 1600,
                    "createdAt": "2026-10-27T05:00:00Z",  # 14:00 KST (12시 slot, 화요일)
                }
            ]

    data = repo.get_analytics_data(reference_dt=ref_dt, vton_client=MockVtonClient())
    daily_usage = {u["label"]: u for u in data["daily"]["usage"]}
    assert daily_usage["12시"]["input"] == 800
    assert daily_usage["12시"]["output"] == 1600

    weekly_usage = {u["label"]: u for u in data["weekly"]["usage"]}
    assert weekly_usage["화"]["input"] == 800
    assert weekly_usage["화"]["output"] == 1600
