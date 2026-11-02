package com.fitzza.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import com.fitzza.gateway.security.AccessTokenBlacklist;
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
        "management.server.port=0",
        "spring.cloud.config.enabled=false",
        "eureka.client.enabled=false",
        "jwt.secret=test-only-jwt-secret-with-32-bytes-or-more"
})
class GatewayRouteTest {

    private static final DisposableServer PRODUCT_SERVICE = startDownstream("product-service");
    private static final DisposableServer ORDER_SERVICE = startDownstream("order-service");
    private static final DisposableServer USER_SERVICE = startDownstream("user-service");

    private static DisposableServer startDownstream(String serviceName) {
        return HttpServer.create().host("127.0.0.1").port(0)
                .handle((request, response) -> response.sendString(Mono.just(serviceName + ":" + request.uri())))
                .bindNow();
    }

    @LocalServerPort
    private int port;

    @Autowired
    private RouteLocator routes;

    @MockBean
    private AccessTokenBlacklist accessTokenBlacklist;

    @BeforeEach
    void nothingIsRevokedByDefault() {
        when(accessTokenBlacklist.isRevoked(anyString())).thenReturn(Mono.just(false));
    }

    @DynamicPropertySource
    static void downstream(DynamicPropertyRegistry registry) {
        registry.add("spring.cloud.discovery.client.simple.instances.product-service[0].uri",
                () -> "http://127.0.0.1:" + PRODUCT_SERVICE.port());
        registry.add("spring.cloud.discovery.client.simple.instances.order-service[0].uri",
                () -> "http://127.0.0.1:" + ORDER_SERVICE.port());
        registry.add("spring.cloud.discovery.client.simple.instances.user-service[0].uri",
                () -> "http://127.0.0.1:" + USER_SERVICE.port());
    }

    @AfterAll
    static void stopDownstream() {
        PRODUCT_SERVICE.disposeNow();
        ORDER_SERVICE.disposeNow();
        USER_SERVICE.disposeNow();
    }

    @Test
    void routesPublicProductAndOrderApisAndHidesInternalPaths() {
        assertThat(routes.getRoutes().collectList().block())
                .extracting(route -> route.getId())
                .contains(
                        "product-service-products",
                        "product-service-categories",
                        "product-service-wishlists",
                        "product-service-worldcups",
                        "order-service-orders",
                        "order-service-carts");

        WebTestClient client = WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        client.get().uri("/api/wishlists").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/wishlists");
        client.delete().uri("/api/wishlists?itemId=1").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/wishlists?itemId=1");
        client.get().uri("/api/products").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/products");
        client.get().uri("/api/products/1").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/products/1");
        client.get().uri("/api/categories").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/categories");
        client.get().uri("/api/worldcups").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/worldcups");
        client.get().uri("/api/worldcups/latest").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/worldcups/latest");
        client.get().uri("/api/carts").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("order-service:/api/carts");
        client.get().uri("/api/orders").exchange().expectStatus().isUnauthorized();
        String orderToken = Jwts.builder().subject("42").issuedAt(new Date())
                .expiration(Date.from(Instant.now().plusSeconds(900)))
                .signWith(Keys.hmacShaKeyFor("test-only-jwt-secret-with-32-bytes-or-more"
                        .getBytes(StandardCharsets.UTF_8)), Jwts.SIG.HS256).compact();
        client.get().uri("/api/orders").headers(headers -> headers.setBearerAuth(orderToken))
                .exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("order-service:/api/orders");
        // FE /api/v1 요청은 서비스의 /api 경로로 바꿔 넘긴다. /api 요청은 그대로 둔다.
        client.get().uri("/api/v1/products").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/products");
        client.get().uri("/api/v1/products/1").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("product-service:/api/products/1");
        client.get().uri("/api/v1/orders").headers(headers -> headers.setBearerAuth(orderToken))
                .exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("order-service:/api/orders");
        client.post().uri("/api/auth/signin").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("user-service:/api/auth/signin");
        client.post().uri("/api/v1/auth/signin").exchange().expectStatus().isOk()
                .expectBody(String.class).isEqualTo("user-service:/api/auth/signin");
        client.get().uri("/internal/wishlists/check").exchange().expectStatus().isNotFound();
        client.get().uri("/internal/worldcups/1").exchange().expectStatus().isNotFound();
        client.get().uri("/internal/products").exchange().expectStatus().isNotFound();
        client.get().uri("/internal/product-options").exchange().expectStatus().isNotFound();
        client.get().uri("/products").exchange().expectStatus().isNotFound();
        client.get().uri("/products/measurements").exchange().expectStatus().isNotFound();
        client.get().uri("/product-options").exchange().expectStatus().isNotFound();
        client.get().uri("/order-items/1").exchange().expectStatus().isNotFound();
        client.get().uri("/wishlists/check").exchange().expectStatus().isNotFound();
        client.get().uri("/worldcups/1").exchange().expectStatus().isNotFound();
    }

    @Test
    void servesOnlyTheLocalUnifiedHealthEndpoint() {
        WebTestClient client = WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();

        client.get().uri("/health").exchange()
                .expectStatus().isOk()
                .expectBody()
                .jsonPath("$.status").isEqualTo("UP")
                .jsonPath("$.liveness").isEqualTo("UP")
                .jsonPath("$.readiness").isEqualTo("UP");
        client.get().uri("/actuator/health").exchange().expectStatus().isNotFound();
    }
}
