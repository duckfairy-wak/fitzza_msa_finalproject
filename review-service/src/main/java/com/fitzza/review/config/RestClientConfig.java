package com.fitzza.review.config;

import com.fitzza.review.logging.RequestIdPropagation;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class RestClientConfig {

    private static final int CONNECT_TIMEOUT_MILLIS = 1000;
    // 주문 서비스가 막 떴거나 오래 쉬다 받은 첫 요청은 초기화 때문에 2초를 넘길 수 있어(로컬 확인) 넉넉히 기다린다.
    private static final int READ_TIMEOUT_MILLIS = 5000;

    // @LoadBalanced가 붙으면 http://order-service 같은 서비스 이름을 Eureka에 등록된 주소로 바꿔 호출한다.
    // ObservationRegistry를 붙여야 호출마다 trace 정보(traceparent 헤더)가 다음 서비스로 넘어가 Jaeger에서 한 흐름으로 이어진다.
    @Bean
    @LoadBalanced
    public RestClient.Builder loadBalancedRestClientBuilder(ObjectProvider<ObservationRegistry> observationRegistry) {
        return RestClient.builder()
                .requestFactory(timeoutRequestFactory())
                .requestInterceptor(requestIdPropagation())
                .observationRegistry(observationRegistry.getIfAvailable(() -> ObservationRegistry.NOOP));
    }

    // Eureka에 없는 서비스(추천 서비스 등)를 주소로 부를 때도 같은 시간 제한을 쓴다.
    public static ClientHttpRequestFactory timeoutRequestFactory() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(CONNECT_TIMEOUT_MILLIS);
        requestFactory.setReadTimeout(READ_TIMEOUT_MILLIS);
        return requestFactory;
    }

    public static ClientHttpRequestInterceptor requestIdPropagation() {
        return new RequestIdPropagation();
    }
}
