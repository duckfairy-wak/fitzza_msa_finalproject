package com.fitzza.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.cloud.gateway.route.RouteLocator;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.reactive.server.WebTestClient;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "management.server.port=0",
        "spring.cloud.config.enabled=false",
        "eureka.client.enabled=false",
        "jwt.secret=test-only-jwt-secret-with-32-bytes-or-more"
})
@ActiveProfiles("prod")
class ProductionApiDocsTest {

    @LocalServerPort
    private int port;

    @Autowired
    private RouteLocator routes;

    @Test
    void disablesDocumentationWithoutRemovingBusinessRoutes() {
        assertThat(routes.getRoutes().collectList().block())
                .extracting(route -> route.getId())
                .contains("user-service", "community-service", "notification-service",
                        "product-service-products", "order-service-orders")
                .doesNotContain(
                        "user-service-docs",
                        "product-service-docs",
                        "order-service-docs",
                        "community-service-docs",
                        "notification-service-docs");

        WebTestClient client = WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
        for (String path : new String[] {
                "/api-docs/user-service",
                "/api-docs/product-service",
                "/api-docs/order-service",
                "/api-docs/community-service",
                "/api-docs/notification-service",
                "/v3/api-docs",
                "/v3/api-docs.yaml",
                "/v3/api-docs/swagger-config",
                "/swagger-ui.html",
                "/swagger-ui/index.html",
                "/webjars/swagger-ui/index.html"
        }) {
            client.get().uri(path).exchange().expectStatus().isNotFound();
        }
    }
}
