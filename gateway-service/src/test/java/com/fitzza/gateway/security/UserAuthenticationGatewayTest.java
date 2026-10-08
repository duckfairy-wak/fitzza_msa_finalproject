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
            .handle((request, response) -> response.sendString(Mono.just(
                    request.uri() + ":" + request.requestHeaders().get("X-User-Id", "anonymous"))))
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
        registry.add("spring.cloud.discovery.client.simple.instances.user-service[0].uri",
                () -> "http://127.0.0.1:" + DOWNSTREAM.port());
    }

    @AfterAll
    static void stopDownstream() {
        DOWNSTREAM.disposeNow();
    }

    @Test
    void routesPublicAuthenticationRequestsWithoutForwardingForgedIdentity() {
        for (String endpoint : new String[] {"login", "reissue", "logout"}) {
            client().post().uri("/api/v1/auth/" + endpoint).header("X-User-Id", "999")
                    .exchange().expectStatus().isOk().expectBody(String.class)
                    .isEqualTo("/api/v1/auth/" + endpoint + ":anonymous");
        }
    }

    @Test
    void authenticatesProfileReadsAndBodyUpdatesThroughActualGatewayRoute() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        client().get().uri("/api/v1/users/me").header("X-User-Id", "999")
                .exchange().expectStatus().isUnauthorized();
        client().get().uri("/api/v1/users/me").header("X-User-Id", "999")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isOk().expectBody(String.class).isEqualTo("/api/v1/users/me:42");
        client().patch().uri("/api/v1/users/me/body").header("X-User-Id", "999")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isOk().expectBody(String.class).isEqualTo("/api/v1/users/me/body:42");
    }

    @Test
    void rejectsATokenRevokedByLogoutOnTheUserRoute() {
        String token = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        when(accessTokenBlacklist.isRevoked(token)).thenReturn(Mono.just(true));

        client().get().uri("/api/v1/users/me")
                .headers(headers -> headers.setBearerAuth(token))
                .exchange().expectStatus().isUnauthorized();
    }

    @Test
    void answersBrowserPreflightFromAnAllowedOriginWithoutAToken() {
        client().options().uri("/api/v1/users/me")
                .header("Origin", "http://localhost:3000")
                .header("Access-Control-Request-Method", "GET")
                .header("Access-Control-Request-Headers", "authorization")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Origin", "http://localhost:3000");
    }

    @Test
    void addsTheCorsHeaderToResponsesForAnAllowedOriginAndRejectsOtherOrigins() {
        client().post().uri("/api/v1/auth/login").header("Origin", "http://localhost:5173")
                .exchange().expectStatus().isOk()
                .expectHeader().valueEquals("Access-Control-Allow-Origin", "http://localhost:5173");
        client().post().uri("/api/v1/auth/login").header("Origin", "http://not-allowed.example")
                .exchange().expectStatus().isForbidden();
    }

    @Test
    void doesNotExposeInternalUserEndpoints() {
        client().get().uri("/internal/users/42/body").exchange().expectStatus().isNotFound();
        assertThat(routes.getRoutes().collectList().block()).isNotEmpty();
    }

    private WebTestClient client() {
        return WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
    }
}
