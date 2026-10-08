package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.atomic.AtomicReference;
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

    private final JwtAuthenticationFilter filter =
            new JwtAuthenticationFilter(new AccessTokenVerifier(TestTokens.SECRET));
    private final AtomicReference<ServerHttpRequest> forwarded = new AtomicReference<>();
    private final GatewayFilterChain chain = exchange -> {
        forwarded.set(exchange.getRequest());
        return Mono.empty();
    };

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
