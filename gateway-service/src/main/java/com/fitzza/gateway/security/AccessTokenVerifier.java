package com.fitzza.gateway.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class AccessTokenVerifier {

    private static final int MIN_SECRET_BYTES = 32;
    static final String ROLE_CLAIM = "role";
    static final String USER_ROLE = "USER";
    static final String ADMIN_ROLE = "ADMIN";

    /** 검증을 통과한 토큰의 주인과 역할. */
    public record VerifiedUser(long userId, String role) {
    }

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
     * 서명과 만료를 확인하고 토큰의 사용자 ID를 돌려준다. 모든 라우트가 이 검사를 함께 쓴다.
     *
     * @throws io.jsonwebtoken.ExpiredJwtException 만료된 토큰
     * @throws io.jsonwebtoken.JwtException 서명이 다르거나 형식이 잘못됐거나 아직 쓸 수 없는 토큰
     * @throws IllegalArgumentException 비어 있거나, HS256이 아니거나, 만료 시각이 없거나, 사용자 ID가 양수가 아닌 토큰
     */
    public long verify(String token) {
        return authenticate(token).userId();
    }

    /**
     * {@link #verify(String)}와 같은 검사를 하고 토큰의 역할도 함께 돌려준다.
     * 역할이 없는 예전 토큰이나 모르는 값은 USER로 본다. ADMIN은 정확히 일치할 때만 인정한다.
     */
    public VerifiedUser authenticate(String token) {
        Jws<Claims> signed = parser.parseSignedClaims(token);
        // user-service는 HS256으로만 서명한다. 같은 비밀키로 만든 다른 알고리즘의 토큰은 받지 않는다.
        if (!Jwts.SIG.HS256.getId().equals(signed.getHeader().getAlgorithm())) {
            throw new IllegalArgumentException("HS256 is required.");
        }
        Claims claims = signed.getPayload();
        // 만료 시각이 없는 토큰은 영원히 쓸 수 있으므로 받지 않는다.
        if (claims.getExpiration() == null) {
            throw new IllegalArgumentException("An expiration is required.");
        }
        long userId = Long.parseLong(claims.getSubject());
        if (userId <= 0) {
            throw new IllegalArgumentException("A positive user ID is required.");
        }
        Object role = claims.get(ROLE_CLAIM);
        return new VerifiedUser(userId, ADMIN_ROLE.equals(role) ? ADMIN_ROLE : USER_ROLE);
    }
}
