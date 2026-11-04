import sqlite3

from app.core.database import RecommendationRepository


def test_size_preferences_are_stored_per_fit_type(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))

    repo.save_size_feedback(7, 1, 11, "FIT", subcategory="겨울 더블 코트", fit_type="오버핏",
                            preference_spec={"가슴단면": 68.0})
    repo.save_size_feedback(7, 2, 21, "FIT", subcategory="겨울 더블 코트", fit_type="레귤러",
                            preference_spec={"가슴단면": 60.0})

    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="오버 사이즈") == {"가슴단면": 68.0}
    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="레귤러") == {"가슴단면": 60.0}


def test_size_preference_falls_back_to_regular_fit(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))
    repo.save_size_feedback(7, 2, 21, "FIT", subcategory="겨울 더블 코트", fit_type="",
                            preference_spec={"가슴단면": 60.0})

    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="슬림") == {"가슴단면": 60.0}
    assert repo.get_user_size_preference(7, "겨울 더블 코트") == {"가슴단면": 60.0}


def test_regular_lookup_does_not_use_other_fit_rows(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))
    repo.save_size_feedback(7, 1, 11, "FIT", subcategory="겨울 더블 코트", fit_type="오버 사이즈",
                            preference_spec={"가슴단면": 68.0})

    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="레귤러") is None


def test_sqlite_legacy_preference_table_is_migrated_to_fit_primary_key(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE user_size_preferences (
            user_id INTEGER NOT NULL,
            subcategory TEXT NOT NULL,
            fit_type TEXT NOT NULL DEFAULT '',
            preference_spec_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, subcategory)
        );
        INSERT INTO user_size_preferences VALUES (7, '셔츠', '', '{"가슴단면": 59.0}', 3, '2026-11-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    repo = RecommendationRepository(db_path=str(db_path))

    assert repo.get_user_size_preference(7, "셔츠", fit_type="레귤러") == {"가슴단면": 59.0}
    repo.save_size_feedback(7, 3, 31, "FIT", subcategory="셔츠", fit_type="오버핏",
                            preference_spec={"가슴단면": 64.0})
    assert repo.get_user_size_preference(7, "셔츠", fit_type="오버핏") == {"가슴단면": 64.0}
    assert repo.get_user_size_preference(7, "셔츠", fit_type="레귤러") == {"가슴단면": 59.0}


def test_size_preference_merge_uses_exponential_moving_average(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))
    repo.save_size_feedback(7, 1, 11, "FIT", subcategory="셔츠", fit_type="레귤러", preference_spec={"가슴단면": 60.0})
    repo.save_size_feedback(7, 2, 21, "SMALL", subcategory="셔츠", fit_type="레귤러", preference_spec={"가슴단면": 70.0})

    assert repo.get_user_size_preference(7, "셔츠", fit_type="레귤러") == {"가슴단면": 63.0}


def test_feedback_small_uses_midpoint_with_next_larger_size() -> None:
    from app.services.size_resolver import build_feedback_preference_spec

    spec = build_feedback_preference_spec(
        "SMALL",
        {"가슴단면": 58.0, "어깨너비": 50.0, "총장": 72.0},
        [
            {"가슴단면": 55.0, "어깨너비": 48.0, "총장": 70.0},
            {"가슴단면": 61.0, "어깨너비": 52.0, "총장": 74.0},
            {"가슴단면": 64.0, "어깨너비": 54.0, "총장": 76.0},
        ],
        "상의",
    )
    assert spec == {"가슴단면": 59.5, "어깨너비": 51.0, "총장": 73.0}


def test_feedback_big_uses_midpoint_with_next_smaller_size() -> None:
    from app.services.size_resolver import build_feedback_preference_spec

    spec = build_feedback_preference_spec(
        "BIG",
        {"허리단면": 40.0, "총장": 100.0},
        [{"허리단면": 38.0, "총장": 99.0}, {"허리단면": 42.0, "총장": 101.0}],
        "하의",
    )
    assert spec == {"허리단면": 39.0, "총장": 99.5}


def test_feedback_without_neighbor_size_offsets_core_fields_only() -> None:
    from app.services.size_resolver import build_feedback_preference_spec

    top = build_feedback_preference_spec("SMALL", {"가슴단면": 64.0, "총장": 76.0}, [{"가슴단면": 61.0, "총장": 74.0}], "상의")
    assert top == {"가슴단면": 65.5, "총장": 76.0}

    shoes = build_feedback_preference_spec("SMALL", {"발길이": 270.0}, [], "신발")
    assert shoes == {"발길이": 275.0}


def test_feedback_fit_keeps_purchased_spec() -> None:
    from app.services.size_resolver import build_feedback_preference_spec

    assert build_feedback_preference_spec("FIT", {"가슴단면": 58.0}, [{"가슴단면": 61.0}], "상의") == {"가슴단면": 58.0}


def test_process_size_feedback_uses_sibling_size_measurements() -> None:
    from app.services.size_resolver import process_size_feedback

    class SiblingProductClient:
        def get_product_measurements(self, product_ids, request_id_header=None):
            return {
                501: [
                    {"option_id": 1, "size": "M", "measurements": {"가슴단면": 58.0, "어깨너비": 50.0}},
                    {"option_id": 2, "size": "M", "measurements": {"가슴단면": 58.0, "어깨너비": 50.0}},
                    {"option_id": 3, "size": "L", "measurements": {"가슴단면": 61.0, "어깨너비": 52.0}},
                ]
            }

    class RecordingRepository:
        def __init__(self):
            self.saved = None

        def save_size_feedback(self, **kwargs):
            self.saved = kwargs

        def get_user_size_preference(self, **kwargs):
            return None

    repo = RecordingRepository()
    process_size_feedback(
        user_id=7,
        product_id=501,
        option_id=1,
        size_feedback="SMALL",
        repository=repo,
        product_client=SiblingProductClient(),
        qdrant_payload={"category": "상의", "subcategory": "셔츠", "features": {"핏": ["레귤러"]}},
    )

    assert repo.saved["preference_spec"] == {"가슴단면": 59.5, "어깨너비": 51.0}
    assert repo.saved["fit_type"] == "레귤러"


def test_sqlite_preference_migration_rolls_back_on_failure(tmp_path) -> None:
    import pytest

    db_path = tmp_path / "broken.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE user_size_preferences (
            user_id INTEGER NOT NULL,
            subcategory TEXT NOT NULL,
            fit_type TEXT NOT NULL DEFAULT '',
            preference_spec_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT,
            PRIMARY KEY (user_id, subcategory)
        );
        INSERT INTO user_size_preferences VALUES (7, '셔츠', '', '{"가슴단면": 59.0}', 1, NULL);
        """
    )
    conn.commit()
    conn.close()

    # 새 테이블의 updated_at NOT NULL 제약 때문에 데이터 복사 단계에서 실패한다.
    with pytest.raises(sqlite3.Error):
        RecommendationRepository(db_path=str(db_path))

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    rows = conn.execute("SELECT user_id, subcategory FROM user_size_preferences").fetchall()
    conn.close()

    assert "user_size_preferences_legacy" not in tables
    assert rows == [(7, "셔츠")]
