import sqlite3

from app.core.database import RecommendationRepository


def test_size_preferences_are_stored_per_fit_type(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))

    repo.save_size_feedback(7, 1, 11, "FIT", subcategory="겨울 더블 코트", fit_type="오버핏",
                            purchased_spec={"가슴단면": 68.0})
    repo.save_size_feedback(7, 2, 21, "FIT", subcategory="겨울 더블 코트", fit_type="레귤러",
                            purchased_spec={"가슴단면": 60.0})

    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="오버 사이즈") == {"가슴단면": 68.0}
    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="레귤러") == {"가슴단면": 60.0}


def test_size_preference_falls_back_to_regular_fit(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))
    repo.save_size_feedback(7, 2, 21, "FIT", subcategory="겨울 더블 코트", fit_type="",
                            purchased_spec={"가슴단면": 60.0})

    assert repo.get_user_size_preference(7, "겨울 더블 코트", fit_type="슬림") == {"가슴단면": 60.0}
    assert repo.get_user_size_preference(7, "겨울 더블 코트") == {"가슴단면": 60.0}


def test_regular_lookup_does_not_use_other_fit_rows(tmp_path) -> None:
    repo = RecommendationRepository(db_path=str(tmp_path / "rec.db"))
    repo.save_size_feedback(7, 1, 11, "FIT", subcategory="겨울 더블 코트", fit_type="오버 사이즈",
                            purchased_spec={"가슴단면": 68.0})

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
                            purchased_spec={"가슴단면": 64.0})
    assert repo.get_user_size_preference(7, "셔츠", fit_type="오버핏") == {"가슴단면": 64.0}
    assert repo.get_user_size_preference(7, "셔츠", fit_type="레귤러") == {"가슴단면": 59.0}
