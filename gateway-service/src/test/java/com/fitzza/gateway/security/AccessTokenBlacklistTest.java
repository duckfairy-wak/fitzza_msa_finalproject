package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import reactor.core.publisher.Mono;

class AccessTokenBlacklistTest {

    private final ReactiveStringRedisTemplate redisTemplate = mock(ReactiveStringRedisTemplate.class);
    private final AccessTokenBlacklist blacklist = new AccessTokenBlacklist(redisTemplate);

    @Test
    void tokenRecordedAtLogoutIsRevoked() {
        when(redisTemplate.hasKey(AccessTokenBlacklist.keyOf("logged-out"))).thenReturn(Mono.just(true));

        assertThat(blacklist.isRevoked("logged-out").block()).isTrue();
    }

    @Test
    void tokenThatWasNeverRecordedIsNotRevoked() {
        when(redisTemplate.hasKey(AccessTokenBlacklist.keyOf("still-in-use"))).thenReturn(Mono.just(false));

        assertThat(blacklist.isRevoked("still-in-use").block()).isFalse();
    }

    @Test
    void redisFailureIsPassedOnInsteadOfLookingLikeAnAnswer() {
        when(redisTemplate.hasKey(AccessTokenBlacklist.keyOf("any")))
                .thenReturn(Mono.error(new IllegalStateException("redis is down")));

        assertThatThrownBy(() -> blacklist.isRevoked("any").block()).isInstanceOf(IllegalStateException.class);
    }

    // user-service의 AccessTokenBlacklistTest에도 같은 값이 있다. 두 서비스의 키가 달라지면 둘 중 하나가 깨진다.
    @Test
    void keyIsTheSameOneUserServiceWritesAtLogout() {
        assertThat(AccessTokenBlacklist.keyOf("sample-access-token"))
                .isEqualTo("access-token-blacklist:10df4fbd27d19c9f6ac1b1c01511aa33c6df463de1e94ef5f5e68e6fda090c5a");
    }
}
