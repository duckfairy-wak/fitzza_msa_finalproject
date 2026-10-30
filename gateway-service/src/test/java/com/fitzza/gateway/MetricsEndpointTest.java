package com.fitzza.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.net.ServerSocket;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

// Gateway만 Ingress로 외부에 열린다. 메트릭은 관리 포트에서만 나가고, 일반 포트로는 보이지 않아야 한다.
// Gateway는 management.server.port 값으로 관리 포트 요청을 구분한다. 0(랜덤)이면 구분하지 못하고 라우팅을 시도해
// 404가 나므로, 운영처럼 고정 포트를 쓰도록 빈 포트를 골라 넣는다.
// 테스트에서는 Spring Boot가 메트릭 내보내기(Prometheus 레지스트리)를 기본으로 끄므로 명시적으로 켠다.
@AutoConfigureObservability(tracing = false)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "management.metrics.distribution.slo.http.server.requests=100ms,1s",
        "spring.cloud.config.enabled=false",
        "eureka.client.enabled=false",
        "jwt.secret=test-only-jwt-secret-with-32-bytes-or-more"
})
class MetricsEndpointTest {

    private static final String SECRET_LOOKING_ID = "987654321";

    @DynamicPropertySource
    static void fixedManagementPort(DynamicPropertyRegistry registry) throws IOException {
        int freePort;
        try (ServerSocket socket = new ServerSocket(0)) {
            freePort = socket.getLocalPort();
        }
        registry.add("management.server.port", () -> freePort);
    }

    @LocalServerPort
    private int port;

    @LocalManagementPort
    private int managementPort;

    @Test
    void metricsAreServedOnlyOnTheManagementPort() {
        client(port).get().uri("/actuator/prometheus").exchange().expectStatus().isNotFound();
        client(managementPort).get().uri("/actuator/health").exchange().expectStatus().isNotFound();

        String metrics = scrape();
        assertThat(metrics).contains("jvm_memory_used_bytes", "jvm_threads_live_threads", "process_cpu_usage");
    }

    // 원래 경로·ID·쿼리값이 라벨로 남으면 시계열이 끝없이 늘고 민감한 값이 새어 나간다.
    @Test
    void requestMetricsUseBoundedLabelsWithoutRawPathsOrValues() {
        client(port).get().uri("/api/v1/unknown/" + SECRET_LOOKING_ID + "?token=" + SECRET_LOOKING_ID)
                .exchange();

        String metrics = scrape();
        assertThat(metrics).contains("http_server_requests_seconds_count", "http_server_requests_seconds_bucket");
        assertThat(metrics).doesNotContain(SECRET_LOOKING_ID);
        assertThat(metrics.lines().filter(line -> line.startsWith("http_server_requests_seconds_count")))
                .allSatisfy(line -> assertThat(line).doesNotContain("/api/v1/unknown"));
    }

    private String scrape() {
        return client(managementPort).get().uri("/actuator/prometheus").exchange()
                .expectStatus().isOk()
                .expectBody(String.class).returnResult().getResponseBody();
    }

    private static WebTestClient client(int port) {
        return WebTestClient.bindToServer().baseUrl("http://localhost:" + port).build();
    }
}
