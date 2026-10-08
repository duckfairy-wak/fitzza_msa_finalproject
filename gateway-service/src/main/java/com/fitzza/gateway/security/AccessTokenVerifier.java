package com.fitzza.gateway.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class AccessTokenVerifier {

    private static final int MIN_SECRET_BYTES = 32;

    private final JwtParser parser;

    // user-service가 서명에 쓰는 것과 같은 JWT_SECRET이어야 한다.
    public AccessTokenVerifier(@Value("${jwt.secret}") String secret) {
        byte[] secretBytes = secret.getBytes(StandardCharsets.UTF_8);
        if (secretBytes.length < MIN_SECRET_BYTES) {
            throw new IllegalArgumentException("JWT_SECRET must be at least 32 bytes.");
        }
        this.parser = Jwts.parser().verifyWith(Keys.hmacShaKeyFor(secretBytes)).build();
    }

    /**
     * 서명과 만료를 확인하고 토큰의 사용자 ID를 돌려준다.
     *
     * @throws io.jsonwebtoken.ExpiredJwtException 만료된 토큰
     * @throws io.jsonwebtoken.JwtException 서명이 다르거나 형식이 잘못된 토큰
     * @throws IllegalArgumentException 비어 있거나 사용자 ID가 숫자가 아닌 토큰
     */
    public long verify(String token) {
        Claims claims = parser.parseSignedClaims(token).getPayload();
        return Long.parseLong(claims.getSubject());
    }
}
