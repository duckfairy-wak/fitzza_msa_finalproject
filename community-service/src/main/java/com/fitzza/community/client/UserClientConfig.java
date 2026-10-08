package com.fitzza.community.client;

import java.io.IOException;
import java.net.HttpURLConnection;
import javax.net.ssl.HttpsURLConnection;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration
public class UserClientConfig {

    private static final int CONNECT_TIMEOUT_MILLIS = 1000;
    private static final int READ_TIMEOUT_MILLIS = 2000;

    // @LoadBalanced가 붙으면 https://user-service 같은 서비스 이름을 Eureka에 등록된 주소로 바꿔 호출한다.
    @Bean
    @LoadBalanced
    public RestClient.Builder loadBalancedRestClientBuilder() {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory() {
            @Override
            protected void prepareConnection(HttpURLConnection connection, String httpMethod) throws IOException {
                // Validate the resolved destination after load balancing, before sending the internal token.
                if (!(connection instanceof HttpsURLConnection)) {
                    throw new IOException("User service requests require HTTPS");
                }
                super.prepareConnection(connection, httpMethod);
                // Keep JVM certificate/hostname validation and never forward credentials through redirects.
                connection.setInstanceFollowRedirects(false);
            }
        };
        requestFactory.setConnectTimeout(CONNECT_TIMEOUT_MILLIS);
        requestFactory.setReadTimeout(READ_TIMEOUT_MILLIS);
        return RestClient.builder().requestFactory(requestFactory);
    }
}
