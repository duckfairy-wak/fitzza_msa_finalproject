package com.fitzza.community.client;

import io.micrometer.observation.ObservationRegistry;
import java.util.Optional;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

// 추천 서비스의 서비스 전용 API(GET /recommendations/combos/{comboId}?userId=)를 부른다.
// 추천 서비스는 Eureka에 등록되지 않은 FastAPI라 서비스 이름이 아니라 주소(RECOMMENDATION_SERVICE_URL)로 부른다.
@Component
public class RecommendationServiceClient implements ComboResults {

    static final String SERVICE_TOKEN_HEADER = "X-Service-Token";

    private final RestClient restClient;
    private final boolean configured;

    @Autowired
    public RecommendationServiceClient(
            @Value("${fitzza.recommendation-service.base-url:}") String baseUrl,
            @Value("${fitzza.service-token}") String serviceToken,
            ObjectProvider<ObservationRegistry> observationRegistry) {
        this(UserClientConfig.plainRestClientBuilder()
                .observationRegistry(observationRegistry.getIfAvailable(() -> ObservationRegistry.NOOP)),
                baseUrl, serviceToken);
    }

    RecommendationServiceClient(RestClient.Builder builder, String baseUrl, String serviceToken) {
        this.configured = baseUrl != null && !baseUrl.isBlank();
        if (configured) {
            builder.baseUrl(baseUrl);
        }
        this.restClient = builder.defaultHeader(SERVICE_TOKEN_HEADER, serviceToken).build();
    }

    // 추천 서비스는 없는 코디에 404를 돌려준다. 남의 코디는 owned=false로 온다.
    @Override
    public Optional<ComboResult> findCombo(long comboId, Long userId) {
        // 주소가 없으면 확인할 방법이 없으므로 일시 장애와 같이 다룬다(설정 전까지 코디 공유·선택지는 503).
        if (!configured) {
            throw new ResourceAccessException("RECOMMENDATION_SERVICE_URL is not configured");
        }
        try {
            return Optional.ofNullable(restClient
                    .get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/recommendations/combos/{comboId}")
                            .queryParam("userId", userId)
                            .build(comboId))
                    .retrieve()
                    .body(ComboResult.class));
        } catch (HttpClientErrorException.NotFound exception) {
            return Optional.empty();
        }
    }
}
