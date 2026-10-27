"""vton-service 환경 설정 및 토큰 검증 유틸."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_DIR.parent
PROJECT_ROOT = SERVICE_ROOT.parent

load_dotenv(dotenv_path=SERVICE_ROOT / ".env", override=False)
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

MIN_SERVICE_TOKEN_BYTES = 32


def _default_db_path() -> str:
    data_dir = SERVICE_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "vton.db")


def _default_storage_dir() -> str:
    storage_dir = SERVICE_ROOT / "data" / "fittings"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return str(storage_dir)


@dataclass
class Settings:
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "")
    )
    openai_image_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")
    )
    openai_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120.0"))
    )
    openai_max_retries: int = field(
        default_factory=lambda: int(os.getenv("OPENAI_MAX_RETRIES", "1"))
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
        default_factory=lambda: os.getenv("POSTGRES_SCHEMA", "vton")
    )
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "")
    )
    product_service_url: str = field(
        default_factory=lambda: os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8082")
    )
    notification_service_url: str = field(
        default_factory=lambda: os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8086")
    )
    vton_service_token: str = field(
        default_factory=lambda: os.getenv("VTON_SERVICE_TOKEN", "")
    )
    community_service_token: str = field(
        default_factory=lambda: os.getenv("COMMUNITY_SERVICE_TOKEN", "")
    )
    recommendation_service_token: str = field(
        default_factory=lambda: os.getenv("RECOMMENDATION_SERVICE_TOKEN", "")
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("VTON_DB_PATH", _default_db_path())
    )
    storage_dir: str = field(
        default_factory=lambda: os.getenv("VTON_STORAGE_DIR", _default_storage_dir())
    )
    photos_dir: str = field(
        default_factory=lambda: os.getenv("VTON_PHOTOS_DIR", "")
    )
    http_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("HTTP_TIMEOUT_SECONDS", "5.0"))
    )
    public_base_url: str = field(
        default_factory=lambda: os.getenv("VTON_PUBLIC_BASE_URL", "")
    )
    storage_backend: str = field(
        default_factory=lambda: os.getenv("VTON_STORAGE_BACKEND", "local")
    )
    aws_s3_bucket_name: str = field(
        default_factory=lambda: os.getenv("AWS_S3_BUCKET_NAME", "fitzza-prod-assets-vton")
    )
    aws_endpoint_url: str = field(
        default_factory=lambda: os.getenv("AWS_ENDPOINT_URL", "")
    )
    aws_region: str = field(
        default_factory=lambda: os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    )
    aws_access_key_id: str = field(
        default_factory=lambda: os.getenv("AWS_ACCESS_KEY_ID", "")
    )
    aws_secret_access_key: str = field(
        default_factory=lambda: os.getenv("AWS_SECRET_ACCESS_KEY", "")
    )
    cloudfront_domain: str = field(
        default_factory=lambda: os.getenv("CLOUDFRONT_DOMAIN", "")
    )
    queue_backend: str = field(
        default_factory=lambda: os.getenv("VTON_QUEUE_BACKEND", os.getenv("QUEUE_BACKEND", "memory")).strip().lower()
    )
    aws_sqs_queue_url: str = field(
        default_factory=lambda: os.getenv("AWS_SQS_QUEUE_URL", "")
    )
    aws_sqs_dlq_url: str = field(
        default_factory=lambda: os.getenv("AWS_SQS_DLQ_URL", "")
    )
    sqs_visibility_timeout: int = field(
        default_factory=lambda: int(os.getenv("SQS_VISIBILITY_TIMEOUT", "300"))
    )
    sqs_wait_time_seconds: int = field(
        default_factory=lambda: int(os.getenv("SQS_WAIT_TIME_SECONDS", "20"))
    )
    sqs_max_number_of_messages: int = field(
        default_factory=lambda: int(os.getenv("SQS_MAX_NUMBER_OF_MESSAGES", "1"))
    )
    sqs_max_receive_count: int = field(
        default_factory=lambda: int(os.getenv("SQS_MAX_RECEIVE_COUNT", "3"))
    )



    def get_photos_dir(self) -> Path:
        if self.photos_dir.strip():
            p = Path(self.photos_dir.strip())
        else:
            p = Path(self.storage_dir).parent / "photos"
        p.mkdir(parents=True, exist_ok=True)
        return p

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
            "recommendation": self.recommendation_service_token,
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
        for caller in allowed_callers:
            expected_token = caller_tokens.get(caller, "")
            if not expected_token:
                continue
            expected_bytes = expected_token.encode("utf-8")
            if len(expected_bytes) >= MIN_SERVICE_TOKEN_BYTES and secrets.compare_digest(
                given_bytes, expected_bytes
            ):
                return True
        return False


_SETTINGS_INSTANCE: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = Settings()
    return _SETTINGS_INSTANCE


def reset_settings_for_tests(settings: Settings | None = None) -> None:
    global _SETTINGS_INSTANCE
    _SETTINGS_INSTANCE = settings
