package com.fitzza.community.client;

import io.micrometer.observation.ObservationRegistry;
import java.time.Duration;
import java.util.Optional;
import java.util.function.Function;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

// 가상 피팅 서비스의 서비스 전용 API(GET /fittings/{fittingId}?userId=)를 부른다.
// 피팅 서비스는 Eureka에 등록되지 않은 FastAPI라 서비스 이름이 아니라 주소(VTON_SERVICE_URL)로 부른다.
@Component
public class VirtualTryOnServiceClient implements FittingResults {

    static final String SERVICE_TOKEN_HEADER = "X-Service-Token";

    private final RestClient restClient;
    private final boolean configured;
    // 호출 하나에만 쓸 시간 제한을 만든다. null이면 시간 제한을 바꾸지 않는다(테스트용 가짜 서버를 그대로 쓰기 위해).
    private final Function<Duration, ClientHttpRequestFactory> timeoutRequestFactories;

    @Autowired
    public VirtualTryOnServiceClient(
            @Value("${fitzza.vton-service.base-url:}") String baseUrl,
            @Value("${fitzza.service-token}") String serviceToken,
            ObjectProvider<ObservationRegistry> observationRegistry) {
        this(UserClientConfig.plainRestClientBuilder()
                .observationRegistry(observationRegistry.getIfAvailable(() -> ObservationRegistry.NOOP)),
                baseUrl, serviceToken, UserClientConfig::timeoutRequestFactory);
    }

    VirtualTryOnServiceClient(RestClient.Builder builder, String baseUrl, String serviceToken) {
        this(builder, baseUrl, serviceToken, null);
    }

    VirtualTryOnServiceClient(
            RestClient.Builder builder,
            String baseUrl,
            String serviceToken,
            Function<Duration, ClientHttpRequestFactory> timeoutRequestFactories) {
        this.configured = baseUrl != null && !baseUrl.isBlank();
        if (configured) {
            builder.baseUrl(baseUrl);
        }
        this.restClient = builder.defaultHeader(SERVICE_TOKEN_HEADER, serviceToken).build();
        this.timeoutRequestFactories = timeoutRequestFactories;
    }

    // 피팅 서비스는 없는 피팅에 404를 돌려준다. 남의 피팅은 owned=false로 온다.
    @Override
    public Optional<FittingResult> findFitting(long fittingId, Long userId) {
        return find(restClient, fittingId, userId);
    }

    // 공유 글 이미지를 새로 받을 때처럼 오래 기다릴 수 없으면, 이 호출에만 짧은 시간 제한을 둔다.
    // 연결 설정·요청 ID 전달·추적은 그대로 두고 요청 팩토리만 바꾼다.
    @Override
    public Optional<FittingResult> findFitting(long fittingId, Long userId, Duration timeout) {
        if (timeoutRequestFactories == null) {
            return find(restClient, fittingId, userId);
        }
        return find(restClient.mutate().requestFactory(timeoutRequestFactories.apply(timeout)).build(), fittingId, userId);
    }

    private Optional<FittingResult> find(RestClient client, long fittingId, Long userId) {
        // 주소가 없으면 확인할 방법이 없으므로 일시 장애와 같이 다룬다(설정 전까지 피팅 공유는 503).
        if (!configured) {
            throw new ResourceAccessException("VTON_SERVICE_URL is not configured");
        }
        try {
            return Optional.ofNullable(client
                    .get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/fittings/{fittingId}")
                            .queryParam("userId", userId)
                            .build(fittingId))
                    .retrieve()
                    .body(FittingResult.class));
        } catch (HttpClientErrorException.NotFound exception) {
            return Optional.empty();
        }
    }
}
