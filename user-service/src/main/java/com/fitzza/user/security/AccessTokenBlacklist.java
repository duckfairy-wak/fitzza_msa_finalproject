package com.fitzza.user.security;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

@Component
public class AccessTokenBlacklist {

    // gateway-service의 AccessTokenBlacklist가 같은 방식으로 키를 만들어 조회한다.
    // 한쪽만 바꾸면 로그아웃한 토큰이 계속 통과한다.
    private static final String KEY_PREFIX = "access-token-blacklist:";
    private static final String REVOKED = "revoked";

    private final StringRedisTemplate redisTemplate;
    private final JwtTokenProvider jwtTokenProvider;

    public AccessTokenBlacklist(StringRedisTemplate redisTemplate, JwtTokenProvider jwtTokenProvider) {
        this.redisTemplate = redisTemplate;
        this.jwtTokenProvider = jwtTokenProvider;
    }

    // 우리가 발급했고 아직 살아 있는 토큰만 기록한다. 아무 문자열이나 받으면 로그아웃 API로 Redis를 채울 수 있다.
    // 만료된 뒤에는 게이트웨이가 어차피 거부하므로 만료 시각까지만 보관한다. 초 단위로 올림해 일찍 풀리지 않게 한다.
    public void revoke(String accessToken) {
        jwtTokenProvider
                .remainingValidity(accessToken)
                .map(remaining -> Duration.ofSeconds(remaining.toSeconds() + 1))
                .ifPresent(timeToLive -> redisTemplate.opsForValue().set(keyOf(accessToken), REVOKED, timeToLive));
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
