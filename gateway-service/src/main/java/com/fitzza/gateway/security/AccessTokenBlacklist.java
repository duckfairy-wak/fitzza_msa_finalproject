package com.fitzza.gateway.security;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

@Component
public class AccessTokenBlacklist {

    // user-service의 AccessTokenBlacklist가 로그아웃 때 같은 방식으로 만든 키를 기록한다.
    // 한쪽만 바꾸면 로그아웃한 토큰이 계속 통과한다.
    private static final String KEY_PREFIX = "access-token-blacklist:";
    // 모든 인증 요청이 이 조회를 거치므로, Redis가 느려져도 요청이 오래 매달리지 않게 한다.
    private static final Duration LOOKUP_TIMEOUT = Duration.ofSeconds(1);

    private final ReactiveStringRedisTemplate redisTemplate;

    public AccessTokenBlacklist(ReactiveStringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    /**
     * 로그아웃으로 폐기된 토큰인지 확인한다. Redis에 닿지 못하면 오류로 끝난다.
     */
    public Mono<Boolean> isRevoked(String token) {
        return Mono.defer(() -> redisTemplate.hasKey(keyOf(token))).timeout(LOOKUP_TIMEOUT);
    }

    static String keyOf(String token) {
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8));
            return KEY_PREFIX + HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available.", exception);
        }
    }
}
