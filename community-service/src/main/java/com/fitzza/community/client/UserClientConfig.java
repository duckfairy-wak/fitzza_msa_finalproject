package com.fitzza.community.client;

import com.fitzza.community.logging.RequestIdPropagation;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class UserClientConfig {

    private static final int CONNECT_TIMEOUT_MILLIS = 1000;
    // 상대 서비스가 막 떴거나 오래 쉬다 받은 첫 요청은 초기화 때문에 2초를 넘길 수 있어(로컬 확인) 넉넉히 기다린다.
    private static final int READ_TIMEOUT_MILLIS = 5000;

    // @LoadBalanced가 붙으면 http://user-service 같은 서비스 이름을 Eureka에 등록된 주소로 바꿔 호출한다.
    // ObservationRegistry를 붙여야 호출마다 trace 정보(traceparent 헤더)가 다음 서비스로 넘어가 Jaeger에서 한 흐름으로 이어진다.
    @Bean
    @LoadBalanced
    public RestClient.Builder loadBalancedRestClientBuilder(ObjectProvider<ObservationRegistry> observationRegistry) {
        return plainRestClientBuilder().observationRegistry(observationRegistry.getIfAvailable(() -> ObservationRegistry.NOOP));
    }

    // Eureka에 등록되지 않은 FastAPI 서비스(추천·가상 피팅)를 주소로 부를 때 쓴다. 시간 제한과 요청 ID 전달은 같다.
    static RestClient.Builder plainRestClientBuilder() {
        return RestClient.builder().requestFactory(timeoutRequestFactory()).requestInterceptor(new RequestIdPropagation());
    }

    private static ClientHttpRequestFactory timeoutRequestFactory() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(CONNECT_TIMEOUT_MILLIS);
        requestFactory.setReadTimeout(READ_TIMEOUT_MILLIS);
        return requestFactory;
    }
}
