"""AWS S3 및 로컬 스토리지를 추상화하는 스토리지 클라이언트."""

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
    """S3 및 로컬 파일시스템 업로드/다운로드를 일관되게 처리하는 스토리지 클라이언트."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.backend = self.settings.storage_backend.lower().strip()
        self.bucket_name = self.settings.aws_s3_bucket_name
        self.cloudfront_domain = self.settings.cloudfront_domain.strip().rstrip("/")
        self.endpoint_url = self.settings.aws_endpoint_url.strip() or None
        self._s3_client: Any = None
        self._url_cache: dict[str, tuple[str, float]] = {}
        self._cache_lock = threading.Lock()
        self._cache_max_size = 2048

    @property
    def is_s3(self) -> bool:
        """S3 백엔드 사용 여부."""
        return self.backend in {"s3", "aws"}

    def _parse_s3_location(self, key_or_url: str) -> tuple[str, str]:
        """S3 키 또는 전체 URL(S3/CloudFront/LocalStack/Presigned)에서 (bucket, key)를 추출합니다."""
        clean = key_or_url.strip()
        bucket = self.bucket_name

        if clean.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(clean)
            host = parsed.netloc.lower()
            path = parsed.path.lstrip("/")

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
            path = clean.lstrip("/")

        # /api/vton/{id}/image 형태의 레거시 로컬 엔드포인트 경로를 S3 객체 키(fittings/{id}.png)로 자동 매핑
        if path.startswith("api/vton/") and path.endswith("/image"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2].isdigit():
                path = f"fittings/{parts[2]}.png"

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
            profile_name = (self.settings.aws_profile or "").strip() or None
            session = boto3.Session(
                profile_name=profile_name,
                region_name=self.settings.aws_region or None,
            )
            kwargs: dict[str, Any] = {
                "endpoint_url": self.endpoint_url,
                "config": config,
            }
            if not profile_name:
                if self.settings.aws_access_key_id and self.settings.aws_access_key_id != "test":
                    kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
                if self.settings.aws_secret_access_key and self.settings.aws_secret_access_key != "test":
                    kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
            self._s3_client = session.client("s3", **kwargs)
        return self._s3_client

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "image/png",
    ) -> str:
        """바이트 데이터를 스토리지에 업로드하고 공개 URL 또는 경로를 반환합니다.

        Args:
            key: 스토리지 내 객체 식별 키 (예: user-images/user_1_abc.png, fittings/10.png)
            data: 업로드할 원본 바이트
            content_type: MIME 타입 (기본 image/png)

        Returns:
            CloudFront URL, S3 URL, 또는 로컬 파일 식별자
        """
        clean_key = self._extract_s3_key(key)

        if self.is_s3:
            s3 = self._get_s3()
            try:
                s3.put_object(
                    Bucket=self.bucket_name,
                    Key=clean_key,
                    Body=data,
                    ContentType=content_type,
                )
                logger.info(
                    "S3 업로드 성공: s3://%s/%s (size=%d)",
                    self.bucket_name,
                    clean_key,
                    len(data),
                )
            except Exception as exc:
                logger.error(
                    "S3 업로드 실패 (bucket=%s, key=%s): %s",
                    self.bucket_name,
                    clean_key,
                    exc,
                    exc_info=True,
                )
                raise IOError(f"스토리지 업로드 실패: {exc}") from exc

            return self.get_public_url(clean_key)

        # Local Fallback
        return self._save_local(clean_key, data)

    def download_bytes(self, key_or_path: str, bucket_name: str | None = None) -> bytes:
        """스토리지에서 객체 또는 로컬 파일의 바이트를 다운로드합니다.

        Args:
            key_or_path: S3 키(예: user-images/xxx.png), 전체 URL, 또는 로컬 파일 경로
            bucket_name: 명시적 버킷 이름 (기본값: URL에서 파싱된 버킷 또는 기본 버킷)

        Returns:
            바이트 데이터
        """
        # 1. 로컬 파일 경로인 경우 (기존 로컬 저장 호환)
        local_p = Path(key_or_path)
        if local_p.is_file():
            return local_p.read_bytes()

        bucket, clean_key = self._parse_s3_location(key_or_path)
        if bucket_name:
            bucket = bucket_name

        # 2. S3 백엔드인 경우
        if self.is_s3:
            s3 = self._get_s3()
            try:
                response = s3.get_object(Bucket=bucket, Key=clean_key)
                body = response["Body"].read()
                logger.info(
                    "S3 다운로드 성공: s3://%s/%s (size=%d)",
                    bucket,
                    clean_key,
                    len(body),
                )
                return body
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404"}:
                    raise FileNotFoundError(f"스토리지에서 파일을 찾을 수 없습니다: s3://{bucket}/{clean_key}") from exc
                raise IOError(f"스토리지 다운로드 오류: {exc}") from exc
            except Exception as exc:
                raise IOError(f"스토리지 다운로드 실패: {exc}") from exc

        # 3. 로컬 백엔드인데 상대 경로인 경우
        base_dir = Path(self.settings.storage_dir).parent
        candidate = base_dir / clean_key
        if candidate.is_file():
            return candidate.read_bytes()

        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {key_or_path}")

    def delete_object(self, key_or_path: str) -> bool:
        """스토리지에서 객체 또는 로컬 파일을 삭제합니다."""
        clean_key = self._extract_s3_key(key_or_path)
        if self.is_s3:
            s3 = self._get_s3()
            try:
                s3.delete_object(Bucket=self.bucket_name, Key=clean_key)
                logger.info("S3 객체 삭제 성공: s3://%s/%s", self.bucket_name, clean_key)
                return True
            except Exception as exc:
                logger.warning("S3 객체 삭제 실패 (%s): %s", clean_key, exc)
                return False

        local_p = Path(key_or_path)
        if local_p.is_file():
            try:
                local_p.unlink()
                return True
            except OSError as exc:
                logger.warning("로컬 파일 삭제 실패 (%s): %s", key_or_path, exc)
                return False
        return False

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
        """S3 객체에 대한 임시 서명 URL(Pre-signed URL)을 생성하여 반환합니다.

        - key_or_url: DB에 저장된 S3 키(fittings/12.png) 또는 전체 URL(https://bucket.s3.../fittings/12.png)
        - expires_in: 서명 유효 시간(초, 기본 3600초 / 1시간)
        - CloudFront 도메인이 설정된 경우 영구 캐싱 CDN URL을 우선 반환합니다.
        - 로컬 스토리지 모드이거나 서명 생성 실패 시 원본 경로를 안전하게 반환합니다.
        """
        if not key_or_url:
            return ""

        clean_input = str(key_or_url).strip()
        if not clean_input:
            return ""

        # 외부 HTTP(S) URL(무신사 원본 이미지 등)인 경우 그대로 유지
        if clean_input.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(clean_input)
            netloc = (parsed.netloc or "").lower()
            is_s3_host = (
                self.bucket_name.lower() in netloc
                or (self.endpoint_url and urllib.parse.urlparse(self.endpoint_url).netloc.lower() == netloc)
                or netloc.endswith(".amazonaws.com")
            )
            is_cf_host = bool(
                self.cloudfront_domain
                and urllib.parse.urlparse(self.cloudfront_domain).netloc.lower() == netloc
            )
            if not (is_s3_host or is_cf_host):
                return clean_input

        # S3 백엔드가 아니거나 로컬 모드인 경우 원본 경로 반환
        if not self.is_s3:
            return clean_input

        # CloudFront 도메인이 연결되어 있으면 CDN 캐싱 URL로 자동 반환
        if self.cloudfront_domain:
            return self.get_public_url(clean_input)

        clean_key = self._extract_s3_key(clean_input)
        if not clean_key:
            return clean_input

        cache_key = f"{clean_key}:{expires_in}"
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
                Params={"Bucket": self.bucket_name, "Key": clean_key},
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
                "S3 Pre-signed URL 생성 실패 (key=%s): %s. 원본 URL을 반환합니다.",
                clean_key,
                exc,
            )
            return clean_input

    def _save_local(self, clean_key: str, data: bytes) -> str:
        """로컬 파일시스템에 저장 (Fallback)."""
        base_dir = Path(self.settings.storage_dir).parent
        target_path = base_dir / clean_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        logger.info("로컬 스토리지 저장 완료: %s (size=%d)", target_path, len(data))
        return str(target_path.resolve())
