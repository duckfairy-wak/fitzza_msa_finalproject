package com.fitzza.user.security;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class RefreshTokenStore {

    private static final String KEY_PREFIX = "refresh-token:";
    private static final int TOKEN_BYTES = 32;

    private final StringRedisTemplate redisTemplate;
    private final Duration timeToLive;
    private final SecureRandom secureRandom = new SecureRandom();

    public RefreshTokenStore(
            StringRedisTemplate redisTemplate,
            @Value("${jwt.refresh-expiration-seconds}") long refreshExpirationSeconds) {
        if (refreshExpirationSeconds <= 0) {
            throw new IllegalArgumentException("Refresh token expiration must be greater than zero.");
        }
        this.redisTemplate = redisTemplate;
        this.timeToLive = Duration.ofSeconds(refreshExpirationSeconds);
    }

    // 토큰마다 키를 따로 두어 여러 기기에서 동시에 로그인할 수 있다. 만료는 Redis TTL에 맡긴다.
    public String issue(Long userId) {
        byte[] randomBytes = new byte[TOKEN_BYTES];
        secureRandom.nextBytes(randomBytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(randomBytes);
        redisTemplate.opsForValue().set(keyOf(token), String.valueOf(userId), timeToLive);
        return token;
    }

    // 조회와 삭제를 한 번에 해서, 같은 토큰으로 동시에 들어온 재발급 요청 중 하나만 성공한다.
    public Optional<Long> consume(String token) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        String userId = redisTemplate.opsForValue().getAndDelete(keyOf(token));
        return Optional.ofNullable(userId).map(Long::valueOf);
    }

    public void revoke(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        redisTemplate.delete(keyOf(token));
    }

    // Redis 내용이 유출돼도 토큰을 그대로 쓸 수 없도록 원문 대신 해시를 키로 쓴다.
    static String keyOf(String token) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8));
            return KEY_PREFIX + HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available.", exception);
        }
    }
}
