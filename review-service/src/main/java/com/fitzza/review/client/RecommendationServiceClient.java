package com.fitzza.review.client;

import com.fitzza.review.config.RestClientConfig;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

// 추천 서비스의 서비스 전용 API(POST /recommendations/size-feedback)를 부른다.
// 추천 서비스는 Eureka에 등록되지 않은 FastAPI라, 서비스 이름이 아니라 주소(RECOMMENDATION_SERVICE_URL)로 부른다.
@Component
public class RecommendationServiceClient implements SizeFeedbacks {

    static final String SERVICE_TOKEN_HEADER = "X-Service-Token";
    static final String SIZE_FEEDBACK_PATH = "/recommendations/size-feedback";

    private final RestClient restClient;
    private final boolean enabled;

    @Autowired
    public RecommendationServiceClient(
            @Value("${fitzza.recommendation-service.base-url:}") String baseUrl,
            @Value("${fitzza.service-token:}") String serviceToken,
            ObjectProvider<ObservationRegistry> observationRegistry) {
        this(RestClient.builder()
                .requestFactory(RestClientConfig.timeoutRequestFactory())
                .observationRegistry(observationRegistry.getIfAvailable(() -> ObservationRegistry.NOOP)),
                baseUrl, serviceToken);
    }

    RecommendationServiceClient(RestClient.Builder builder, String baseUrl, String serviceToken) {
        this.enabled = baseUrl != null && !baseUrl.isBlank() && serviceToken != null && !serviceToken.isBlank();
        if (enabled) {
            builder.baseUrl(baseUrl).defaultHeader(SERVICE_TOKEN_HEADER, serviceToken);
        }
        this.restClient = builder.requestInterceptor(RestClientConfig.requestIdPropagation()).build();
    }

    @Override
    public boolean isEnabled() {
        return enabled;
    }

    @Override
    public void send(SizeFeedbackRequest request) {
        if (!enabled) {
            throw new IllegalStateException("추천 서비스 주소나 REVIEW_SERVICE_TOKEN이 설정되지 않았습니다.");
        }
        restClient.post()
                .uri(SIZE_FEEDBACK_PATH)
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve()
                .toBodilessEntity();
    }
}
