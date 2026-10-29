package com.fitzza.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.cloud.config.enabled=false",
        "eureka.client.enabled=false",
        "jwt.secret=test-only-jwt-secret-with-32-bytes-or-more"
})
class UserAuthenticationGatewayTest {

    private static final DisposableServer DOWNSTREAM = HttpServer.create().host("127.0.0.1").port(0)
            .handle((request, response) -> {
                if (request.uri().equals("/api/auth/refresh") && request.requestHeaders().contains("Cookie")) {
                    return response.header("Set-Cookie", "refreshToken=rotated; Path=/api; HttpOnly; SameSite=Lax")
                            .sendString(Mono.just(request.requestHeaders().get("Cookie", "missing")));
                }
                return response.sendString(Mono.just(
                    request.uri() + ":" + request.requestHeaders().get("X-User-Id", "anonymous")));
            })
            .bindNow();

    @LocalServerPort
    private int port;

    @Autowired
    private RouteLocator routes;

    // 테스트에는 Redis가 없으므로 블랙리스트 조회만 대역으로 바꾼다.
    @MockBean
    private AccessTokenBlacklist accessTokenBlacklist;

    @BeforeEach
    void nothingIsRevokedByDefault() {
        when(accessTokenBlacklist.isRevoked(anyString())).thenReturn(Mono.just(false));
    }

    @DynamicPropertySource
    static void downstream(DynamicPropertyRegistry registry) {
        for (String service : new String[] {
                "user-service",
                "product-service",
                "order-service",
                "community-service",
                "notification-service",
                "review-service"}) {
            registry.add("spring.cloud.discovery.client.simple.instances." + service + "[0].uri",
                    () -> "http://127.0.0.1:" + DOWNSTREAM.port());
        }
        registry.add("RECOMMENDATION_SERVICE_URL", () -> "http://127.0.0.1:" + DOWNSTREAM.port());
    }

    @AfterAll
    static void stopDownstream() {
        DOWNSTREAM.disposeNow();
    }

    @Test
    void routesTheApiDocumentOfAServiceWithoutAToken() {
        for (String service : new String[] {"user-service", "community-service", "notification-service"}) {
            client().get().uri("/api-docs/" + service)
                    .exchange().expectStatus().isOk().expectBody(String.class)
                    .isEqualTo("/v3/api-docs:anonymous");
        }
        for (String service : new String[] {"product-service", "order-service"}) {
            client().get().uri("/api-docs/" + service)
                    .exchange().expectStatus().isOk().expectBody(String.class)
                    .isEqualTo("/v3/api-docs/public:anonymous");
        }
    }

    @Test
    void routesPublicAuthenticationRequestsWithoutForwardingForgedIdentity() {
        for (String endpoint : new String[] {"signup", "signin", "refresh", "signout"}) {
            client().post().uri("/api/auth/" + endpoint).header("X-User-Id", "999")
                    .exchange().expectStatus().isOk().expectBody(String.class)
                    .isEqualTo("/api/auth/" + endpoint + ":anonymous");
        }
    }

    @Test
    void routesPreferenceOptionsWithoutATokenOrForgedIdentity() {
        for (String prefix : new String[] {"/api", "/api/v1"}) {
            for (String option : new String[] {"fits", "styles"}) {
                client().get().uri(prefix + "/users/preferences/" + option).header("X-User-Id", "999")
                        .exchange().expectStatus().isOk().expectBody(String.class)
                        .isEqualTo("/api/users/preferences/" + option + ":anonymous");
            }
        }
        client().post().uri("/api/users/preferences/fits")
                .exchange().expectStatus().isUnauthorized();
        client().get().uri("/api/users/preferences/fits")
                .headers(headers -> headers.setBearerAuth("invalid-token"))
                .exchange().expectStatus().isUnauthorized();
    }

    @Test
    void authenticatesProfileReadsAndBodyUpdatesThroughActualGatewayRoute() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        client().get().uri("/api/users/me").header("X-User-Id", "999")
                .exchange().expectStatus().isUnauthorized();
        client().get().uri("/api/users/me").header("X-User-Id", "999")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isOk().expectBody(String.class).isEqualTo("/api/users/me:42");
        client().patch().uri("/api/users/me").header("X-User-Id", "999")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isOk().expectBody(String.class).isEqualTo("/api/users/me:42");
    }

    // 프론트는 TOKEN_EXPIRED를 받았을 때만 재발급한다. user 라우트도 다른 라우트와 같은 코드를 줘야 한다.
    @Test
    void expiredTokenOnTheUserRouteTellsTheClientToReissue() {
        String expired = Jwts.builder().subject("42")
                .issuedAt(Date.from(Instant.now().minusSeconds(1000)))
                .expiration(Date.from(Instant.now().minusSeconds(60)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();

        client().get().uri("/api/users/me")
                .headers(headers -> headers.setBearerAuth(expired))
                .exchange().expectStatus().isUnauthorized()
                .expectBody(String.class).value(body -> assertThat(body).contains("\"code\":\"TOKEN_EXPIRED\""));
    }

    @Test
    void analyticsAliasPreservesQueryAndRequiresLogin() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();

        client().get().uri("/api/v1/analytics?period=daily").header("X-User-Id", "999")
                .exchange().expectStatus().isUnauthorized();
        for (String path : new String[] {"/api/v1/analytics", "/api/v1/recommendations/analytics"}) {
            client().get().uri(path + "?period=daily")
                    .headers(headers -> headers.setBearerAuth(token))
                    .exchange().expectStatus().isOk()
                    .expectBody(String.class).isEqualTo("/api/v1/recommendations/analytics?period=daily:42");
        }
    }

    @Test
    void recommendationsRequireLoginAndReceiveTheVerifiedUser() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();

        client().post().uri("/api/v1/recommendations").header("X-User-Id", "999")
                .exchange().expectStatus().isUnauthorized()
                .expectBody(String.class).value(body -> assertThat(body).contains("\"code\":\"UNAUTHENTICATED\""));
        client().post().uri("/api/v1/recommendations").header("X-User-Id", "999")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("/api/v1/recommendations:42");
    }

    @Test
    void routesReviewsAndSurveysToTheReviewService() {
        client().get().uri("/api/reviews?productId=1").exchange()
                .expectStatus().isOk().expectBody(String.class).isEqualTo("/api/reviews?productId=1:anonymous");
        client().get().uri("/api/surveys/me?orderItemIds=1").exchange()
                .expectStatus().isOk().expectBody(String.class).isEqualTo("/api/surveys/me?orderItemIds=1:anonymous");
        client().post().uri("/api/surveys").exchange()
                .expectStatus().isOk().expectBody(String.class).isEqualTo("/api/surveys:anonymous");
    }

    @Test
    void userRouteWithoutATokenAnswersWithACode() {
        client().get().uri("/api/users/me")
                .exchange().expectStatus().isUnauthorized()
                .expectBody(String.class).value(body -> assertThat(body).contains("\"code\":\"UNAUTHENTICATED\""));
    }

    @Test
    void rejectsATokenRevokedByLogoutOnTheUserRoute() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        when(accessTokenBlacklist.isRevoked(token)).thenReturn(Mono.just(true));

        client().get().uri("/api/users/me")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isUnauthorized();
    }

    @Test
    void answersBrowserPreflightFromAnAllowedOriginWithoutAToken() {
        client().options().uri("/api/users/me")
                .header("Origin", "http://localhost:3000")
                .header("Access-Control-Request-Method", "GET")
                .header("Access-Control-Request-Headers", "authorization")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Origin", "http://localhost:3000");
    }

    @Test
    void everyResponseCarriesARequestIdThatTheBrowserMayRead() {
        client().get().uri("/api/users/me").exchange()
                .expectStatus().isUnauthorized()
                .expectHeader().exists("X-Request-Id");
        client().post().uri("/api/auth/signin").header("X-Request-Id", "fe-request-0001")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("X-Request-Id", "fe-request-0001");
        client().post().uri("/api/auth/signin").header("Origin", "http://localhost:5173")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Expose-Headers", "X-Request-Id");
    }

    @Test
    void addsTheCorsHeaderToResponsesForAnAllowedOriginAndRejectsOtherOrigins() {
        client().post().uri("/api/auth/signin").header("Origin", "http://localhost:5173")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Origin", "http://localhost:5173");
        client().post().uri("/api/auth/signin").header("Origin", "http://not-allowed.example")
                .exchange().expectStatus().isForbidden();
    }

    @Test
    void doesNotExposeServiceOnlyEndpoints() {
        client().get().uri("/users/42/body").exchange().expectStatus().isNotFound();
        client().get().uri("/users?userIds=42").exchange().expectStatus().isNotFound();
        client().post().uri("/notifications/events").exchange().expectStatus().isNotFound();
        client().get().uri("/internal/users/42/body").exchange().expectStatus().isNotFound();
        assertThat(routes.getRoutes().collectList().block()).isNotEmpty();
    }

    private WebTestClient client() {
        return WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
    }

    @Test
    void forwardsRefreshCookiesAndAllowsCredentialedFrontendRequests() {
        client().post().uri("/api/auth/refresh")
                .header("Origin", "http://localhost:3000")
                .cookie("refreshToken", "original")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Credentials", "true")
                .expectHeader().valueEquals("Access-Control-Allow-Origin", "http://localhost:3000")
                .expectCookie().valueEquals("refreshToken", "rotated")
                .expectCookie().httpOnly("refreshToken", true)
                .expectBody(String.class).isEqualTo("refreshToken=original");
        client().options().uri("/api/auth/refresh")
                .header("Origin", "http://localhost:3000")
                .header("Access-Control-Request-Method", "POST")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Credentials", "true");
        client().post().uri("/api/auth/refresh")
                .header("Origin", "https://untrusted.example")
                .cookie("refreshToken", "original")
                .exchange().expectStatus().isForbidden();
    }
}
