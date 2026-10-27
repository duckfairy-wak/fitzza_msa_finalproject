import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

MIN_SERVICE_TOKEN_BYTES = 32


def _default_db_path() -> str:
    base_dir = Path(__file__).resolve().parents[2]
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "recommendation.db")


@dataclass
class Settings:
    qdrant_url: str = field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    qdrant_collection_name: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION_NAME", "musinsa_products")
    )
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    postgres_host: str = field(
        default_factory=lambda: os.getenv("POSTGRES_HOST", "")
    )
    postgres_port: int = field(
        default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432"))
    )
    postgres_db: str = field(
        default_factory=lambda: os.getenv("POSTGRES_DB", "fitzza")
    )
    postgres_user: str = field(
        default_factory=lambda: os.getenv("POSTGRES_USER", "fitzza")
    )
    postgres_password: str = field(
        default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "fitzza_local")
    )
    postgres_schema: str = field(
        default_factory=lambda: os.getenv("POSTGRES_SCHEMA", "recommendation")
    )
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "")
    )
    user_service_url: str = field(
        default_factory=lambda: os.getenv("USER_SERVICE_URL", "")
    )
    product_service_url: str = field(
        default_factory=lambda: os.getenv("PRODUCT_SERVICE_URL", "")
    )
    vton_service_url: str = field(
        default_factory=lambda: os.getenv("VTON_SERVICE_URL", "http://localhost:8091")
    )
    order_service_url: str = field(
        default_factory=lambda: os.getenv("ORDER_SERVICE_URL", "")
    )
    notification_service_url: str = field(
        default_factory=lambda: os.getenv("NOTIFICATION_SERVICE_URL", "")
    )
    recommendation_service_token: str = field(
        default_factory=lambda: os.getenv("RECOMMENDATION_SERVICE_TOKEN", "")
    )
    vton_service_token: str = field(
        default_factory=lambda: os.getenv("VTON_SERVICE_TOKEN", "")
    )
    community_service_token: str = field(
        default_factory=lambda: os.getenv("COMMUNITY_SERVICE_TOKEN", "")
    )
    product_service_token: str = field(
        default_factory=lambda: os.getenv("PRODUCT_SERVICE_TOKEN", "")
    )
    review_service_token: str = field(
        default_factory=lambda: os.getenv("REVIEW_SERVICE_TOKEN", "")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("RECOMMENDATION_DB_PATH", _default_db_path())
    )
    http_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "5.0"))
    )
    redis_host: str = field(
        default_factory=lambda: os.getenv("REDIS_HOST", "localhost")
    )
    redis_port: int = field(
        default_factory=lambda: int(os.getenv("REDIS_PORT", "6379"))
    )
    redis_db: int = field(
        default_factory=lambda: int(os.getenv("REDIS_DB", "0"))
    )
    redis_password: str | None = field(
        default_factory=lambda: os.getenv("REDIS_PASSWORD") or None
    )
    redis_enabled: bool = field(
        default_factory=lambda: os.getenv("REDIS_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    )
    enable_dev_mock_history: bool = field(
        default_factory=lambda: os.getenv("ENABLE_DEV_MOCK_HISTORY", "false").strip().lower() in ("true", "1", "yes")
    )
    enable_lifespan_warmup: bool = field(
        default_factory=lambda: os.getenv("ENABLE_LIFESPAN_WARMUP", "true").strip().lower() in ("true", "1", "yes")
    )
    redis_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("REDIS_TTL_SECONDS", "3600"))
    )
    redis_socket_timeout: float = field(
        default_factory=lambda: float(os.getenv("REDIS_SOCKET_TIMEOUT", "2.0"))
    )
    admin_user_ids: str = field(
        default_factory=lambda: os.getenv("ADMIN_USER_IDS", "4")
    )
    admin_token: str = field(
        default_factory=lambda: os.getenv("ADMIN_TOKEN", "")
    )


    def get_admin_user_ids(self) -> set[int]:
        ids: set[int] = set()
        for part in (self.admin_user_ids or "").split(","):
            clean = part.strip()
            if clean.isdigit():
                ids.add(int(clean))
        return ids

    def verify_admin_token(self, provided_token: str | None) -> bool:
        if not provided_token or not provided_token.strip():
            return False
        configured = (self.admin_token or "").strip()
        if not configured:
            return False
        return secrets.compare_digest(
            configured.encode("utf-8"),
            provided_token.strip().encode("utf-8"),
        )

    def get_postgres_dsn(self) -> str | None:
        if self.database_url.strip():
            return self.database_url.strip()
        host = self.postgres_host.strip()
        if not host:
            return None
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{user}:{password}"
            f"@{host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_caller_tokens(self) -> dict[str, str]:
        return {
            "community": self.community_service_token,
            "product": self.product_service_token,
            "review": self.review_service_token,
        }

    def verify_service_token(
        self,
        provided_token: str | None,
        allowed_callers: Iterable[str],
    ) -> bool:
        if not provided_token or not provided_token.strip():
            return False

        given_bytes = provided_token.encode("utf-8")
        if len(given_bytes) < MIN_SERVICE_TOKEN_BYTES:
            return False

        caller_tokens = self.get_caller_tokens()
        allowed_set = set(allowed_callers)
        matched_callers: set[str] = set()

        for caller, configured_token in caller_tokens.items():
            if not configured_token or not configured_token.strip():
                continue
            configured_bytes = configured_token.encode("utf-8")
            if len(configured_bytes) < MIN_SERVICE_TOKEN_BYTES:
                continue
            if secrets.compare_digest(configured_bytes, given_bytes):
                matched_callers.add(caller)

        return bool(matched_callers & allowed_set)


def get_settings() -> Settings:
    return Settings()
