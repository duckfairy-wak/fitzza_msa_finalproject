package com.fitzza.community.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.fitzza.community.client.FittingResults.FittingResult;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.mock.http.client.MockClientHttpRequest;
import org.springframework.mock.http.client.MockClientHttpResponse;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

class VirtualTryOnServiceClientTest {

    private static final String BASE_URL = "http://vton-service:8000";
    private static final String SERVICE_TOKEN = "test-community-service-token";

    @Test
    void readsTheFittingForTheUserWithTheServiceToken() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        VirtualTryOnServiceClient client = new VirtualTryOnServiceClient(builder, BASE_URL, SERVICE_TOKEN);
        server.expect(requestTo(BASE_URL + "/fittings/3?userId=7"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(VirtualTryOnServiceClient.SERVICE_TOKEN_HEADER, SERVICE_TOKEN))
                .andRespond(withSuccess(
                        "{\"owned\":true,\"status\":\"COMPLETED\",\"resultImageUrl\":\"https://cdn.example.com/f3.png\","
                                + "\"products\":[{\"productId\":1,\"productName\":\"셔츠\",\"price\":39000,"
                                + "\"imageUrl\":\"https://cdn.example.com/1.png\"}]}",
                        MediaType.APPLICATION_JSON));

        assertThat(client.findFitting(3L, 7L)).contains(new FittingResult(
                true,
                "COMPLETED",
                "https://cdn.example.com/f3.png",
                List.of(new ResultProduct(1L, "셔츠", 39000, "https://cdn.example.com/1.png"))));
        server.verify();
    }

    @Test
    void findsNothingForAMissingFittingAndPassesOtherFailuresOn() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        VirtualTryOnServiceClient client = new VirtualTryOnServiceClient(builder, BASE_URL, SERVICE_TOKEN);
        server.expect(requestTo(BASE_URL + "/fittings/404?userId=7")).andRespond(withStatus(HttpStatus.NOT_FOUND));
        server.expect(requestTo(BASE_URL + "/fittings/3?userId=7")).andRespond(withServerError());

        assertThat(client.findFitting(404L, 7L)).isEmpty();
        assertThatThrownBy(() -> client.findFitting(3L, 7L)).isInstanceOf(RestClientException.class);
        server.verify();
    }

    // 시간 제한을 준 호출은 그 제한으로 만든 요청 팩토리를 쓰고, 주소·서비스 토큰은 평소와 같다.
    @Test
    void usesARequestFactoryBuiltForTheGivenTimeout() {
        List<Duration> timeouts = new ArrayList<>();
        List<MockClientHttpRequest> requests = new ArrayList<>();
        ClientHttpRequestFactory fakeFactory = (uri, httpMethod) -> {
            MockClientHttpRequest request = new MockClientHttpRequest(httpMethod, uri);
            MockClientHttpResponse response = new MockClientHttpResponse(
                    "{\"owned\":true,\"status\":\"COMPLETED\",\"resultImageUrl\":\"https://cdn.example.com/f3.png\",\"products\":[]}"
                            .getBytes(StandardCharsets.UTF_8),
                    HttpStatus.OK);
            response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
            request.setResponse(response);
            requests.add(request);
            return request;
        };
        VirtualTryOnServiceClient client = new VirtualTryOnServiceClient(
                RestClient.builder(), BASE_URL, SERVICE_TOKEN, timeout -> {
                    timeouts.add(timeout);
                    return fakeFactory;
                });

        assertThat(client.findFitting(3L, 7L, Duration.ofMillis(800)))
                .contains(new FittingResult(true, "COMPLETED", "https://cdn.example.com/f3.png", List.of()));
        assertThat(timeouts).containsExactly(Duration.ofMillis(800));
        assertThat(requests).singleElement().satisfies(request -> {
            assertThat(request.getURI()).hasToString(BASE_URL + "/fittings/3?userId=7");
            assertThat(request.getHeaders().getFirst(VirtualTryOnServiceClient.SERVICE_TOKEN_HEADER)).isEqualTo(SERVICE_TOKEN);
        });
    }

    @Test
    void doesNotCallAnythingUntilTheAddressIsConfigured() {
        RestClient.Builder builder = RestClient.builder();
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        VirtualTryOnServiceClient client = new VirtualTryOnServiceClient(builder, "", SERVICE_TOKEN);

        assertThatThrownBy(() -> client.findFitting(3L, 7L)).isInstanceOf(ResourceAccessException.class);
        server.verify();
    }
}
