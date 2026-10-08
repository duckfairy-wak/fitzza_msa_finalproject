package com.fitzza.gateway.security;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;

final class TestTokens {

    static final String SECRET = "gateway-test-secret-that-is-at-least-32-bytes";
    static final String OTHER_SECRET = "another-secret-that-is-also-at-least-32-bytes";

    private TestTokens() {
    }

    static String valid(String subject) {
        return signed(SECRET, subject, Instant.now().plusSeconds(600));
    }

    static String expired(String subject) {
        return signed(SECRET, subject, Instant.now().minusSeconds(600));
    }

    static String signedWithOtherSecret(String subject) {
        return signed(OTHER_SECRET, subject, Instant.now().plusSeconds(600));
    }

    private static String signed(String secret, String subject, Instant expiration) {
        return Jwts.builder()
                .subject(subject)
                .issuedAt(Date.from(expiration.minusSeconds(3600)))
                .expiration(Date.from(expiration))
                .signWith(Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256)
                .compact();
    }
}
