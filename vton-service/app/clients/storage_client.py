"""AWS S3 및 로컬 스토리지를 추상화하는 스토리지 클라이언트."""

from __future__ import annotations

import logging
from pathlib import Path
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

    @property
    def is_s3(self) -> bool:
        """S3 백엔드 사용 여부."""
        return self.backend in {"s3", "aws"}

    def _extract_s3_key(self, key_or_url: str) -> str:
        """S3 키 또는 전체 URL(S3/CloudFront/LocalStack)에서 S3 객체 키를 추출합니다."""
        clean = key_or_url.strip()
        if clean.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(clean)
            path = parsed.path.lstrip("/")
            if path.startswith(f"{self.bucket_name}/"):
                path = path[len(self.bucket_name) + 1 :]
        else:
            path = clean.lstrip("/")

        # /api/vton/{id}/image 형태의 레거시 로컬 엔드포인트 경로를 S3 객체 키(fittings/{id}.png)로 자동 매핑
        if path.startswith("api/vton/") and path.endswith("/image"):
            parts = path.split("/")
            if len(parts) == 4 and parts[2].isdigit():
                return f"fittings/{parts[2]}.png"

        return path

    def _get_s3(self) -> Any:
        if self._s3_client is None:
            config = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                signature_version="s3v4",
            )
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.settings.aws_region,
                aws_access_key_id=self.settings.aws_access_key_id or None,
                aws_secret_access_key=self.settings.aws_secret_access_key or None,
                config=config,
            )
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

    def download_bytes(self, key_or_path: str) -> bytes:
        """스토리지에서 객체 또는 로컬 파일의 바이트를 다운로드합니다.

        Args:
            key_or_path: S3 키(예: user-images/xxx.png), 전체 URL, 또는 로컬 파일 경로

        Returns:
            바이트 데이터
        """
        # 1. 로컬 파일 경로인 경우 (기존 로컬 저장 호환)
        local_p = Path(key_or_path)
        if local_p.is_file():
            return local_p.read_bytes()

        clean_key = self._extract_s3_key(key_or_path)

        # 2. S3 백엔드인 경우
        if self.is_s3:
            s3 = self._get_s3()
            try:
                response = s3.get_object(Bucket=self.bucket_name, Key=clean_key)
                body = response["Body"].read()
                logger.info(
                    "S3 다운로드 성공: s3://%s/%s (size=%d)",
                    self.bucket_name,
                    clean_key,
                    len(body),
                )
                return body
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in {"NoSuchKey", "404"}:
                    raise FileNotFoundError(f"스토리지에서 파일을 찾을 수 없습니다: {clean_key}") from exc
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

        # S3 백엔드가 아니거나 로컬 모드인 경우 원본 경로 반환
        if not self.is_s3:
            return clean_input

        # CloudFront 도메인이 연결되어 있으면 CDN 캐싱 URL로 자동 반환
        if self.cloudfront_domain:
            return self.get_public_url(clean_input)

        clean_key = self._extract_s3_key(clean_input)
        try:
            s3 = self._get_s3()
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": clean_key},
                ExpiresIn=expires_in,
            )
            return str(url)
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
