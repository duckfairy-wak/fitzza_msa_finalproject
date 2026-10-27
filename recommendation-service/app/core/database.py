import json
import logging
import math
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


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
                                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                                completion_tokens INTEGER NOT NULL DEFAULT 0,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );

                            CREATE INDEX IF NOT EXISTS idx_rec_requests_user_created
                                ON {schema}.recommendation_requests (user_id, request_id DESC);
                            CREATE INDEX IF NOT EXISTS idx_rec_requests_status_created
                                ON {schema}.recommendation_requests (status, created_at DESC);

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
                                items_json TEXT NOT NULL DEFAULT '[]',
                                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );

                            CREATE INDEX IF NOT EXISTS idx_rec_combos_request
                                ON {schema}.recommendation_combos (request_id, rank_order ASC);

                            CREATE TABLE IF NOT EXISTS {schema}.user_size_preferences (
                                user_id BIGINT NOT NULL,
                                subcategory VARCHAR(100) NOT NULL,
                                fit_type VARCHAR(50) NOT NULL DEFAULT '',
                                preference_spec_json TEXT NOT NULL,
                                sample_count INTEGER NOT NULL DEFAULT 1,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (user_id, subcategory)
                            );

                            CREATE TABLE IF NOT EXISTS {schema}.size_feedback_logs (
                                feedback_id BIGSERIAL PRIMARY KEY,
                                user_id BIGINT NOT NULL,
                                product_id BIGINT NOT NULL,
                                option_id BIGINT NOT NULL,
                                size_feedback VARCHAR(16) NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );

                            DO $$
                            BEGIN
                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'recommendation_requests'
                                      AND column_name = 'created_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.recommendation_requests
                                        ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
                                        ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;

                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'recommendation_combos'
                                      AND column_name = 'created_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.recommendation_combos
                                        ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
                                        ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;

                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'user_size_preferences'
                                      AND column_name = 'updated_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.user_size_preferences
                                        ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::timestamptz,
                                        ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;

                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'size_feedback_logs'
                                      AND column_name = 'created_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.size_feedback_logs
                                        ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
                                        ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;

                                IF NOT EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'recommendation_requests'
                                      AND column_name = 'prompt_tokens'
                                ) THEN
                                    ALTER TABLE {schema}.recommendation_requests
                                        ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0;
                                END IF;

                                IF NOT EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'recommendation_requests'
                                      AND column_name = 'completion_tokens'
                                ) THEN
                                    ALTER TABLE {schema}.recommendation_requests
                                        ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0;
                                END IF;
                            END $$;
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
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_recommendation_requests_user_created
                        ON recommendation_requests (user_id, request_id DESC);
                    CREATE INDEX IF NOT EXISTS idx_rec_requests_status_created
                        ON recommendation_requests (status, created_at DESC);

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
                # SQLite 마이그레이션: 기존 파일 DB에 새 컬럼이 없을 경우 추가
                columns = [
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(recommendation_requests)"
                    ).fetchall()
                ]
                if "prompt_tokens" not in columns:
                    conn.execute(
                        "ALTER TABLE recommendation_requests ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                if "completion_tokens" not in columns:
                    conn.execute(
                        "ALTER TABLE recommendation_requests ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                conn.commit()
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _format_utc_timestamp(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, datetime):
            if val.tzinfo is None:
                val = val.replace(tzinfo=timezone.utc)
            else:
                val = val.astimezone(timezone.utc)
            return val.strftime("%Y-%m-%dT%H:%M:%SZ")
        s = str(val).strip()
        if not s:
            return ""
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return s

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
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
                                message = %s,
                                prompt_tokens = %s,
                                completion_tokens = %s
                            WHERE request_id = %s
                            """,
                            (tpo_summary, items_str, message, prompt_tokens, completion_tokens, request_id),
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
                        message = ?,
                        prompt_tokens = ?,
                        completion_tokens = ?
                    WHERE request_id = ?
                    """,
                    (tpo_summary, items_str, message, prompt_tokens, completion_tokens, request_id),
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
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
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
                                message = %s,
                                prompt_tokens = %s,
                                completion_tokens = %s
                            WHERE request_id = %s
                            """,
                            (tpo_summary, message, prompt_tokens, completion_tokens, request_id),
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
                        message = ?,
                        prompt_tokens = ?,
                        completion_tokens = ?
                    WHERE request_id = ?
                    """,
                    (tpo_summary, message, prompt_tokens, completion_tokens, request_id),
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
                                   tpo_summary, items_json, message, prompt_tokens,
                                   completion_tokens, created_at
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
                           tpo_summary, items_json, message, prompt_tokens,
                           completion_tokens, created_at
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
            "promptTokens": int(row.get("prompt_tokens", 0) if hasattr(row, "get") else row["prompt_tokens"] if "prompt_tokens" in row.keys() else 0),
            "completionTokens": int(row.get("completion_tokens", 0) if hasattr(row, "get") else row["completion_tokens"] if "completion_tokens" in row.keys() else 0),
            "createdAt": RecommendationRepository._format_utc_timestamp(row["created_at"]),
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
            return self._build_page_dict(rows, page, total_pages, total_count=total_count, size=size)

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
                return self._build_page_dict(rows, page, total_pages, total_count=total_count, size=size)
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _build_page_dict(
        rows: list[Any],
        page: int,
        total_pages: int,
        total_count: int = 0,
        size: int = 20,
    ) -> dict[str, Any]:
        content = [
            {
                "requestId": int(r["request_id"]),
                "queryText": r["query_text"],
                "tpoSummary": r["tpo_summary"],
                "createdAt": RecommendationRepository._format_utc_timestamp(r["created_at"]),
            }
            for r in rows
        ]
        has_next = (page + 1) < total_pages
        return {
            "content": content,
            "page": page,
            "size": size,
            "totalElements": total_count,
            "totalPages": total_pages,
            "hasNext": has_next,
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

    def get_analytics_data(
        self,
        reference_dt: datetime | None = None,
        vton_client: Any | None = None,
    ) -> dict[str, Any]:
        """일간/주간/월간/연간 토큰 사용량, 인기 키워드, 추천 상품 통계를 한국 시간(KST) 현재 날짜 기준으로 집계하여 반환합니다."""
        if reference_dt is None:
            now = datetime.now(KST)
        elif reference_dt.tzinfo is None:
            now = reference_dt.replace(tzinfo=KST)
        else:
            now = reference_dt.astimezone(KST)

        # 1. 일간 (오늘 00:00:00 ~ 오늘 23:59:59.999999 KST)
        daily_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_end = daily_start + timedelta(days=1) - timedelta(microseconds=1)

        # 2. 주간 (이번 주 월요일 00:00:00 ~ 현재 날짜 23:59:59.999999 KST)
        weekly_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        weekly_end = daily_end

        # 3. 월간 (이번 달 1일 00:00:00 ~ 현재 날짜 23:59:59.999999 KST)
        monthly_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_end = daily_end

        # 4. 연간 (올해 1월 1일 00:00:00 ~ 현재 날짜 23:59:59.999999 KST)
        yearly_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        yearly_end = daily_end

        daily_data = self._aggregate_period_analytics("daily", "일간", daily_start, daily_end, vton_client=vton_client)
        weekly_data = self._aggregate_period_analytics("weekly", "주간", weekly_start, weekly_end, vton_client=vton_client)
        monthly_data = self._aggregate_period_analytics("monthly", "월간", monthly_start, monthly_end, vton_client=vton_client)
        yearly_data = self._aggregate_period_analytics("yearly", "연간", yearly_start, yearly_end, vton_client=vton_client)

        return {
            "daily": daily_data,
            "weekly": weekly_data,
            "monthly": monthly_data,
            "yearly": yearly_data,
        }

    def _get_requests_in_range(
        self,
        start_dt: datetime,
        end_dt: datetime,
        limit: int = 3000,
    ) -> list[dict[str, Any]]:
        """지정된 기간 동안 완료(DONE)된 추천 요청 및 코디 상품 데이터를 조회합니다 (최대 limit건)."""
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
        start_iso = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        if self._use_postgres:
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT r.request_id, r.query_text, r.search_type, r.tpo_summary,
                                   r.items_json, r.prompt_tokens, r.completion_tokens, r.created_at,
                                   COALESCE(
                                       json_agg(c.items_json) FILTER (WHERE c.combo_id IS NOT NULL),
                                       '[]'::json
                                   ) AS combo_items_json
                            FROM recommendation_requests r
                            LEFT JOIN recommendation_combos c ON r.request_id = c.request_id
                            WHERE r.created_at >= %s AND r.created_at <= %s
                              AND r.status = 'DONE'
                            GROUP BY r.request_id
                            ORDER BY r.created_at DESC
                            LIMIT %s
                            """,
                            (start_utc, end_utc, limit),
                        )
                        rows = cur.fetchall()
            return [dict(r) for r in reversed(rows)]

        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT request_id, query_text, search_type, tpo_summary,
                           items_json, prompt_tokens, completion_tokens, created_at
                    FROM recommendation_requests
                    WHERE created_at >= ? AND created_at <= ?
                      AND status = 'DONE'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (start_iso, end_iso, limit),
                ).fetchall()
                results = []
                for r in reversed(rows):
                    req_dict = dict(r)
                    req_id = req_dict["request_id"]
                    c_rows = conn.execute(
                        "SELECT items_json FROM recommendation_combos WHERE request_id = ?",
                        (req_id,),
                    ).fetchall()
                    req_dict["combo_items_json"] = [cr["items_json"] for cr in c_rows]
                    results.append(req_dict)
                return results
            finally:
                self._close_sqlite_if_transient(conn)

    def _get_vton_tokens_in_range(
        self,
        start_dt: datetime,
        end_dt: datetime,
        vton_client: Any | None = None,
        limit: int = 3000,
    ) -> list[dict[str, Any]]:
        """지정된 기간 동안 완료(COMPLETED)된 가상 피팅(VTON) 요청의 OpenAI 토큰 사용량을 조회합니다 (최대 limit건)."""
        start_utc = start_dt.astimezone(timezone.utc)
        end_utc = end_dt.astimezone(timezone.utc)
        start_iso = start_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        # 1. MSA 내부 통신 API 우선 호출 (vton-service HTTP 클라이언트)
        if vton_client is not None and getattr(vton_client, "is_configured", False):
            try:
                records = vton_client.get_token_usage_in_range(start_iso=start_iso, end_iso=end_iso)
                if records:
                    return [
                        {
                            "prompt_tokens": int(r.get("promptTokens") or r.get("prompt_tokens") or 0),
                            "completion_tokens": int(r.get("completionTokens") or r.get("completion_tokens") or 0),
                            "created_at": r.get("createdAt") or r.get("created_at"),
                        }
                        for r in records
                    ]
            except Exception as exc:
                logger.warning("VTON 토큰 사용량 내부 통신 실패: %s: %s", type(exc).__name__, exc)

        # 2. PostgreSQL 운영 환경에서는 SQLite 폴백을 타지 않고 즉시 반환
        if self._use_postgres:
            return []

        # 3. 로컬 개발/테스트용 SQLite 또는 단일 DB 폴백
        with self._lock:
            conn = self._get_sqlite_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT prompt_tokens, completion_tokens, created_at
                    FROM fittings
                    WHERE created_at >= ? AND created_at <= ?
                      AND status = 'COMPLETED'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (start_iso, end_iso, limit),
                ).fetchall()
                return [dict(r) for r in reversed(rows)]
            except Exception:
                return []
            finally:
                self._close_sqlite_if_transient(conn)

    @staticmethod
    def _parse_record_kst_datetime(created_at_raw: Any, fallback_dt: datetime) -> datetime:
        if isinstance(created_at_raw, datetime):
            if created_at_raw.tzinfo is None:
                return created_at_raw.replace(tzinfo=timezone.utc).astimezone(KST)
            return created_at_raw.astimezone(KST)
        if created_at_raw:
            dt = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(KST)
        return fallback_dt

    def _aggregate_period_analytics(
        self,
        period: str,
        label: str,
        start_dt: datetime,
        end_dt: datetime,
        vton_client: Any | None = None,
    ) -> dict[str, Any]:
        records = self._get_requests_in_range(start_dt, end_dt)
        vton_records = self._get_vton_tokens_in_range(start_dt, end_dt, vton_client=vton_client)

        # 1. 토큰 사용량 집계 (슬롯 레이블 초기화)
        usage_buckets = self._init_usage_buckets(period, start_dt, end_dt)
        keyword_counts: Counter[str] = Counter()
        product_counts: dict[tuple[str, str], int] = Counter()

        for rec in records:
            rec_dt = self._parse_record_kst_datetime(rec.get("created_at"), start_dt)

            bucket_key = self._get_bucket_key(period, rec_dt, start_dt)
            p_tokens = int(rec.get("prompt_tokens") or 0)
            c_tokens = int(rec.get("completion_tokens") or 0)

            if bucket_key in usage_buckets:
                usage_buckets[bucket_key]["input"] += p_tokens
                usage_buckets[bucket_key]["output"] += c_tokens

            # 키워드 집계 (tpo_summary 및 query_text 파싱)
            extracted_keywords = self._extract_keywords(rec.get("tpo_summary"), rec.get("query_text"))
            for kw in extracted_keywords:
                keyword_counts[kw] += 1

            # 상품 집계
            items_to_count = []
            single_items_raw = rec.get("items_json")
            if single_items_raw:
                try:
                    loaded = json.loads(single_items_raw) if isinstance(single_items_raw, str) else single_items_raw
                    if isinstance(loaded, list):
                        items_to_count.extend(loaded)
                except Exception:
                    pass

            combos_raw = rec.get("combo_items_json")
            if combos_raw:
                for c_item in combos_raw:
                    try:
                        c_loaded = json.loads(c_item) if isinstance(c_item, str) else c_item
                        if isinstance(c_loaded, list):
                            items_to_count.extend(c_loaded)
                    except Exception:
                        pass

            for it in items_to_count:
                if not isinstance(it, dict):
                    continue
                p_name = it.get("productName") or it.get("product_name") or ""
                p_brand = it.get("brandName") or it.get("brand_name") or ""
                if p_name:
                    product_counts[(p_name, p_brand)] += 1

        # 2. 가상 피팅(VTON) OpenAI 토큰 합산
        for v_rec in vton_records:
            v_dt = self._parse_record_kst_datetime(v_rec.get("created_at"), start_dt)
            bucket_key = self._get_bucket_key(period, v_dt, start_dt)
            vp_tokens = int(v_rec.get("prompt_tokens") or 0)
            vc_tokens = int(v_rec.get("completion_tokens") or 0)
            if bucket_key in usage_buckets:
                usage_buckets[bucket_key]["input"] += vp_tokens
                usage_buckets[bucket_key]["output"] += vc_tokens

        usage_list = [
            {"label": val["label"], "input": val["input"], "output": val["output"]}
            for val in usage_buckets.values()
        ]

        keywords_list = [
            {"name": name, "count": count}
            for name, count in keyword_counts.most_common(10)
        ]

        products_list = [
            {"name": name, "brand": brand, "count": count}
            for (name, brand), count in sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        return {
            "label": label,
            "startDate": start_dt.strftime("%Y-%m-%d"),
            "endDate": end_dt.strftime("%Y-%m-%d"),
            "usage": usage_list,
            "keywords": keywords_list,
            "products": products_list,
        }

    @staticmethod
    def _calendar_week_of_month(dt: datetime) -> int:
        """달력 기준(월~일 한 주)으로 해당 날짜가 몇 주차인지 계산합니다."""
        first_day = dt.replace(day=1)
        return ((dt.day + first_day.weekday() - 1) // 7) + 1

    @classmethod
    def _init_usage_buckets(cls, period: str, start_dt: datetime, end_dt: datetime) -> dict[str, dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        if period == "daily":
            for h in (0, 4, 8, 12, 16, 20):
                label = f"{h:02d}시"
                buckets[label] = {"label": label, "input": 0, "output": 0}
        elif period == "weekly":
            day_labels = ["월", "화", "수", "목", "금", "토", "일"]
            max_weekday = end_dt.weekday()
            for d in day_labels[: max_weekday + 1]:
                buckets[d] = {"label": d, "input": 0, "output": 0}
        elif period == "monthly":
            max_week = cls._calendar_week_of_month(end_dt)
            for w in range(1, max_week + 1):
                label = f"{w}주"
                buckets[label] = {"label": label, "input": 0, "output": 0}
        elif period == "yearly":
            max_month = end_dt.month
            for m in range(1, max_month + 1):
                label = f"{m}월"
                buckets[label] = {"label": label, "input": 0, "output": 0}
        return buckets

    @classmethod
    def _get_bucket_key(cls, period: str, rec_dt: datetime, start_dt: datetime) -> str:
        if period == "daily":
            h = rec_dt.hour
            slot_h = (h // 4) * 4
            return f"{slot_h:02d}시"
        if period == "weekly":
            day_labels = ["월", "화", "수", "목", "금", "토", "일"]
            return day_labels[rec_dt.weekday()]
        if period == "monthly":
            week_idx = cls._calendar_week_of_month(rec_dt)
            return f"{week_idx}주"
        if period == "yearly":
            return f"{rec_dt.month}월"
        return ""

    @staticmethod
    def _extract_keywords(tpo_summary: str | None, query_text: str | None) -> list[str]:
        target_text = f"{tpo_summary or ''} {query_text or ''}"
        standard_keywords = [
            "출근룩", "미니멀", "캐주얼", "가을 코디", "데이트룩",
            "오버핏", "스트릿", "하객룩", "여행룩", "포멀", "댄디",
            "와이드", "스포티", "빈티지", "시티보이", "겨울 코디", "봄 코디", "여름 코디"
        ]
        found = []
        for kw in standard_keywords:
            if kw in target_text:
                found.append(kw)
        if not found and tpo_summary:
            words = [w.strip() for w in re.split(r"[,\s]+", tpo_summary) if len(w.strip()) >= 2]
            found.extend(words[:3])
        return found

