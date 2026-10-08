package com.fitzza.user.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import javax.crypto.SecretKey;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class JwtTokenProviderTest {

    private static final String SECRET = "test-only-jwt-secret-with-32-bytes-or-more";
    private static final long EXPIRATION_SECONDS = 900;

    /**
     * 서명 검증을 통과한 토큰의 subject와 만료 시각이 발급 설정과 일치하는지 검증한다.
     */
    @Test
    void createsTokenWithUserIdAsSubjectAndConfiguredExpiration() {
        JwtTokenProvider provider = new JwtTokenProvider(SECRET, EXPIRATION_SECONDS);
        Instant before = Instant.now();

        String token = provider.createAccessToken(42L);

        Claims claims = parse(token);
        assertThat(claims.getSubject()).isEqualTo("42");
        assertThat(claims.getExpiration().toInstant())
                .isBetween(before.plusSeconds(EXPIRATION_SECONDS - 2), before.plusSeconds(EXPIRATION_SECONDS + 2));
    }

    @ParameterizedTest
    @ValueSource(longs = {1, 900})
    void acceptsExpirationAtAllowedBoundaries(long expirationSeconds) {
        assertThatCode(() -> new JwtTokenProvider(SECRET, expirationSeconds))
                .doesNotThrowAnyException();
    }

    /**
     * 최소 길이를 충족하지 못한 비밀값으로 발급기를 만들 수 없는지 검증한다.
     */
    @Test
    void rejectsSecretShorterThan32Bytes() {
        assertThatThrownBy(() -> new JwtTokenProvider("too-short", EXPIRATION_SECONDS))
                .isInstanceOf(IllegalArgumentException.class);
    }

    /**
     * 허용 범위를 벗어난 유효 기간을 생성 단계에서 거부하는지 검증한다.
     */
    @ParameterizedTest
    @ValueSource(longs = {Long.MIN_VALUE, -1, 0, 901, 3600, Long.MAX_VALUE})
    void rejectsExpirationOutsideAllowedRange(long expirationSeconds) {
        assertThatThrownBy(() -> new JwtTokenProvider(SECRET, expirationSeconds))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void remainingValidityOfAFreshTokenIsItsConfiguredLifetime() {
        JwtTokenProvider provider = new JwtTokenProvider(SECRET, EXPIRATION_SECONDS);

        assertThat(provider.remainingValidity(provider.createAccessToken(42L)))
                .hasValueSatisfying(remaining -> assertThat(remaining)
                        .isGreaterThan(Duration.ofSeconds(EXPIRATION_SECONDS - 5))
                        .isLessThanOrEqualTo(Duration.ofSeconds(EXPIRATION_SECONDS)));
    }

    @Test
    void remainingValidityIsEmptyForTokensThatCanNoLongerBeUsed() {
        JwtTokenProvider provider = new JwtTokenProvider(SECRET, EXPIRATION_SECONDS);
        SecretKey key = Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8));
        String expired = Jwts.builder()
                .subject("42")
                .expiration(Date.from(Instant.now().minusSeconds(60)))
                .signWith(key, Jwts.SIG.HS256)
                .compact();
        String forged = new JwtTokenProvider("another-secret-that-is-also-at-least-32-bytes", EXPIRATION_SECONDS)
                .createAccessToken(42L);

        assertThat(provider.remainingValidity(expired)).isEmpty();
        assertThat(provider.remainingValidity(forged)).isEmpty();
        assertThat(provider.remainingValidity("not-a-token")).isEmpty();
        assertThat(provider.remainingValidity(null)).isEmpty();
    }

    /**
     * 테스트 전용 키로 서명을 검증한 뒤 토큰의 클레임을 반환한다.
     */
    private Claims parse(String token) {
        SecretKey key = Keys.hmacShaKeyFor(SECRET.getBytes(StandardCharsets.UTF_8));
        return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
    }
}
