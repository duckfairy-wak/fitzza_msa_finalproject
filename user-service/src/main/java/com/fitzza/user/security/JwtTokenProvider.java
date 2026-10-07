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

    private final SecretKey signingKey;
    private final long expirationSeconds;

    public JwtTokenProvider(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.expiration-seconds}") long expirationSeconds) {
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalArgumentException("JWT_SECRET must be at least 32 bytes.");
        }
        if (expirationSeconds <= 0) {
            throw new IllegalArgumentException("JWT expiration must be greater than zero.");
        }
        this.signingKey = Keys.hmacShaKeyFor(secretBytes);
        this.expirationSeconds = expirationSeconds;
    }

    // 게이트웨이가 같은 키와 HS256으로 검증하고 subject를 X-User-Id 헤더로 넘긴다.
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
