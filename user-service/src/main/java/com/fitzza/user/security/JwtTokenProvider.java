package com.fitzza.user.security;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import javax.crypto.SecretKey;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class JwtTokenProvider {

    private static final int MIN_SECRET_BYTES = 32;
    private static final long MAX_EXPIRATION_SECONDS = 900;

    private final SecretKey signingKey;
    private final long expirationSeconds;

    /**
     * UTF-8 비밀키와 만료 설정을 검증하고 토큰 서명에 사용할 키를 준비한다.
     *
     * @param secret UTF-8로 인코딩했을 때 32바이트 이상인 비밀값
     * @param expirationSeconds 1초 이상 900초 이하인 토큰 유효 기간
     * @throws IllegalArgumentException 비밀값이 너무 짧거나 유효 기간이 1초 이상 900초 이하가 아닌 경우
     */
    public JwtTokenProvider(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.expiration-seconds}") long expirationSeconds) {
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalArgumentException("JWT_SECRET must be at least 32 bytes.");
        }
        if (expirationSeconds <= 0 || expirationSeconds > MAX_EXPIRATION_SECONDS) {
            throw new IllegalArgumentException("JWT expiration must be between 1 and 900 seconds.");
        }
        this.signingKey = Keys.hmacShaKeyFor(secretBytes);
        this.expirationSeconds = expirationSeconds;
    }

    /**
     * 사용자 ID를 subject로 설정하고 발급·만료 시각을 포함한 HS256 토큰을 생성한다.
     *
     * @param userId 인증된 사용자의 ID
     * @return 설정된 키로 서명한 액세스 토큰
     */
    public String createAccessToken(Long userId) {
        Instant issuedAt = Instant.now();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .issuedAt(Date.from(issuedAt))
                .expiration(Date.from(issuedAt.plusSeconds(expirationSeconds)))
                .signWith(signingKey, Jwts.SIG.HS256)
                .compact();
    }
}
