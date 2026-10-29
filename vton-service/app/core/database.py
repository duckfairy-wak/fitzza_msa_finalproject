"""vton-service DB 영속성 및 저장소 레이어 (PostgreSQL vton 스키마 + SQLite 로컬 폴백)."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _validate_identifier(identifier: str) -> str:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(f"유효하지 않은 SQL 식별자입니다: {identifier}")
    return identifier


class VtonRepository:
    def __init__(
        self,
        db_path: str = ":memory:",
        postgres_dsn: str | None = None,
        postgres_schema: str = "vton",
    ) -> None:
        self.db_path = db_path
        self.postgres_dsn = (postgres_dsn or "").strip() or None
        self.postgres_schema = _validate_identifier(postgres_schema or "vton")
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
                            CREATE TABLE IF NOT EXISTS {schema}.fittings (
                                fitting_id BIGSERIAL PRIMARY KEY,
                                user_id BIGINT NOT NULL,
                                photo_id BIGINT,
                                request_id BIGINT,
                                status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                                result_image_url TEXT,
                                error_message TEXT,
                                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                                completion_tokens INTEGER NOT NULL DEFAULT 0,
                                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );
                            DO $$
                            BEGIN
                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'fittings'
                                      AND column_name = 'created_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.fittings
                                        ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
                                        ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;

                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'fittings'
                                      AND column_name = 'updated_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.fittings
                                        ALTER COLUMN updated_at TYPE TIMESTAMPTZ USING updated_at::timestamptz,
                                        ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;
                            END $$;
                            ALTER TABLE {schema}.fittings ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
                            ALTER TABLE {schema}.fittings ADD COLUMN IF NOT EXISTS request_id BIGINT;
                            ALTER TABLE {schema}.fittings ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER NOT NULL DEFAULT 0;
                            ALTER TABLE {schema}.fittings ADD COLUMN IF NOT EXISTS completion_tokens INTEGER NOT NULL DEFAULT 0;
                            ALTER TABLE {schema}.fittings ADD COLUMN IF NOT EXISTS warnings TEXT;

                            CREATE INDEX IF NOT EXISTS idx_fittings_user_created
                                ON {schema}.fittings (user_id, fitting_id DESC);
                            CREATE INDEX IF NOT EXISTS idx_fittings_status_created
                                ON {schema}.fittings (status, created_at DESC);

                            CREATE TABLE IF NOT EXISTS {schema}.fitting_products (
                                id BIGSERIAL PRIMARY KEY,
                                fitting_id BIGINT NOT NULL
                                    REFERENCES {schema}.fittings(fitting_id) ON DELETE CASCADE,
                                product_id BIGINT NOT NULL,
                                product_name TEXT NOT NULL,
                                price INTEGER NOT NULL DEFAULT 0,
                                image_url TEXT NOT NULL DEFAULT '',
                                category_name VARCHAR(64) NOT NULL DEFAULT ''
                            );
                            CREATE INDEX IF NOT EXISTS idx_fitting_products_fitting
                                ON {schema}.fitting_products (fitting_id);

                            CREATE TABLE IF NOT EXISTS {schema}.user_photos (
                                photo_id BIGSERIAL PRIMARY KEY,
                                user_id BIGINT NOT NULL,
                                file_path TEXT NOT NULL,
                                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                            );

                            DO $$
                            BEGIN
                                IF EXISTS (
                                    SELECT 1 FROM information_schema.columns
                                    WHERE table_schema = '{schema}'
                                      AND table_name = 'user_photos'
                                      AND column_name = 'created_at'
                                      AND data_type IN ('text', 'character varying')
                                ) THEN
                                    ALTER TABLE {schema}.user_photos
                                        ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz,
                                        ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP;
                                END IF;
                            END $$;
                            CREATE INDEX IF NOT EXISTS idx_user_photos_user
                                ON {schema}.user_photos (user_id, photo_id DESC);
                            """
                        )
                        conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS fittings (
                            fitting_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            photo_id INTEGER,
                            request_id INTEGER,
                            status TEXT NOT NULL DEFAULT 'PENDING',
                            result_image_url TEXT,
                            error_message TEXT,
                            prompt_tokens INTEGER NOT NULL DEFAULT 0,
                            completion_tokens INTEGER NOT NULL DEFAULT 0,
                            is_deleted INTEGER NOT NULL DEFAULT 0,
                            warnings TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        """
                    )
                    # 기존 SQLite 테이블에 컬럼 누락 시 보완
                    cur.execute("PRAGMA table_info(fittings);")
                    columns = [row[1] for row in cur.fetchall()]
                    if "is_deleted" not in columns:
                        cur.execute("ALTER TABLE fittings ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0;")
                    if "request_id" not in columns:
                        cur.execute("ALTER TABLE fittings ADD COLUMN request_id INTEGER;")
                    if "prompt_tokens" not in columns:
                        cur.execute("ALTER TABLE fittings ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0;")
                    if "completion_tokens" not in columns:
                        cur.execute("ALTER TABLE fittings ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0;")
                    if "warnings" not in columns:
                        cur.execute("ALTER TABLE fittings ADD COLUMN warnings TEXT;")

                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_fittings_user_created
                            ON fittings (user_id, fitting_id DESC);
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_fittings_status_created
                            ON fittings (status, created_at DESC);
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS fitting_products (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            fitting_id INTEGER NOT NULL,
                            product_id INTEGER NOT NULL,
                            product_name TEXT NOT NULL,
                            price INTEGER NOT NULL DEFAULT 0,
                            image_url TEXT NOT NULL DEFAULT '',
                            category_name TEXT NOT NULL DEFAULT '',
                            FOREIGN KEY (fitting_id) REFERENCES fittings (fitting_id) ON DELETE CASCADE
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_fitting_products_fitting
                            ON fitting_products (fitting_id);
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS user_photos (
                            photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            file_path TEXT NOT NULL,
                            is_deleted INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT NOT NULL
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_user_photos_user
                            ON user_photos (user_id, photo_id DESC);
                        """
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

    def create_fitting(
        self,
        user_id: int,
        photo_id: int | None,
        product_ids: list[int],
        request_id: int | None = None,
    ) -> int:
        now = self._now_iso()
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {schema}.fittings (
                                user_id, photo_id, request_id, status, created_at, updated_at
                            ) VALUES (%s, %s, %s, 'PENDING', %s, %s)
                            RETURNING fitting_id;
                            """,
                            (user_id, photo_id, request_id, now, now),
                        )
                        fitting_id = int(cur.fetchone()["fitting_id"])
                        conn.commit()
                        return fitting_id
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO fittings (
                            user_id, photo_id, request_id, status, created_at, updated_at
                        ) VALUES (?, ?, ?, 'PENDING', ?, ?);
                        """,
                        (user_id, photo_id, request_id, now, now),
                    )
                    fitting_id = int(cur.lastrowid)
                    conn.commit()
                    return fitting_id
                finally:
                    self._close_sqlite_if_transient(conn)

    def save_fitting_products(
        self,
        fitting_id: int,
        products: list[dict[str, Any]],
    ) -> None:
        if not products:
            return
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"DELETE FROM {schema}.fitting_products WHERE fitting_id = %s;",
                            (fitting_id,),
                        )
                        for p in products:
                            cur.execute(
                                f"""
                                INSERT INTO {schema}.fitting_products (
                                    fitting_id, product_id, product_name, price, image_url, category_name
                                ) VALUES (%s, %s, %s, %s, %s, %s);
                                """,
                                (
                                    fitting_id,
                                    int(p["productId"]),
                                    str(p.get("productName", "")),
                                    int(p.get("price", 0)),
                                    str(p.get("imageUrl", "")),
                                    str(p.get("categoryName", "")),
                                ),
                            )
                        conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "DELETE FROM fitting_products WHERE fitting_id = ?;",
                        (fitting_id,),
                    )
                    for p in products:
                        cur.execute(
                            """
                            INSERT INTO fitting_products (
                                fitting_id, product_id, product_name, price, image_url, category_name
                            ) VALUES (?, ?, ?, ?, ?, ?);
                            """,
                            (
                                fitting_id,
                                int(p["productId"]),
                                str(p.get("productName", "")),
                                int(p.get("price", 0)),
                                str(p.get("imageUrl", "")),
                                str(p.get("categoryName", "")),
                            ),
                        )
                    conn.commit()
                finally:
                    self._close_sqlite_if_transient(conn)

    def mark_completed(
        self,
        fitting_id: int,
        result_image_url: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        warnings: list[str] | None = None,
    ) -> None:
        now = self._now_iso()
        warnings_json = json.dumps(warnings, ensure_ascii=False) if warnings else None
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            UPDATE {schema}.fittings
                            SET status = 'COMPLETED',
                                result_image_url = %s,
                                prompt_tokens = %s,
                                completion_tokens = %s,
                                warnings = %s,
                                updated_at = %s
                            WHERE fitting_id = %s;
                            """,
                            (result_image_url, prompt_tokens, completion_tokens, warnings_json, now, fitting_id),
                        )
                        conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE fittings
                        SET status = 'COMPLETED',
                            result_image_url = ?,
                            prompt_tokens = ?,
                            completion_tokens = ?,
                            warnings = ?,
                            updated_at = ?
                        WHERE fitting_id = ?;
                        """,
                        (result_image_url, prompt_tokens, completion_tokens, warnings_json, now, fitting_id),
                    )
                    conn.commit()
                finally:
                    self._close_sqlite_if_transient(conn)

    def update_fitting_failed(
        self,
        fitting_id: int,
        error_message: str,
    ) -> None:
        self.mark_failed(fitting_id=fitting_id, error_message=error_message)

    def mark_failed(
        self,
        fitting_id: int,
        error_message: str,
    ) -> None:
        now = self._now_iso()
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            UPDATE {schema}.fittings
                            SET status = 'FAILED',
                                error_message = %s,
                                updated_at = %s
                            WHERE fitting_id = %s;
                            """,
                            (error_message[:1000], now, fitting_id),
                        )
                        conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE fittings
                        SET status = 'FAILED',
                            error_message = ?,
                            updated_at = ?
                        WHERE fitting_id = ?;
                        """,
                        (error_message[:1000], now, fitting_id),
                    )
                    conn.commit()
                finally:
                    self._close_sqlite_if_transient(conn)

    def delete_fitting(self, fitting_id: int, user_id: int) -> bool:
        """
        [소프트 삭제] 본인의 가상 피팅 기록을 is_deleted = TRUE로 마킹합니다.
        성공 시 True, 이미 삭제되었거나 대상이 없으면 False를 반환합니다.
        """
        now = self._now_iso()
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            UPDATE {schema}.fittings
                            SET is_deleted = TRUE,
                                updated_at = %s
                            WHERE fitting_id = %s
                              AND user_id = %s
                              AND is_deleted = FALSE;
                            """,
                            (now, fitting_id, user_id),
                        )
                        rowcount = cur.rowcount
                        conn.commit()
                        return rowcount > 0
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE fittings
                        SET is_deleted = 1,
                            updated_at = ?
                        WHERE fitting_id = ?
                          AND user_id = ?
                          AND is_deleted = 0;
                        """,
                        (now, fitting_id, user_id),
                    )
                    rowcount = cur.rowcount
                    conn.commit()
                    return rowcount > 0
                finally:
                    self._close_sqlite_if_transient(conn)

    def get_fitting_detail(
        self,
        fitting_id: int,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        query = f"""
                            SELECT fitting_id, user_id, photo_id, request_id, status,
                                   result_image_url, error_message, prompt_tokens, completion_tokens,
                                   is_deleted, warnings, created_at, updated_at
                            FROM {schema}.fittings
                            WHERE fitting_id = %s
                        """
                        if not include_deleted:
                            query += " AND is_deleted = FALSE"
                        cur.execute(query + ";", (fitting_id,))
                        fitting_row = cur.fetchone()
                        if not fitting_row:
                            return None

                        cur.execute(
                            f"""
                            SELECT product_id, product_name, price, image_url, category_name
                            FROM {schema}.fitting_products
                            WHERE fitting_id = %s
                            ORDER BY id ASC;
                            """,
                            (fitting_id,),
                        )
                        product_rows = cur.fetchall() or []
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    query = """
                        SELECT fitting_id, user_id, photo_id, request_id, status,
                               result_image_url, error_message, prompt_tokens, completion_tokens,
                               is_deleted, warnings, created_at, updated_at
                        FROM fittings
                        WHERE fitting_id = ?
                    """
                    if not include_deleted:
                        query += " AND is_deleted = 0"
                    cur.execute(query + ";", (fitting_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    fitting_row = dict(row)

                    cur.execute(
                        """
                        SELECT product_id, product_name, price, image_url, category_name
                        FROM fitting_products
                        WHERE fitting_id = ?
                        ORDER BY id ASC;
                        """,
                        (fitting_id,),
                    )
                    product_rows = [dict(r) for r in cur.fetchall()]
                finally:
                    self._close_sqlite_if_transient(conn)

        products = [
            {
                "productId": int(r["product_id"]),
                "productName": r["product_name"],
                "price": int(r["price"]),
                "imageUrl": r["image_url"],
                "categoryName": r["category_name"],
            }
            for r in product_rows
        ]

        raw_warnings = fitting_row.get("warnings")
        parsed_warnings: list[str] = []
        if raw_warnings:
            try:
                parsed = json.loads(raw_warnings)
                if isinstance(parsed, list):
                    parsed_warnings = [str(x) for x in parsed]
            except Exception:
                pass

        return {
            "fittingId": int(fitting_row["fitting_id"]),
            "userId": int(fitting_row["user_id"]),
            "photoId": fitting_row["photo_id"],
            "requestId": int(fitting_row["request_id"]) if fitting_row.get("request_id") is not None else None,
            "status": fitting_row["status"],
            "resultImageUrl": fitting_row["result_image_url"],
            "errorMessage": fitting_row["error_message"],
            "warnings": parsed_warnings,
            "promptTokens": int(fitting_row.get("prompt_tokens") or 0),
            "completionTokens": int(fitting_row.get("completion_tokens") or 0),
            "isDeleted": bool(fitting_row.get("is_deleted", False)),
            "products": products,
            "createdAt": self._format_utc_timestamp(fitting_row["created_at"]),
            "updatedAt": self._format_utc_timestamp(fitting_row["updated_at"]),
        }

    def save_user_photo(self, user_id: int, file_path: str) -> dict[str, Any]:
        """사용자가 업로드한 전신 사진 메타데이터를 저장하고 사진 정보 딕셔너리를 반환합니다."""
        now = self._now_iso()
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            INSERT INTO {schema}.user_photos (user_id, file_path, is_deleted, created_at)
                            VALUES (%s, %s, FALSE, %s)
                            RETURNING photo_id, created_at;
                            """,
                            (user_id, file_path, now),
                        )
                        row = cur.fetchone()
                        conn.commit()
                        return {
                            "photoId": int(row["photo_id"]),
                            "userId": user_id,
                            "filePath": file_path,
                            "createdAt": self._format_utc_timestamp(row["created_at"]),
                        }
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO user_photos (user_id, file_path, is_deleted, created_at)
                        VALUES (?, ?, 0, ?);
                        """,
                        (user_id, file_path, now),
                    )
                    photo_id = int(cur.lastrowid)
                    conn.commit()
                    return {
                        "photoId": photo_id,
                        "userId": user_id,
                        "filePath": file_path,
                        "createdAt": self._format_utc_timestamp(now),
                    }
                finally:
                    self._close_sqlite_if_transient(conn)

    def get_user_photo(self, photo_id: int) -> dict[str, Any] | None:
        """photo_id로 활성 상태의 사용자 사진 정보를 조회합니다."""
        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT photo_id, user_id, file_path, created_at
                            FROM {schema}.user_photos
                            WHERE photo_id = %s AND is_deleted = FALSE;
                            """,
                            (photo_id,),
                        )
                        row = cur.fetchone()
                        if not row:
                            return None
                        return {
                            "photoId": int(row["photo_id"]),
                            "userId": int(row["user_id"]),
                            "filePath": str(row["file_path"]),
                            "createdAt": self._format_utc_timestamp(row["created_at"]),
                        }
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT photo_id, user_id, file_path, created_at
                        FROM user_photos
                        WHERE photo_id = ? AND is_deleted = 0;
                        """,
                        (photo_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    return {
                        "photoId": int(row["photo_id"]),
                        "userId": int(row["user_id"]),
                        "filePath": str(row["file_path"]),
                        "createdAt": self._format_utc_timestamp(row["created_at"]),
                    }
                finally:
                    self._close_sqlite_if_transient(conn)

    def get_user_fittings(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        request_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """사용자의 활성(삭제되지 않은) 피팅 목록을 최신순으로 조회하고 전체 건수와 함께 반환합니다."""
        items: list[dict[str, Any]] = []
        total_count = 0

        if self._use_postgres:
            schema = self.postgres_schema
            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        where_clauses = ["user_id = %s", "is_deleted = FALSE"]
                        params: list[Any] = [user_id]
                        if request_id is not None:
                            where_clauses.append("request_id = %s")
                            params.append(request_id)
                        where_sql = " AND ".join(where_clauses)

                        # 전체 건수
                        cur.execute(
                            f"""
                            SELECT COUNT(*) AS total_count
                            FROM {schema}.fittings
                            WHERE {where_sql};
                            """,
                            tuple(params),
                        )
                        count_row = cur.fetchone()
                        if count_row:
                            total_count = int(
                                count_row["total_count"]
                                if isinstance(count_row, dict) or hasattr(count_row, "__getitem__") and "total_count" in count_row
                                else count_row[0]
                            )
                        else:
                            total_count = 0

                        if total_count == 0:
                            return [], 0

                        # 목록 조회
                        query_params = list(params) + [limit, offset]
                        cur.execute(
                            f"""
                            SELECT fitting_id, user_id, photo_id, request_id, status,
                                   result_image_url, error_message, created_at, updated_at
                            FROM {schema}.fittings
                            WHERE {where_sql}
                            ORDER BY fitting_id DESC
                            LIMIT %s OFFSET %s;
                            """,
                            tuple(query_params),
                        )
                        rows = cur.fetchall() or []
                        fitting_ids = [int(r["fitting_id"]) for r in rows]

                        # 상품 목록 매핑
                        product_map: dict[int, list[dict[str, Any]]] = {fid: [] for fid in fitting_ids}
                        if fitting_ids:
                            placeholders = ",".join(["%s"] * len(fitting_ids))
                            cur.execute(
                                f"""
                                SELECT fitting_id, product_id, product_name, price, image_url, category_name
                                FROM {schema}.fitting_products
                                WHERE fitting_id IN ({placeholders})
                                ORDER BY id ASC;
                                """,
                                fitting_ids,
                            )
                            for pr in cur.fetchall() or []:
                                fid = int(pr["fitting_id"])
                                product_map[fid].append({
                                    "productId": int(pr["product_id"]),
                                    "productName": pr["product_name"],
                                    "price": int(pr["price"]),
                                    "imageUrl": pr["image_url"],
                                    "categoryName": pr["category_name"],
                                })

                        for r in rows:
                            fid = int(r["fitting_id"])
                            prods = product_map.get(fid, [])
                            items.append({
                                "fittingId": fid,
                                "userId": int(r["user_id"]),
                                "photoId": r["photo_id"],
                                "requestId": int(r["request_id"]) if r.get("request_id") is not None else None,
                                "status": r["status"],
                                "resultImageUrl": r["result_image_url"],
                                "productCount": len(prods),
                                "products": prods,
                                "createdAt": self._format_utc_timestamp(r["created_at"]),
                            })
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    where_clauses = ["user_id = ?", "is_deleted = 0"]
                    params: list[Any] = [user_id]
                    if request_id is not None:
                        where_clauses.append("request_id = ?")
                        params.append(request_id)
                    where_sql = " AND ".join(where_clauses)

                    cur.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM fittings
                        WHERE {where_sql};
                        """,
                        tuple(params),
                    )
                    count_row = cur.fetchone()
                    total_count = int(count_row[0]) if count_row else 0

                    if total_count == 0:
                        return [], 0

                    query_params = list(params) + [limit, offset]
                    cur.execute(
                        f"""
                        SELECT fitting_id, user_id, photo_id, request_id, status,
                               result_image_url, error_message, created_at, updated_at
                        FROM fittings
                        WHERE {where_sql}
                        ORDER BY fitting_id DESC
                        LIMIT ? OFFSET ?;
                        """,
                        tuple(query_params),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    fitting_ids = [int(r["fitting_id"]) for r in rows]

                    product_map = {fid: [] for fid in fitting_ids}
                    if fitting_ids:
                        placeholders = ",".join(["?"] * len(fitting_ids))
                        cur.execute(
                            f"""
                            SELECT fitting_id, product_id, product_name, price, image_url, category_name
                            FROM fitting_products
                            WHERE fitting_id IN ({placeholders})
                            ORDER BY id ASC;
                            """,
                            fitting_ids,
                        )
                        for pr in cur.fetchall():
                            pr_dict = dict(pr)
                            fid = int(pr_dict["fitting_id"])
                            product_map[fid].append({
                                "productId": int(pr_dict["product_id"]),
                                "productName": pr_dict["product_name"],
                                "price": int(pr_dict["price"]),
                                "imageUrl": pr_dict["image_url"],
                                "categoryName": pr_dict["category_name"],
                            })

                    for r in rows:
                        fid = int(r["fitting_id"])
                        prods = product_map.get(fid, [])
                        items.append({
                            "fittingId": fid,
                            "userId": int(r["user_id"]),
                            "photoId": r["photo_id"],
                            "requestId": int(r["request_id"]) if r.get("request_id") is not None else None,
                            "status": r["status"],
                            "resultImageUrl": r["result_image_url"],
                            "productCount": len(prods),
                            "products": prods,
                            "createdAt": self._format_utc_timestamp(r["created_at"]),
                        })
                finally:
                    self._close_sqlite_if_transient(conn)

        return items, total_count

    def get_token_usage_in_range(
        self,
        start_iso: str,
        end_iso: str,
        limit: int = 3000,
    ) -> list[dict[str, Any]]:
        """지정된 기간 동안 완료(COMPLETED)된 피팅의 OpenAI 토큰 사용량과 생성일시를 조회합니다 (최대 limit건)."""
        if self._use_postgres:
            schema = self.postgres_schema
            try:
                start_param: Any = datetime.fromisoformat(str(start_iso).replace("Z", "+00:00"))
            except Exception:
                start_param = start_iso
            try:
                end_param: Any = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
            except Exception:
                end_param = end_iso

            with self._lock:
                with self._get_pg_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT prompt_tokens, completion_tokens, created_at
                            FROM {schema}.fittings
                            WHERE created_at >= %s AND created_at <= %s
                              AND status = 'COMPLETED'
                            ORDER BY created_at DESC
                            LIMIT %s;
                            """,
                            (start_param, end_param, limit),
                        )
                        rows = cur.fetchall() or []
                        return [
                            {
                                "promptTokens": int(r.get("prompt_tokens") or 0),
                                "completionTokens": int(r.get("completion_tokens") or 0),
                                "createdAt": self._format_utc_timestamp(r["created_at"]),
                            }
                            for r in reversed(rows)
                        ]
        else:
            with self._lock:
                conn = self._get_sqlite_connection()
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT prompt_tokens, completion_tokens, created_at
                        FROM fittings
                        WHERE created_at >= ? AND created_at <= ?
                          AND status = 'COMPLETED'
                        ORDER BY created_at DESC
                        LIMIT ?;
                        """,
                        (start_iso, end_iso, limit),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    return [
                        {
                            "promptTokens": int(r.get("prompt_tokens") or 0),
                            "completionTokens": int(r.get("completion_tokens") or 0),
                            "createdAt": self._format_utc_timestamp(r["created_at"]),
                        }
                        for r in reversed(rows)
                    ]
                finally:
                    self._close_sqlite_if_transient(conn)
