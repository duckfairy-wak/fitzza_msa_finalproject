package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import reactor.core.publisher.Mono;

class JwtAuthenticationFilterTest {

    private static final String USER_ID_HEADER = "X-User-Id";

    private final AccessTokenBlacklist blacklist = mock(AccessTokenBlacklist.class);
    private final JwtAuthenticationFilter filter =
            new JwtAuthenticationFilter(new AccessTokenVerifier(TestTokens.SECRET), blacklist);
    private final AtomicReference<ServerHttpRequest> forwarded = new AtomicReference<>();
    private final GatewayFilterChain chain = exchange -> {
        forwarded.set(exchange.getRequest());
        return Mono.empty();
    };

    @BeforeEach
    void nothingIsRevokedByDefault() {
        when(blacklist.isRevoked(anyString())).thenReturn(Mono.just(false));
    }

    @Test
    void validTokenIsForwardedWithItsUserId() {
        MockServerWebExchange exchange = send(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.valid("7")));

        assertThat(forwardedUserId()).isEqualTo("7");
        assertThat(exchange.getResponse().getStatusCode()).isNull();
    }

    @Test
    void userIdHeaderSentByTheClientIsReplacedByTheTokenOwner() {
        send(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.valid("7"))
                .header(USER_ID_HEADER, "999"));

        assertThat(forwarded.get().getHeaders().get(USER_ID_HEADER)).containsExactly("7");
    }

    @Test
    void requestWithoutTokenIsForwardedAsAnonymous() {
        send(MockServerHttpRequest.get("/api/v1/community/posts"));

        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getHeaders().containsKey(USER_ID_HEADER)).isFalse();
    }

    @Test
    void userIdHeaderWithoutTokenIsRemoved() {
        send(MockServerHttpRequest.get("/api/v1/users/me").header(USER_ID_HEADER, "999"));

        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getHeaders().containsKey(USER_ID_HEADER)).isFalse();
    }

    @Test
    void expiredTokenIsRejectedWithACodeTheClientCanActOn() {
        MockServerWebExchange exchange = send(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.expired("7")));

        assertThat(forwarded.get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":\"TOKEN_EXPIRED\"");
    }

    @Test
    void forgedTokenIsRejected() {
        MockServerWebExchange exchange = send(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.signedWithOtherSecret("7")));

        assertThat(forwarded.get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":\"INVALID_TOKEN\"");
    }

    @Test
    void emptyBearerTokenIsRejected() {
        MockServerWebExchange exchange = send(
                MockServerHttpRequest.get("/api/v1/users/me").header(HttpHeaders.AUTHORIZATION, "Bearer "));

        assertThat(forwarded.get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @Test
    void tokenRevokedByLogoutIsRejected() {
        String token = TestTokens.valid("7");
        when(blacklist.isRevoked(token)).thenReturn(Mono.just(true));

        MockServerWebExchange exchange = send(
                MockServerHttpRequest.get("/api/v1/users/me").header(HttpHeaders.AUTHORIZATION, "Bearer " + token));

        assertThat(forwarded.get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":\"INVALID_TOKEN\"");
    }

    @Test
    void requestIsRefusedWhenTheBlacklistCannotBeChecked() {
        when(blacklist.isRevoked(anyString())).thenReturn(Mono.error(new IllegalStateException("redis is down")));

        MockServerWebExchange exchange = send(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.valid("7")));

        assertThat(forwarded.get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.SERVICE_UNAVAILABLE);
        assertThat(exchange.getResponse().getBodyAsString().block()).contains("\"code\":\"AUTH_UNAVAILABLE\"");
    }

    @Test
    void failureBehindTheGatewayIsNotReportedAsAnAuthenticationOutage() {
        GatewayFilterChain failingChain = exchange -> Mono.error(new IllegalStateException("downstream failed"));
        MockServerWebExchange exchange = MockServerWebExchange.from(MockServerHttpRequest.get("/api/v1/users/me")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.valid("7")));

        assertThatThrownBy(() -> filter.filter(exchange, failingChain).block())
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("downstream failed");
        assertThat(exchange.getResponse().getStatusCode()).isNull();
    }

    @Test
    void logoutIsForwardedWithoutAskingTheBlacklist() {
        send(MockServerHttpRequest.post("/api/v1/auth/logout")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.valid("7")));

        assertThat(forwarded.get()).isNotNull();
        verify(blacklist, never()).isRevoked(anyString());
    }

    @Test
    void expiredTokenDoesNotBlockTheReissueEndpoint() {
        send(MockServerHttpRequest.post("/api/v1/auth/reissue")
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.expired("7"))
                .header(USER_ID_HEADER, "999"));

        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getHeaders().containsKey(USER_ID_HEADER)).isFalse();
    }

    @Test
    void runsBeforeRouting() {
        assertThat(filter.getOrder()).isNegative();
    }

    private MockServerWebExchange send(MockServerHttpRequest.BaseBuilder<?> request) {
        MockServerWebExchange exchange = MockServerWebExchange.from(request);
        filter.filter(exchange, chain).block();
        return exchange;
    }

    private String forwardedUserId() {
        return forwarded.get().getHeaders().getFirst(USER_ID_HEADER);
    }
}
