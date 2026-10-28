import json
import logging
import time
from typing import Any, Optional

import redis
from redis.exceptions import RedisError

from app.core.config import Settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis 캐시 클라이언트.

    Redis 서버 장애 또는 네트워크 지연 시 애플리케이션의 정상 동작을 보장하기 위해
    모든 캐시 조회/저장 연산에 대해 Graceful Fallback(회복 탄력성)을 적용합니다.
    """

    DEFAULT_PREFIX = "fitzza:rec:"
    CIRCUIT_COOLDOWN_SECONDS: float = 30.0

    def __init__(
        self,
        settings: Settings,
        redis_instance: Optional[redis.Redis] = None,
        key_prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self.settings = settings
        self.key_prefix = key_prefix
        self._enabled = settings.redis_enabled
        self._pool: Optional[redis.ConnectionPool] = None
        self._circuit_open_until: float = 0.0

        if redis_instance is not None:
            self._client: Optional[redis.Redis] = redis_instance
            self._available = True
        elif not self._enabled:
            logger.info("Redis 캐시가 비활성화(REDIS_ENABLED=false)되어 있습니다.")
            self._client = None
            self._available = False
        else:
            try:
                redis_url = (getattr(settings, "redis_url", "") or "").strip()
                if redis_url:
                    self._pool = redis.ConnectionPool.from_url(
                        redis_url,
                        socket_timeout=settings.redis_socket_timeout,
                        socket_connect_timeout=settings.redis_socket_timeout,
                        decode_responses=True,
                    )
                    logger.info("Redis 클라이언트 초기화 완료 (REDIS_URL 적용)")
                else:
                    self._pool = redis.ConnectionPool(
                        host=settings.redis_host,
                        port=settings.redis_port,
                        db=settings.redis_db,
                        password=settings.redis_password,
                        socket_timeout=settings.redis_socket_timeout,
                        socket_connect_timeout=settings.redis_socket_timeout,
                        decode_responses=True,
                    )
                    logger.info(
                        "Redis 클라이언트 초기화 완료 (host=%s, port=%d, db=%d)",
                        settings.redis_host,
                        settings.redis_port,
                        settings.redis_db,
                    )
                self._client = redis.Redis(connection_pool=self._pool)
                self._available = True
            except Exception as exc:
                logger.warning(
                    "Redis 클라이언트 초기화 실패, Fallback 모드로 동작합니다: %s", exc
                )
                self._client = None
                self._available = False

    @property
    def is_available(self) -> bool:
        if not self._available or self._client is None:
            return False
        if time.time() < self._circuit_open_until:
            return False
        return True

    def _format_key(self, key: str) -> str:
        clean_key = key.strip()
        if clean_key.startswith(self.key_prefix):
            return clean_key
        return f"{self.key_prefix}{clean_key}"

    def _handle_error(self, op: str, target: str, exc: Exception) -> None:
        logger.warning("Redis %s 실패 (target=%s): %s", op, target, exc)
        if isinstance(exc, (redis.ConnectionError, redis.TimeoutError)):
            self._circuit_open_until = time.time() + self.CIRCUIT_COOLDOWN_SECONDS

    def _reset_circuit(self) -> None:
        if self._circuit_open_until > 0.0:
            self._circuit_open_until = 0.0

    def ping(self) -> bool:
        if not self.is_available:
            return False
        try:
            assert self._client is not None
            res = bool(self._client.ping())
            if res:
                self._reset_circuit()
            return res
        except (RedisError, Exception) as exc:
            self._handle_error("PING", "server", exc)
            return False

    def get(self, key: str) -> Any:
        if not self.is_available:
            return None
        full_key = self._format_key(key)
        try:
            assert self._client is not None
            raw_val = self._client.get(full_key)
            self._reset_circuit()
            if raw_val is None:
                return None
            try:
                return json.loads(raw_val)
            except (json.JSONDecodeError, TypeError):
                return raw_val
        except (RedisError, Exception) as exc:
            self._handle_error("GET", full_key, exc)
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        if not self.is_available:
            return False
        full_key = self._format_key(key)
        ttl = ttl_seconds if ttl_seconds is not None else self.settings.redis_ttl_seconds
        try:
            assert self._client is not None
            if isinstance(value, (dict, list, bool, int, float)) or value is None:
                serialized = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, str):
                serialized = value
            else:
                serialized = json.dumps(value, ensure_ascii=False, default=str)

            if ttl > 0:
                res = bool(self._client.set(full_key, serialized, ex=ttl))
            else:
                res = bool(self._client.set(full_key, serialized))
            if res:
                self._reset_circuit()
            return res
        except (RedisError, Exception) as exc:
            self._handle_error("SET", full_key, exc)
            return False

    def delete(self, key: str) -> bool:
        if not self.is_available:
            return False
        full_key = self._format_key(key)
        try:
            assert self._client is not None
            return bool(self._client.delete(full_key))
        except (RedisError, Exception) as exc:
            self._handle_error("DELETE", full_key, exc)
            return False

    def exists(self, key: str) -> bool:
        if not self.is_available:
            return False
        full_key = self._format_key(key)
        try:
            assert self._client is not None
            return bool(self._client.exists(full_key))
        except (RedisError, Exception) as exc:
            self._handle_error("EXISTS", full_key, exc)
            return False

    def delete_pattern(self, pattern: str) -> int:
        """패턴에 일치하는 캐시 키 일괄 삭제."""
        if not self.is_available:
            return 0
        full_pattern = self._format_key(pattern)
        try:
            assert self._client is not None
            keys = list(self._client.scan_iter(match=full_pattern, count=100))
            if keys:
                return int(self._client.delete(*keys))
            return 0
        except (RedisError, Exception) as exc:
            self._handle_error("DELETE_PATTERN", full_pattern, exc)
            return 0


    def close(self) -> None:
        try:
            if self._client is not None:
                self._client.close()
            if self._pool is not None:
                self._pool.disconnect()
        except Exception as exc:
            logger.debug("Redis 클라이언트 종료 중 예외 발생 (무시됨): %s", exc)
