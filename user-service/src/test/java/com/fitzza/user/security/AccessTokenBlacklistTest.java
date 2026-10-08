package com.fitzza.user.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

class AccessTokenBlacklistTest {

    private static final String SECRET = "test-only-jwt-secret-with-32-bytes-or-more";
    private static final long EXPIRATION_SECONDS = 900;

    private final StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);

    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> valueOperations = mock(ValueOperations.class);

    private final JwtTokenProvider jwtTokenProvider = new JwtTokenProvider(SECRET, EXPIRATION_SECONDS);
    private final AccessTokenBlacklist blacklist = new AccessTokenBlacklist(redisTemplate, jwtTokenProvider);

    @Test
    void revokeStoresOnlyTheHashUntilTheTokenWouldHaveExpired() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        String token = jwtTokenProvider.createAccessToken(7L);

        blacklist.revoke(token);

        ArgumentCaptor<Duration> timeToLive = ArgumentCaptor.forClass(Duration.class);
        verify(valueOperations).set(eq(AccessTokenBlacklist.keyOf(token)), eq("revoked"), timeToLive.capture());
        assertThat(timeToLive.getValue())
                .isGreaterThan(Duration.ofSeconds(EXPIRATION_SECONDS - 5))
                .isLessThanOrEqualTo(Duration.ofSeconds(EXPIRATION_SECONDS + 1));
        assertThat(AccessTokenBlacklist.keyOf(token)).doesNotContain(token);
    }

    @Test
    void revokeIgnoresATokenThisServiceDidNotIssue() {
        String forged = new JwtTokenProvider("another-secret-that-is-also-at-least-32-bytes", EXPIRATION_SECONDS)
                .createAccessToken(7L);

        blacklist.revoke(forged);
        blacklist.revoke("not-a-token");

        verifyNoInteractions(redisTemplate);
    }

    // gateway-service의 AccessTokenBlacklistTest에도 같은 값이 있다. 두 서비스의 키가 달라지면 둘 중 하나가 깨진다.
    @Test
    void keyIsTheSameOneTheGatewayLooksUp() {
        assertThat(AccessTokenBlacklist.keyOf("sample-access-token"))
                .isEqualTo("access-token-blacklist:10df4fbd27d19c9f6ac1b1c01511aa33c6df463de1e94ef5f5e68e6fda090c5a");
    }
}
