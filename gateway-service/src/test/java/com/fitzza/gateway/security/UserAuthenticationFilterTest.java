package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.concurrent.atomic.AtomicReference;
import javax.crypto.SecretKey;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

class UserAuthenticationFilterTest {

    private static final SecretKey KEY = Keys.hmacShaKeyFor(
            "test-only-jwt-secret-with-32-bytes-or-more".getBytes(StandardCharsets.UTF_8));
    private final UserAuthenticationFilter filter = new UserAuthenticationFilter(
            "test-only-jwt-secret-with-32-bytes-or-more");

    @ParameterizedTest
    @ValueSource(strings = {"GET /api/v1/users/me", "PATCH /api/v1/users/me/body"})
    void forwardsVerifiedSubjectInsteadOfAllClientUserIds(String endpoint) {
        MockServerWebExchange exchange = exchange(endpoint, "user-service",
                "Bearer " + token("42", Instant.now().plusSeconds(900), KEY));
        AtomicReference<ServerWebExchange> forwarded = filter(exchange);

        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getRequest().getHeaders().get("X-User-Id")).containsExactly("42");
    }

    @ParameterizedTest
    @ValueSource(strings = {"GET /api/v1/users/me", "PATCH /api/v1/users/me/body",
            "GET /api/v1/users/new-private-endpoint", "POST /api/v1/users/profile/options",
            "GET /api/v1/users/%6de", "GET /api/v1/users/me/"})
    void rejectsUnauthenticatedRequestsDespiteSpoofedUserId(String endpoint) {
        assertUnauthorized(exchange(endpoint, "user-service"));
    }

    @Test
    void rejectsExpiredTokensAndTokensSignedWithAnotherKey() {
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service",
                "Bearer " + token("42", Instant.now().minusSeconds(60), KEY)));
        SecretKey otherKey = Jwts.SIG.HS256.key().build();
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service",
                "Bearer " + token("42", Instant.now().plusSeconds(900), otherKey)));
    }

    @ParameterizedTest
    @ValueSource(strings = {"not-a-token", "Bearer invalid", "Basic credentials", "Bearer "})
    void rejectsMalformedAuthorization(String authorization) {
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service", authorization));
    }

    @Test
    void rejectsMultipleAuthorizationHeaders() {
        String authorization = "Bearer " + token("42", Instant.now().plusSeconds(900), KEY);
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service", authorization, authorization));
    }

    @Test
    void rejectsTokensWithoutExpirationOrSubjectAndUnsignedTokens() {
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service", "Bearer " + token("42", null, KEY)));
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service",
                "Bearer " + token(null, Instant.now().plusSeconds(900), KEY)));
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service",
                "Bearer " + Jwts.builder().subject("42").compact()));
    }

    @ParameterizedTest
    @ValueSource(strings = {"0", "-1", "abc", "9223372036854775808"})
    void rejectsInvalidUserIds(String subject) {
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service",
                "Bearer " + token(subject, Instant.now().plusSeconds(900), KEY)));
    }

    @Test
    void rejectsTokensThatAreNotYetValidOrUseAnotherAlgorithm() {
        String futureToken = Jwts.builder().subject("42")
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .notBefore(Date.from(Instant.now().plusSeconds(300)))
                .signWith(KEY, Jwts.SIG.HS256).compact();
        assertUnauthorized(exchange("GET /api/v1/users/me", "user-service", "Bearer " + futureToken));
        String secret = "test-only-long-secret-for-hs512-validation-".repeat(2);
        UserAuthenticationFilter longKeyFilter = new UserAuthenticationFilter(secret);
        String token = Jwts.builder().subject("42")
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS512).compact();
        MockServerWebExchange exchange = exchange("GET /api/v1/users/me", "user-service", "Bearer " + token);
        longKeyFilter.filter(exchange, ignored -> { throw new AssertionError("Request must not be forwarded"); }).block();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
    }

    @ParameterizedTest
    @ValueSource(strings = {"POST /api/v1/auth/login", "POST /api/v1/auth/reissue", "POST /api/v1/auth/logout",
            "POST /api/v1/users/signup", "GET /api/v1/users/check-email", "GET /api/v1/users/check-nickname",
            "GET /api/v1/users/profile/options", "GET /api/v1/users/status"})
    void keepsPublicEndpointsAccessibleAndStripsSpoofedIds(String endpoint) {
        AtomicReference<ServerWebExchange> forwarded = filter(exchange(endpoint, "user-service"));
        assertThat(forwarded.get()).isNotNull();
        assertThat(forwarded.get().getRequest().getHeaders()).doesNotContainKey("X-User-Id");
    }

    @Test
    void stripsSpoofedIdsFromOtherRoutes() {
        AtomicReference<ServerWebExchange> forwarded = filter(exchange("GET /api/v1/products/status", "product-service"));
        assertThat(forwarded.get().getRequest().getHeaders()).doesNotContainKey("X-User-Id");
    }

    @Test
    void rejectsWeakSigningSecretsAtStartup() {
        assertThatThrownBy(() -> new UserAuthenticationFilter("too-short"))
                .isInstanceOf(io.jsonwebtoken.security.WeakKeyException.class);
    }

    private void assertUnauthorized(MockServerWebExchange exchange) {
        assertThat(filter(exchange).get()).isNull();
        assertThat(exchange.getResponse().getStatusCode()).isEqualTo(HttpStatus.UNAUTHORIZED);
        assertThat(exchange.getResponse().getHeaders().getFirst(HttpHeaders.WWW_AUTHENTICATE)).isEqualTo("Bearer");
    }

    private AtomicReference<ServerWebExchange> filter(MockServerWebExchange exchange) {
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
        filter.filter(exchange, request -> {
            forwarded.set(request);
            return Mono.empty();
        }).block();
        return forwarded;
    }

    private MockServerWebExchange exchange(String endpoint, String routeId, String... authorization) {
        String[] parts = endpoint.split(" ", 2);
        MockServerHttpRequest.BaseBuilder<?> request = MockServerHttpRequest.method(HttpMethod.valueOf(parts[0]), parts[1])
                .header("x-user-id", "999", "1000");
        if (authorization.length > 0) {
            request.header(HttpHeaders.AUTHORIZATION, authorization);
        }
        MockServerWebExchange exchange = MockServerWebExchange.from(request.build());
        exchange.getAttributes().put(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR,
                Route.async().id(routeId).uri("http://localhost:8081").predicate(ignored -> true).build());
        return exchange;
    }

    private String token(String subject, Instant expiration, SecretKey key) {
        return Jwts.builder().subject(subject)
                .issuedAt(new Date())
                .expiration(expiration == null ? null : Date.from(expiration))
                .signWith(key, Jwts.SIG.HS256).compact();
    }
}
