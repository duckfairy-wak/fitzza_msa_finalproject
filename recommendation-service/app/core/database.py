import json
import math
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def _validate_identifier(identifier: str) -> str:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(f"유효하지 않은 SQL 식별자입니다: {identifier}")
    return identifier


class RecommendationRepository:
    def __init__(
        self,
        db_path: str = ":memory:",
        postgres_dsn: str | None = None,
        postgres_schema: str = "recommendation",
    ) -> None:
        self.db_path = db_path
        self.postgres_dsn = (postgres_dsn or "").strip() or None
        self.postgres_schema = _validate_identifier(postgres_schema or "recommendation")
        self._use_postgres = self.postgres_dsn is not None and db_path != ":memory:"
        self._lock = threading.RLock()
        self._persistent_conn: sqlite3.Connection | None = None
        if not self._use_postgres and db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_schema()

    def _get_pg_connection(self) -> Any:
        try:
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(
                self.postgres_dsn,
                row_factory=dict_row,
                options=f"-c search_path={self.postgres_schema}",
            )
        except ImportError:
            import psycopg2
            import psycopg2.extras

            return psycopg2.connect(
                self.postgres_dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
                options=f"-c search_path={self.postgres_schema}",
            )

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_sqlite_if_transient(self, conn: sqlite3.Connection) -> None:
        if conn is not self._persistent_conn:
            conn.close()

    def _init_schema(self) -> None:
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
                        cur.execute(
                            f"""
                            CREATE TABLE IF NOT EXISTS {schema}.recommendation_requests (
                                request_id BIGSERIAL PRIMARY KEY,
                                user_id BIGINT NOT NULL,
                                query_text TEXT NOT NULL,
                                status VARCHAR(32) NOT NULL,
                                search_type VARCHAR(32),
                                tpo_summary TEXT,
                                items_json TEXT NOT NULL DEFAULT '[]',
                                message TEXT,
                                created_at TEXT NOT NULL
                            );

                            CREATE INDEX IF NOT EXISTS idx_rec_requests_user_created
                                ON {schema}.recommendation_requests (user_id, request_id DESC);

                            CREATE TABLE IF NOT EXISTS {schema}.recommendation_combos (
                                combo_id BIGSERIAL PRIMARY KEY,
                                request_id BIGINT NOT NULL
                                    REFERENCES {schema}.recommendation_requests(request_id),
                                user_id BIGINT NOT NULL,
                                rank_order INTEGER NOT NULL DEFAULT 1,
                                total_price INTEGER NOT NULL DEFAULT 0,
                                pass_status VARCHAR(32) NOT NULL DEFAULT 'PASS',
                                harmony_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                                feedback_summary TEXT NOT NULL DEFAULT '',
                                budget_exceeded INTEGER NOT NULL DEFAULT 0,
                                items_json TEXT NOT NULL DEFAULT '[]'
                            );

                            CREATE INDEX IF NOT EXISTS idx_rec_combos_request
                                ON {schema}.recommendation_combos (request_id, rank_order ASC);

                            CREATE TABLE IF NOT EXISTS {schema}.user_size_preferences (
                                user_id BIGINT NOT NULL,
                                subcategory VARCHAR(100) NOT NULL,
                                fit_type VARCHAR(50) NOT NULL DEFAULT '',
                                preference_spec_json TEXT NOT NULL,
                                sample_count INTEGER NOT NULL DEFAULT 1,
                                updated_at TEXT NOT NULL,
                                PRIMARY KEY (user_id, subcategory)
                            );

                            CREATE TABLE IF NOT EXISTS {schema}.size_feedback_logs (
                                feedback_id BIGSERIAL PRIMARY KEY,
                                user_id BIGINT NOT NULL,
                                product_id BIGINT NOT NULL,
                                option_id BIGINT NOT NULL,
                                size_feedback VARCHAR(16) NOT NULL,
                                created_at TEXT NOT NULL
                            );
                            """
                        )
                    conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS recommendation_requests (
                        request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        query_text TEXT NOT NULL,
                        status TEXT NOT NULL,
                        search_type TEXT,
                        tpo_summary TEXT,
                        items_json TEXT NOT NULL DEFAULT '[]',
                        message TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_recommendation_requests_user_created
                        ON recommendation_requests (user_id, request_id DESC);

                    CREATE TABLE IF NOT EXISTS recommendation_combos (
                        combo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        request_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        rank_order INTEGER NOT NULL DEFAULT 1,
                        total_price INTEGER NOT NULL DEFAULT 0,
                        pass_status TEXT NOT NULL DEFAULT 'PASS',
                        harmony_score REAL NOT NULL DEFAULT 0.0,
                        feedback_summary TEXT NOT NULL DEFAULT '',
                        budget_exceeded INTEGER NOT NULL DEFAULT 0,
                        items_json TEXT NOT NULL DEFAULT '[]',
                        FOREIGN KEY (request_id) REFERENCES recommendation_requests(request_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_recommendation_combos_request
                        ON recommendation_combos (request_id, rank_order ASC);

                    CREATE TABLE IF NOT EXISTS user_size_preferences (
                        user_id INTEGER NOT NULL,
                        subcategory TEXT NOT NULL,
                        fit_type TEXT NOT NULL DEFAULT '',
                        preference_spec_json TEXT NOT NULL,
                        sample_count INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, subcategory)
                    );

                    CREATE TABLE IF NOT EXISTS size_feedback_logs (
                        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        option_id INTEGER NOT NULL,
                        size_feedback TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_request(self, user_id: int, query_text: str) -> int:
        now = self._now_iso()
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO recommendation_requests (
                                user_id, query_text, status, items_json, created_at
                            ) VALUES (%s, %s, 'PROCESSING', '[]', %s)
                            RETURNING request_id
                            """,
                            (user_id, query_text, now),
                        )
                        row = cur.fetchone()
                    conn.commit()
                    return int(row["request_id"])

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO recommendation_requests (
                        user_id, query_text, status, items_json, created_at
                    ) VALUES (?, ?, 'PROCESSING', '[]', ?)
                    """,
                    (user_id, query_text, now),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                self._close_sqlite_if_transient(conn)

    def complete_single_request(
        self,
        request_id: int,
        tpo_summary: str | None,
        items: list[dict[str, Any]],
        message: str | None,
    ) -> None:
        items_str = json.dumps(items, ensure_ascii=False)
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE recommendation_requests
                            SET status = 'DONE',
                                search_type = 'SINGLE',
                                tpo_summary = %s,
                                items_json = %s,
                                message = %s
                            WHERE request_id = %s
                            """,
                            (tpo_summary, items_str, message, request_id),
                        )
                    conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                conn.execute(
                    """
                    UPDATE recommendation_requests
                    SET status = 'DONE',
                        search_type = 'SINGLE',
                        tpo_summary = ?,
                        items_json = ?,
                        message = ?
                    WHERE request_id = ?
                    """,
                    (tpo_summary, items_str, message, request_id),
                )
                conn.commit()
            finally:
                self._close_sqlite_if_transient(conn)

    def complete_combo_request(
        self,
        request_id: int,
        user_id: int,
        tpo_summary: str | None,
        combos: list[dict[str, Any]],
        message: str | None,
    ) -> list[dict[str, Any]]:
        saved_combos: list[dict[str, Any]] = []
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        for idx, combo in enumerate(combos, start=1):
                            items = combo.get("items", [])
                            total_price = int(combo.get("totalPrice") or 0)
                            pass_status = str(combo.get("passStatus") or "PASS")
                            harmony_score = float(combo.get("harmonyScore") or 0.0)
                            feedback_summary = str(combo.get("feedbackSummary") or "")
                            budget_exceeded = 1 if combo.get("budgetExceeded") else 0

                            cur.execute(
                                """
                                INSERT INTO recommendation_combos (
                                    request_id, user_id, rank_order, total_price,
                                    pass_status, harmony_score, feedback_summary,
                                    budget_exceeded, items_json
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                RETURNING combo_id
                                """,
                                (
                                    request_id,
                                    user_id,
                                    idx,
                                    total_price,
                                    pass_status,
                                    harmony_score,
                                    feedback_summary,
                                    budget_exceeded,
                                    json.dumps(items, ensure_ascii=False),
                                ),
                            )
                            combo_id = int(cur.fetchone()["combo_id"])
                            saved_combos.append(
                                {
                                    "comboId": combo_id,
                                    "items": items,
                                    "totalPrice": total_price,
                                    "passStatus": pass_status,
                                    "harmonyScore": harmony_score,
                                    "feedbackSummary": feedback_summary,
                                    "budgetExceeded": bool(budget_exceeded),
                                }
                            )

                        cur.execute(
                            """
                            UPDATE recommendation_requests
                            SET status = 'DONE',
                                search_type = 'COMBO',
                                tpo_summary = %s,
                                items_json = '[]',
                                message = %s
                            WHERE request_id = %s
                            """,
                            (tpo_summary, message, request_id),
                        )
                    conn.commit()
            return saved_combos

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                for idx, combo in enumerate(combos, start=1):
                    items = combo.get("items", [])
                    total_price = int(combo.get("totalPrice") or 0)
                    pass_status = str(combo.get("passStatus") or "PASS")
                    harmony_score = float(combo.get("harmonyScore") or 0.0)
                    feedback_summary = str(combo.get("feedbackSummary") or "")
                    budget_exceeded = 1 if combo.get("budgetExceeded") else 0

                    cursor = conn.execute(
                        """
                        INSERT INTO recommendation_combos (
                            request_id,
                            user_id,
                            rank_order,
                            total_price,
                            pass_status,
                            harmony_score,
                            feedback_summary,
                            budget_exceeded,
                            items_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            request_id,
                            user_id,
                            idx,
                            total_price,
                            pass_status,
                            harmony_score,
                            feedback_summary,
                            budget_exceeded,
                            json.dumps(items, ensure_ascii=False),
                        ),
                    )
                    combo_id = int(cursor.lastrowid)
                    saved_combos.append(
                        {
                            "comboId": combo_id,
                            "items": items,
                            "totalPrice": total_price,
                            "passStatus": pass_status,
                            "harmonyScore": harmony_score,
                            "feedbackSummary": feedback_summary,
                            "budgetExceeded": bool(budget_exceeded),
                        }
                    )

                conn.execute(
                    """
                    UPDATE recommendation_requests
                    SET status = 'DONE',
                        search_type = 'COMBO',
                        tpo_summary = ?,
                        items_json = '[]',
                        message = ?
                    WHERE request_id = ?
                    """,
                    (tpo_summary, message, request_id),
                )
                conn.commit()
                return saved_combos
            finally:
                self._close_sqlite_if_transient(conn)

    def fail_request(
        self,
        request_id: int,
        message: str,
        tpo_summary: str | None = None,
    ) -> None:
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE recommendation_requests
                            SET status = 'FAILED',
                                tpo_summary = COALESCE(%s, tpo_summary),
                                message = %s
                            WHERE request_id = %s
                            """,
                            (tpo_summary, message, request_id),
                        )
                    conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                conn.execute(
                    """
                    UPDATE recommendation_requests
                    SET status = 'FAILED',
                        tpo_summary = COALESCE(?, tpo_summary),
                        message = ?
                    WHERE request_id = ?
                    """,
                    (tpo_summary, message, request_id),
                )
                conn.commit()
            finally:
                self._close_sqlite_if_transient(conn)

    def get_request(self, request_id: int) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT request_id, user_id, query_text, status, search_type,
                                   tpo_summary, items_json, message, created_at
                            FROM recommendation_requests
                            WHERE request_id = %s
                            """,
                            (request_id,),
                        )
                        row = cur.fetchone()
                        if row is None:
                            return None

                        cur.execute(
                            """
                            SELECT combo_id, total_price, pass_status, harmony_score,
                                   feedback_summary, budget_exceeded, items_json
                            FROM recommendation_combos
                            WHERE request_id = %s
                            ORDER BY rank_order ASC, combo_id ASC
                            """,
                            (request_id,),
                        )
                        combo_rows = cur.fetchall()
            return self._build_request_dict(row, combo_rows)

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                row = conn.execute(
                    """
                    SELECT request_id, user_id, query_text, status, search_type,
                           tpo_summary, items_json, message, created_at
                    FROM recommendation_requests
                    WHERE request_id = ?
                    """,
                    (request_id,),
                ).fetchone()
                if row is None:
                    return None

                combo_rows = conn.execute(
                    """
                    SELECT combo_id, total_price, pass_status, harmony_score,
                           feedback_summary, budget_exceeded, items_json
                    FROM recommendation_combos
                    WHERE request_id = ?
                    ORDER BY rank_order ASC, combo_id ASC
                    """,
                    (request_id,),
                ).fetchall()
                return self._build_request_dict(row, combo_rows)
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _build_request_dict(row: Any, combo_rows: list[Any]) -> dict[str, Any]:
        combos = [
            {
                "comboId": int(c["combo_id"]),
                "items": json.loads(c["items_json"] or "[]"),
                "totalPrice": int(c["total_price"]),
                "passStatus": c["pass_status"],
                "harmonyScore": float(c["harmony_score"]),
                "feedbackSummary": c["feedback_summary"],
                "budgetExceeded": bool(c["budget_exceeded"]),
            }
            for c in combo_rows
        ]
        return {
            "requestId": int(row["request_id"]),
            "userId": int(row["user_id"]),
            "queryText": row["query_text"],
            "status": row["status"],
            "searchType": row["search_type"],
            "tpoSummary": row["tpo_summary"],
            "items": json.loads(row["items_json"] or "[]"),
            "combos": combos,
            "message": row["message"],
            "createdAt": row["created_at"],
        }

    def list_user_requests(
        self,
        user_id: int,
        page: int = 0,
        size: int = 20,
    ) -> dict[str, Any]:
        offset = page * size
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS cnt
                            FROM recommendation_requests
                            WHERE user_id = %s
                            """,
                            (user_id,),
                        )
                        total_row = cur.fetchone()
                        total_count = int(total_row["cnt"]) if total_row else 0
                        total_pages = math.ceil(total_count / size) if size > 0 else 0

                        cur.execute(
                            """
                            SELECT request_id, query_text, tpo_summary, created_at
                            FROM recommendation_requests
                            WHERE user_id = %s
                            ORDER BY request_id DESC
                            LIMIT %s OFFSET %s
                            """,
                            (user_id, size, offset),
                        )
                        rows = cur.fetchall()
            return self._build_page_dict(rows, page, total_pages)

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                total_row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM recommendation_requests
                    WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
                total_count = int(total_row["cnt"]) if total_row else 0
                total_pages = math.ceil(total_count / size) if size > 0 else 0

                rows = conn.execute(
                    """
                    SELECT request_id, query_text, tpo_summary, created_at
                    FROM recommendation_requests
                    WHERE user_id = ?
                    ORDER BY request_id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, size, offset),
                ).fetchall()
                return self._build_page_dict(rows, page, total_pages)
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _build_page_dict(
        rows: list[Any],
        page: int,
        total_pages: int,
    ) -> dict[str, Any]:
        content = [
            {
                "requestId": int(r["request_id"]),
                "queryText": r["query_text"],
                "tpoSummary": r["tpo_summary"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
        return {
            "content": content,
            "page": page,
            "totalPages": total_pages,
        }

    def get_combo(self, combo_id: int) -> dict[str, Any] | None:
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT combo_id, request_id, user_id, total_price,
                                   feedback_summary, items_json
                            FROM recommendation_combos
                            WHERE combo_id = %s
                            """,
                            (combo_id,),
                        )
                        row = cur.fetchone()
            return self._build_combo_dict(row) if row is not None else None

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                row = conn.execute(
                    """
                    SELECT combo_id, request_id, user_id, total_price,
                           feedback_summary, items_json
                    FROM recommendation_combos
                    WHERE combo_id = ?
                    """,
                    (combo_id,),
                ).fetchone()
                return self._build_combo_dict(row) if row is not None else None
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _build_combo_dict(row: Any) -> dict[str, Any]:
        raw_items = json.loads(row["items_json"] or "[]")
        items = [
            {
                "productId": int(item.get("productId") or 0),
                "productName": str(item.get("productName") or ""),
                "price": int(item.get("price") or 0),
                "imageUrl": item.get("imageUrl"),
            }
            for item in raw_items
        ]
        return {
            "comboId": int(row["combo_id"]),
            "requestId": int(row["request_id"]),
            "userId": int(row["user_id"]),
            "items": items,
            "totalPrice": int(row["total_price"]),
            "feedbackSummary": row["feedback_summary"],
        }

    def save_size_feedback(
        self,
        user_id: int,
        product_id: int,
        option_id: int,
        size_feedback: str,
        subcategory: str | None = None,
        fit_type: str | None = None,
        purchased_spec: dict[str, float] | None = None,
    ) -> None:
        now = self._now_iso()
        offset = 0.0
        if size_feedback == "SMALL":
            offset = 1.5
        elif size_feedback == "BIG":
            offset = -1.5

        adjusted_spec = (
            {
                k: round(float(v) + offset, 1)
                for k, v in purchased_spec.items()
                if isinstance(v, (int, float))
            }
            if purchased_spec
            else None
        )

        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO size_feedback_logs (
                                user_id, product_id, option_id, size_feedback, created_at
                            ) VALUES (%s, %s, %s, %s, %s)
                            """,
                            (user_id, product_id, option_id, size_feedback, now),
                        )
                        if subcategory and adjusted_spec:
                            cur.execute(
                                """
                                SELECT preference_spec_json, sample_count
                                FROM user_size_preferences
                                WHERE user_id = %s AND subcategory = %s
                                """,
                                (user_id, subcategory),
                            )
                            existing = cur.fetchone()
                            if existing is None:
                                cur.execute(
                                    """
                                    INSERT INTO user_size_preferences (
                                        user_id, subcategory, fit_type,
                                        preference_spec_json, sample_count, updated_at
                                    ) VALUES (%s, %s, %s, %s, 1, %s)
                                    """,
                                    (
                                        user_id,
                                        subcategory,
                                        fit_type or "",
                                        json.dumps(adjusted_spec, ensure_ascii=False),
                                        now,
                                    ),
                                )
                            else:
                                n, merged = self._merge_preference_spec(
                                    existing, adjusted_spec
                                )
                                cur.execute(
                                    """
                                    UPDATE user_size_preferences
                                    SET fit_type = COALESCE(NULLIF(%s, ''), fit_type),
                                        preference_spec_json = %s,
                                        sample_count = %s,
                                        updated_at = %s
                                    WHERE user_id = %s AND subcategory = %s
                                    """,
                                    (
                                        fit_type or "",
                                        json.dumps(merged, ensure_ascii=False),
                                        n + 1,
                                        now,
                                        user_id,
                                        subcategory,
                                    ),
                                )
                    conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO size_feedback_logs (
                        user_id, product_id, option_id, size_feedback, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, product_id, option_id, size_feedback, now),
                )

                if subcategory and adjusted_spec:
                    existing = conn.execute(
                        """
                        SELECT preference_spec_json, sample_count
                        FROM user_size_preferences
                        WHERE user_id = ? AND subcategory = ?
                        """,
                        (user_id, subcategory),
                    ).fetchone()

                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO user_size_preferences (
                                user_id, subcategory, fit_type,
                                preference_spec_json, sample_count, updated_at
                            ) VALUES (?, ?, ?, ?, 1, ?)
                            """,
                            (
                                user_id,
                                subcategory,
                                fit_type or "",
                                json.dumps(adjusted_spec, ensure_ascii=False),
                                now,
                            ),
                        )
                    else:
                        n, merged_spec = self._merge_preference_spec(
                            existing, adjusted_spec
                        )
                        conn.execute(
                            """
                            UPDATE user_size_preferences
                            SET fit_type = COALESCE(NULLIF(?, ''), fit_type),
                                preference_spec_json = ?,
                                sample_count = ?,
                                updated_at = ?
                            WHERE user_id = ? AND subcategory = ?
                            """,
                            (
                                fit_type or "",
                                json.dumps(merged_spec, ensure_ascii=False),
                                n + 1,
                                now,
                                user_id,
                                subcategory,
                            ),
                        )
                conn.commit()
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _merge_preference_spec(
        existing: Any,
        adjusted_spec: dict[str, float],
    ) -> tuple[int, dict[str, float]]:
        n = int(existing["sample_count"])
        prev_spec = json.loads(existing["preference_spec_json"] or "{}")
        merged_spec: dict[str, float] = dict(prev_spec)
        for key, val in adjusted_spec.items():
            if key in prev_spec and isinstance(prev_spec[key], (int, float)):
                merged_spec[key] = round(
                    (float(prev_spec[key]) * n + val) / (n + 1), 1
                )
            else:
                merged_spec[key] = val
        return n, merged_spec

    def get_user_size_preference(
        self,
        user_id: int,
        subcategory: str,
    ) -> dict[str, float] | None:
        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT preference_spec_json
                            FROM user_size_preferences
                            WHERE user_id = %s AND subcategory = %s
                            """,
                            (user_id, subcategory),
                        )
                        row = cur.fetchone()
            if row is None:
                return None
            return json.loads(row["preference_spec_json"] or "{}")

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                row = conn.execute(
                    """
                    SELECT preference_spec_json
                    FROM user_size_preferences
                    WHERE user_id = ? AND subcategory = ?
                    """,
                    (user_id, subcategory),
                ).fetchone()
                if row is None:
                    return None
                return json.loads(row["preference_spec_json"] or "{}")
            finally:
                self._close_sqlite_if_transient(conn)
