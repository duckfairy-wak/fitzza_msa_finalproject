"""AWS S3 및 CloudFront 스토리지 클라이언트."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any
import urllib.parse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StorageClient:
    """S3 Object Key를 안전한 Pre-signed URL 또는 CloudFront CDN URL로 변환하는 스토리지 클라이언트."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.backend = (self.settings.storage_backend or "local").lower().strip()
        self.bucket_name = self.settings.aws_s3_bucket_name
        self.cloudfront_domain = (self.settings.cloudfront_domain or "").strip().rstrip("/")
        self.endpoint_url = (self.settings.aws_endpoint_url or "").strip() or None
        self._s3_client: Any = None
        self._url_cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = threading.Lock()
        self._cache_max_size = 2048

    @property
    def is_s3(self) -> bool:
        """S3 백엔드 활성화 여부."""
        return self.backend in {"s3", "aws"}

    def _parse_s3_location(self, key_or_url: str) -> tuple[str, str]:
        """S3 키 또는 전체 URL(S3/CloudFront/LocalStack/Presigned)에서 (bucket, key)를 추출합니다."""
        clean = key_or_url.strip()
        bucket = self.bucket_name

        if clean.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(clean)
            host = parsed.netloc.lower()
            path = urllib.parse.unquote(parsed.path.lstrip("/"))

            if ".s3." in host:
                bucket = host.split(".s3.")[0]
            elif host.endswith(".s3.amazonaws.com"):
                bucket = host[:-len(".s3.amazonaws.com")]
            elif host.startswith("s3.") or host.startswith("s3-") or host == "s3.amazonaws.com":
                parts = path.split("/", 1)
                bucket = parts[0]
                path = parts[1] if len(parts) > 1 else ""
            elif path.startswith(f"{self.bucket_name}/"):
                path = path[len(self.bucket_name) + 1 :]
        else:
            path = urllib.parse.unquote(clean.lstrip("/"))

        return bucket, path

    def _extract_s3_key(self, key_or_url: str) -> str:
        """S3 키 또는 전체 URL(S3/CloudFront/LocalStack)에서 S3 객체 키를 추출합니다."""
        _, key = self._parse_s3_location(key_or_url)
        return key

    def _get_s3(self) -> Any:
        if self._s3_client is None:
            config = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                signature_version="s3v4",
            )
            session_kwargs: dict[str, Any] = {}
            if self.settings.aws_profile.strip():
                session_kwargs["profile_name"] = self.settings.aws_profile.strip()
            session = boto3.Session(**session_kwargs)

            client_kwargs: dict[str, Any] = {
                "endpoint_url": self.endpoint_url,
                "region_name": self.settings.aws_region,
                "config": config,
            }
            if self.settings.aws_access_key_id.strip():
                client_kwargs["aws_access_key_id"] = self.settings.aws_access_key_id.strip()
            if self.settings.aws_secret_access_key.strip():
                client_kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key.strip()

            self._s3_client = session.client("s3", **client_kwargs)
        return self._s3_client

    def get_public_url(self, key: str) -> str:
        """CloudFront 또는 S3 공개 URL을 조합하여 반환합니다."""
        clean_key = self._extract_s3_key(key)
        if self.cloudfront_domain:
            domain = self.cloudfront_domain
            if not domain.startswith(("http://", "https://")):
                domain = f"https://{domain}"
            return f"{domain}/{clean_key}"
        if self.endpoint_url:
            base = self.endpoint_url.rstrip("/")
            return f"{base}/{self.bucket_name}/{clean_key}"
        return f"https://{self.bucket_name}.s3.{self.settings.aws_region}.amazonaws.com/{clean_key}"

    def get_presigned_url(self, key_or_url: str | None, expires_in: int = 3600) -> str:
        """S3 객체 키 또는 URL을 클라이언트에서 접근 가능한 Pre-signed URL로 변환합니다.

        - key_or_url: Qdrant payload의 S3 키(예: pipeline/runs/.../001.png) 또는 외부 URL
        - expires_in: 서명 유효 시간(초, 기본 3600초 / 1시간)
        - 외부 HTTP/HTTPS URL(예: 무신사 CDN)인 경우 원본 URL을 그대로 반환합니다.
        - CloudFront 도메인이 설정된 경우 영구 캐싱 CDN URL을 우선 반환합니다.
        - S3 백엔드가 아니거나 서명 실패 시 원본 값을 안전하게 fallback합니다.
        """
        if not key_or_url:
            return ""

        clean_input = str(key_or_url).strip()
        if not clean_input:
            return ""

        # 외부 HTTP(S) URL인 경우: 우리 서비스가 관리하는 버킷/엔드포인트가 아니면 원본 유지
        if clean_input.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(clean_input)
            netloc = (parsed.netloc or "").lower()
            is_our_bucket = (
                self.bucket_name.lower() in netloc
                or "fitzza" in netloc
            )
            is_endpoint = bool(
                self.endpoint_url
                and urllib.parse.urlparse(self.endpoint_url).netloc.lower() == netloc
            )
            is_cf_host = bool(
                self.cloudfront_domain
                and urllib.parse.urlparse(self.cloudfront_domain).netloc.lower() == netloc
            )
            is_s3_host = is_our_bucket or is_endpoint
            if not (is_s3_host or is_cf_host):
                return clean_input

        # S3 백엔드가 아니면 원본 반환
        if not self.is_s3:
            return clean_input

        # CloudFront 도메인이 연결되어 있으면 CDN 캐싱 URL로 반환
        if self.cloudfront_domain:
            return self.get_public_url(clean_input)

        bucket, clean_key = self._parse_s3_location(clean_input)
        if not clean_key:
            return clean_input

        # 인메모리 캐시 조회 (서명 생성 오버헤드 최소화 및 브라우저 캐시 히트율 극대화)
        cache_key = f"{bucket}:{clean_key}:{expires_in}"
        now = time.time()
        # 남은 유효 시간이 요청 기간 대비 안전 마진(최대 300초 또는 유효기간 절반) 이상일 때만 캐시 재사용
        min_margin = min(300, expires_in // 2) if expires_in > 60 else 10
        with self._cache_lock:
            cached = self._url_cache.get(cache_key)
            if cached:
                url, expire_at = cached
                if now < expire_at - min_margin:
                    return url

        try:
            s3 = self._get_s3()
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket, "Key": clean_key},
                ExpiresIn=expires_in,
            )
            url_str = str(url)
            with self._cache_lock:
                if len(self._url_cache) >= self._cache_max_size:
                    oldest_key = next(iter(self._url_cache), None)
                    if oldest_key is not None:
                        self._url_cache.pop(oldest_key, None)
                self._url_cache[cache_key] = (url_str, now + expires_in)
            return url_str
        except Exception as exc:
            logger.warning(
                "S3 Pre-signed URL 생성 실패 (bucket=%s, key=%s): %s. 원본 값을 반환합니다.",
                bucket,
                clean_key,
                exc,
            )
            return clean_input

    def download_bytes(self, key_or_path: str) -> bytes:
        """스토리지에서 객체 또는 로컬 파일의 바이트를 다운로드합니다."""
        clean_key = self._extract_s3_key(key_or_path)
        if self.is_s3:
            s3 = self._get_s3()
            try:
                response = s3.get_object(Bucket=self.bucket_name, Key=clean_key)
                return response["Body"].read()
            except Exception as exc:
                logger.error("S3 다운로드 실패 (key=%s): %s", clean_key, exc)
                raise IOError(f"S3 다운로드 실패: {exc}") from exc

        # Local fallback
        path = Path(clean_key)
        if not path.is_file():
            raise FileNotFoundError(f"로컬 파일을 찾을 수 없습니다: {path}")
        return path.read_bytes()


_STORAGE_CLIENT: StorageClient | None = None


def get_storage_client() -> StorageClient:
    """StorageClient 싱글톤 인스턴스를 반환합니다."""
    global _STORAGE_CLIENT
    if _STORAGE_CLIENT is None:
        _STORAGE_CLIENT = StorageClient()
    return _STORAGE_CLIENT


def set_storage_client(client: StorageClient | None) -> None:
    """테스트 또는 의존성 주입용 StorageClient 설정 함수."""
    global _STORAGE_CLIENT
    _STORAGE_CLIENT = client
