package com.fitzza.user.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.Duration;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

class RefreshTokenStoreTest {

    private static final long THIRTY_DAYS = 2_592_000L;

    private final StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);

    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> valueOperations = mock(ValueOperations.class);

    private RefreshTokenStore store;

    @BeforeEach
    void setUp() {
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        store = new RefreshTokenStore(redisTemplate, THIRTY_DAYS);
    }

    @Test
    void issueStoresOnlyTheHashWithTheConfiguredLifetime() {
        String token = store.issue(7L);

        ArgumentCaptor<String> key = ArgumentCaptor.forClass(String.class);
        verify(valueOperations).set(key.capture(), eq("7"), eq(Duration.ofSeconds(THIRTY_DAYS)));
        assertThat(token).hasSizeGreaterThanOrEqualTo(43);
        assertThat(key.getValue()).isEqualTo(RefreshTokenStore.keyOf(token));
        assertThat(key.getValue()).startsWith("refresh-token:").doesNotContain(token);
    }

    @Test
    void issueGivesADifferentTokenEveryTime() {
        assertThat(store.issue(7L)).isNotEqualTo(store.issue(7L));
    }

    @Test
    void consumeReturnsTheOwnerAndRemovesTheTokenInOneStep() {
        when(valueOperations.getAndDelete(RefreshTokenStore.keyOf("known-token"))).thenReturn("7");

        assertThat(store.consume("known-token")).contains(7L);
        verify(valueOperations).getAndDelete(RefreshTokenStore.keyOf("known-token"));
    }

    @Test
    void consumeReturnsNothingForUnknownOrExpiredToken() {
        when(valueOperations.getAndDelete(anyString())).thenReturn(null);

        assertThat(store.consume("unknown-token")).isEmpty();
    }

    @Test
    void consumeDoesNotAskRedisForABlankToken() {
        assertThat(store.consume(" ")).isEmpty();
        assertThat(store.consume(null)).isEmpty();
        verifyNoInteractions(valueOperations);
    }

    @Test
    void revokeDeletesTheStoredToken() {
        store.revoke("known-token");

        verify(redisTemplate).delete(RefreshTokenStore.keyOf("known-token"));
    }

    @Test
    void revokeIgnoresABlankToken() {
        store.revoke("");
        store.revoke(null);

        verify(redisTemplate, never()).delete(anyString());
    }

    @Test
    void rejectsNonPositiveLifetime() {
        assertThatThrownBy(() -> new RefreshTokenStore(redisTemplate, 0))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
