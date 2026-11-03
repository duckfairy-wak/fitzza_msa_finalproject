import os
import pytest
from app.services.size_resolver import SizeProfileResolver


@pytest.fixture
def resolver(tmp_path):
    # 테스트용 독립 resolver 인스턴스
    return SizeProfileResolver()


def test_fallback_priority_1_my_specific_fit_preference(resolver):
    """
    1순위: 내 슬림핏 선호 실측 (내 데이터 + 슬림핏)
    userId=1은 '슈트/블레이저 재킷'에 대해 레귤러/오버사이즈/슬림 선호 실측을 모두 보유.
    슬림 요청 시 슬림 선호 실측(73.0, 47.0, 53.0)을 즉시 채택해야 함.
    """
    baseline = resolver._get_baseline_spec(
        user_id="1",
        subcategory="슈트/블레이저 재킷",
        fit_type="슬림",
        category_type="아우터",
    )
    assert baseline["source"] == "learned_preference"
    assert baseline["data"]["총장"] == 73.0
    assert baseline["data"]["어깨너비"] == 47.0
    assert baseline["data"]["가슴단면"] == 53.0


def test_fallback_priority_2_my_specific_fit_order():
    """
    2순위: 내 선호 실측에는 슬림이 없지만, 내 구매 이력에 슬림핏이 있는 경우
    (핏 의도를 유지하여 레귤러 선호 실측으로 새지 않고 슬림핏 구매 이력을 채택)
    """
    resolver = SizeProfileResolver()
    resolver.mock_db = {
        "users": [{"user_id": "test_user", "height": 178.0, "weight": 72.0}],
        "user_preferences": [
            {
                "user_id": "test_user",
                "subcategory": "반소매 티셔츠",
                "fit_type": "레귤러",
                "preference_spec": {"총장": 73.0, "어깨너비": 50.0, "가슴단면": 56.0},
            }
        ],
        "orders_and_surveys": [
            {
                "order_id": "order_slim_01",
                "user_id": "test_user",
                "subcategory": "반소매 티셔츠",
                "fit_type": "슬림",
                "measurement_spec": {"총장": 70.0, "어깨너비": 46.0, "가슴단면": 51.0},
            }
        ],
        "other_users_fits": []
    }

    baseline = resolver._get_baseline_spec(
        user_id="test_user",
        subcategory="반소매 티셔츠",
        fit_type="슬림",
        category_type="상의",
    )
    # 레귤러 선호 실측이 있더라도 핏을 지키기 위해 2순위인 내 '슬림핏' 구매 이력을 우선 채택!
    assert baseline["source"] == "recent_purchase"
    assert baseline["data"]["총장"] == 70.0
    assert baseline["data"]["가슴단면"] == 51.0


def test_fallback_priority_3_similar_body_specific_fit():
    """
    3순위: 내 선호 실측에도 없고, 내 구매 이력도 일반(레귤러)뿐이지만,
    키/몸무게 유사 체형의 타 사용자가 슬림핏 인증(FIT)을 남긴 실측이 있는 경우
    (슬림핏 의도를 유지하여 유사체형 슬림핏 실측 채택)
    """
    resolver = SizeProfileResolver()
    resolver.mock_db = {
        "users": [{"user_id": "1", "height": 178.0, "weight": 72.0}],
        "user_preferences": [],
        "orders_and_surveys": [
            {
                "order_id": "order_reg_99",
                "user_id": "1",
                "subcategory": "반소매 티셔츠",
                "fit_type": "레귤러",
                "measurement_spec": {"총장": 73.0, "어깨너비": 50.0, "가슴단면": 56.0},
            }
        ],
        "other_users_fits": [
            {
                "fit_id": "fit_other_slim",
                "height": 178.0,
                "weight": 72.0,
                "subcategory": "반소매 티셔츠",
                "fit_type": "슬림",
                "fit_feedback": "FIT",
                "measurement_spec": {"총장": 70.0, "어깨너비": 46.0, "가슴단면": 51.0},
            }
        ]
    }
    baseline = resolver._get_baseline_spec(
        user_id="1",
        subcategory="반소매 티셔츠",
        fit_type="슬림",
        category_type="상의",
    )
    assert baseline["source"] == "similar_body_profile"
    assert baseline["data"]["총장"] == 70.0
    assert baseline["data"]["어깨너비"] == 46.0
    assert baseline["data"]["가슴단면"] == 51.0


def test_fallback_priority_4_fallback_to_my_regular_preference():
    """
    2단계 - 4순위: 슬림핏 데이터(선호, 구매, 유사체형)가 전혀 없는 경우
    내 레귤러/기본 선호 실측으로 안전하게 폴백
    """
    resolver = SizeProfileResolver()
    resolver.mock_db = {
        "users": [{"user_id": "test_user_4", "height": 178.0, "weight": 72.0}],
        "user_preferences": [
            {
                "user_id": "test_user_4",
                "subcategory": "카디건",
                "fit_type": "레귤러",
                "preference_spec": {"총장": 70.0, "어깨너비": 50.0, "가슴단면": 58.0},
            }
        ],
        "orders_and_surveys": [],
        "other_users_fits": []
    }

    baseline = resolver._get_baseline_spec(
        user_id="test_user_4",
        subcategory="카디건",
        fit_type="슬림",  # 슬림 데이터가 전혀 없음
        category_type="상의",
    )
    assert baseline["source"] == "learned_preference"
    assert baseline["data"]["총장"] == 70.0
    assert baseline["data"]["가슴단면"] == 58.0


def test_fallback_priority_5_fallback_to_my_regular_order():
    """
    2단계 - 5순위: 슬림핏 데이터 및 선호 실측이 모두 없는 경우
    내 일반(레귤러) 구매 이력 실측으로 폴백
    """
    resolver = SizeProfileResolver()
    resolver.mock_db = {
        "users": [{"user_id": "test_user_5", "height": 178.0, "weight": 72.0}],
        "user_preferences": [],
        "orders_and_surveys": [
            {
                "order_id": "order_reg_01",
                "user_id": "test_user_5",
                "subcategory": "데님 팬츠",
                "fit_type": "레귤러",
                "measurement_spec": {"총장": 104.0, "허리단면": 41.5, "밑위": 28.5},
            }
        ],
        "other_users_fits": []
    }

    baseline = resolver._get_baseline_spec(
        user_id="test_user_5",
        subcategory="데님 팬츠",
        fit_type="슬림",  # 슬림 데이터 없음
        category_type="하의",
    )
    assert baseline["source"] == "recent_purchase"
    assert baseline["data"]["총장"] == 104.0
    assert baseline["data"]["허리단면"] == 41.5


def test_fallback_priority_6_fallback_to_similar_body_regular():
    """
    2단계 - 6순위: 슬림핏 데이터, 본인 선호 실측, 본인 구매 이력이 모두 없는 경우
    유사 체형 사용자의 일반 실측으로 폴백
    """
    resolver = SizeProfileResolver()
    resolver.mock_db = {
        "users": [{"user_id": "test_user_6", "height": 178.0, "weight": 72.0}],
        "user_preferences": [],
        "orders_and_surveys": [],
        "other_users_fits": [
            {
                "fit_id": "fit_other_reg",
                "height": 179.0,
                "weight": 73.0,
                "subcategory": "맨투맨/스웨트",
                "fit_type": "레귤러",
                "fit_feedback": "FIT",
                "measurement_spec": {"총장": 71.0, "어깨너비": 52.0, "가슴단면": 60.0},
            }
        ]
    }

    baseline = resolver._get_baseline_spec(
        user_id="test_user_6",
        subcategory="맨투맨/스웨트",
        fit_type="슬림",  # 슬림 데이터 없음
        category_type="상의",
    )
    assert baseline["source"] == "similar_body_profile"
    assert baseline["data"]["총장"] == 71.0
    assert baseline["data"]["가슴단면"] == 60.0


def test_shoe_size_only_user_body_is_preserved():
    """
    키와 몸무게 없이 shoeSize만 전달된 경우에도 신발 카테고리 추천 시
    target_user가 버려지지 않고 body_profile 경로로 신발 사이즈가 반영되어야 함
    """
    resolver = SizeProfileResolver(enable_mock_data=False)
    baseline = resolver._get_baseline_spec(
        user_id="unknown_user_999",
        subcategory="스니커즈",
        fit_type="레귤러",
        category_type="신발",
        user_body={"shoeSize": 275},
    )
    assert baseline["source"] == "body_profile"
    assert baseline["data"]["shoe_size"] == 275.0
    assert baseline["data"]["발길이"] == 275.0


def test_general_fit_update_does_not_overwrite_specific_fit_preference():
    """
    특정 핏(오버사이즈) 선호 데이터만 있는 상태에서 일반(레귤러) 핏 피드백/동기화가 들어올 때
    기존 오버사이즈 항목을 오염시키지 않고 별도 레귤러 항목으로 추가해야 함
    """
    from app.services.size_resolver import sync_user_size_preference

    resolver = SizeProfileResolver(enable_mock_data=False)
    resolver.mock_db["user_preferences"] = [
        {
            "preference_id": 1,
            "user_id": "10",
            "subcategory": "셔츠/블라우스",
            "fit_type": "오버사이즈",
            "preference_spec": {"총장": 80.0, "가슴단면": 62.0},
            "sample_count": 3,
        }
    ]

    resolver.update_fit_preferences(
        user_id="10",
        subcategory="셔츠/블라우스",
        fit_type="레귤러",
        purchased_size_spec={"총장": 74.0, "가슴단면": 55.0},
    )

    prefs = resolver.mock_db["user_preferences"]
    assert len(prefs) == 2
    assert prefs[0]["fit_type"] == "오버사이즈"
    assert prefs[0]["preference_spec"]["가슴단면"] == 62.0
    assert prefs[1]["fit_type"] == "레귤러"
    assert prefs[1]["preference_spec"]["가슴단면"] == 55.0

    # sync_user_size_preference도 특정 핏만 있을 때 덮어쓰지 않아야 함
    resolver2 = SizeProfileResolver(enable_mock_data=False)
    resolver2.mock_db["user_preferences"] = [
        {
            "preference_id": 1,
            "user_id": "20",
            "subcategory": "후드 티셔츠",
            "fit_type": "슬림",
            "preference_spec": {"총장": 68.0, "가슴단면": 51.0},
            "sample_count": 2,
        }
    ]
    sync_user_size_preference(
        size_resolver=resolver2,
        user_id="20",
        subcategory="후드 티셔츠",
        fit_type="레귤러",
        pref_spec={"총장": 72.0, "가슴단면": 58.0},
    )
    prefs2 = resolver2.mock_db["user_preferences"]
    assert len(prefs2) == 2
    assert prefs2[0]["fit_type"] == "슬림"
    assert prefs2[0]["preference_spec"]["가슴단면"] == 51.0
    assert prefs2[1]["fit_type"] == "레귤러"
    assert prefs2[1]["preference_spec"]["가슴단면"] == 58.0


def test_production_mode_disables_mock_size_data(monkeypatch):
    """
    운영 환경(ENABLE_DEV_MOCK_SIZE_DATA=false, PYTEST_CURRENT_TEST 미설정)에서는
    mock_size_data.json을 메모리에 로드하지 않아야 함
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ENABLE_DEV_MOCK_SIZE_DATA", "false")
    resolver = SizeProfileResolver()
    assert resolver.enable_mock_data is False
    assert resolver.mock_db["users"] == []
    assert resolver.mock_db["user_preferences"] == []
    assert resolver.mock_db["orders_and_surveys"] == []
    assert resolver.mock_db["other_users_fits"] == []
