package com.fitzza.community.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.fitzza.community.client.ProductCatalog.ProductSummary;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

class ProductServiceClientTest {

    private static final String BASE_URL = "http://product-service";
    private static final String SERVICE_TOKEN = "test-community-service-token";

    private MockRestServiceServer server;
    private ProductServiceClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new ProductServiceClient(builder, BASE_URL, SERVICE_TOKEN);
    }

    @Test
    void asksTheProductServiceWhetherTheUserWishlistedTheProduct() {
        server.expect(requestTo(BASE_URL + "/wishlists/check?userId=7&itemId=55"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(ProductServiceClient.SERVICE_TOKEN_HEADER, SERVICE_TOKEN))
                .andRespond(withSuccess("{\"wishlisted\":true}", MediaType.APPLICATION_JSON));
        server.expect(requestTo(BASE_URL + "/wishlists/check?userId=8&itemId=55"))
                .andRespond(withSuccess("{\"wishlisted\":false}", MediaType.APPLICATION_JSON));

        assertThat(client.isWishlisted(7L, 55L)).isTrue();
        assertThat(client.isWishlisted(8L, 55L)).isFalse();
        server.verify();
    }

    @Test
    void readsTheProductSummaryAndIgnoresFieldsItDoesNotUse() {
        server.expect(requestTo(BASE_URL + "/products?productIds=55"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(ProductServiceClient.SERVICE_TOKEN_HEADER, SERVICE_TOKEN))
                .andRespond(withSuccess(
                        "[{\"productId\":55,\"brandName\":\"Fitzza\",\"productName\":\"오버핏 셔츠\","
                                + "\"price\":39000,\"imageUrl\":\"https://cdn.example.com/55.png\",\"status\":\"ON_SALE\"}]",
                        MediaType.APPLICATION_JSON));

        assertThat(client.findProduct(55L))
                .contains(new ProductSummary(55L, "Fitzza", "오버핏 셔츠", 39000, "https://cdn.example.com/55.png", "ON_SALE"));
        server.verify();
    }

    @Test
    void readsFreshImageUrlsForManyProductsInOneRequest() {
        server.expect(requestTo(BASE_URL + "/products?productIds=55&productIds=56&productIds=57"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(ProductServiceClient.SERVICE_TOKEN_HEADER, SERVICE_TOKEN))
                .andRespond(withSuccess(
                        "[{\"productId\":55,\"imageUrl\":\"https://s3.example.com/55.jpg?X-Amz-Expires=3600\"},"
                                + "{\"productId\":56,\"imageUrl\":\"\"}]",
                        MediaType.APPLICATION_JSON));

        assertThat(client.findImageUrls(List.of(55L, 56L, 57L)))
                .containsExactly(Map.entry(55L, "https://s3.example.com/55.jpg?X-Amz-Expires=3600"));
        server.verify();
    }

    @Test
    void findsNothingWhenTheProductDoesNotExist() {
        server.expect(requestTo(BASE_URL + "/products?productIds=404"))
                .andRespond(withSuccess("[]", MediaType.APPLICATION_JSON));

        assertThat(client.findProduct(404L)).isEmpty();
        server.verify();
    }

    @Test
    void readsTheWorldcupResultForTheUser() {
        server.expect(requestTo(BASE_URL + "/worldcups/9?userId=7"))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(ProductServiceClient.SERVICE_TOKEN_HEADER, SERVICE_TOKEN))
                .andRespond(withSuccess(
                        "{\"worldcupHistoryId\":9,\"owned\":true,\"winnerProduct\":{\"productId\":55,"
                                + "\"brandName\":\"Fitzza\",\"productName\":\"오버핏 셔츠\",\"price\":39000,"
                                + "\"imageUrl\":\"https://cdn.example.com/55.png\",\"status\":\"ON_SALE\"},"
                                + "\"completedAt\":\"2026-10-13T10:00:00\"}",
                        MediaType.APPLICATION_JSON));
        server.expect(requestTo(BASE_URL + "/worldcups/9?userId=8"))
                .andRespond(withSuccess(
                        "{\"worldcupHistoryId\":9,\"owned\":false,\"winnerProduct\":null,\"completedAt\":null}",
                        MediaType.APPLICATION_JSON));

        assertThat(client.findWorldcup(9L, 7L)).contains(new WorldcupResults.WorldcupResult(9L, true,
                new WorldcupResults.WinnerProduct(55L, "Fitzza", "오버핏 셔츠", 39000, "https://cdn.example.com/55.png")));
        assertThat(client.findWorldcup(9L, 8L)).contains(new WorldcupResults.WorldcupResult(9L, false, null));
        server.verify();
    }

    @Test
    void findsNoWorldcupResultWhenTheProductServiceSaysNotFound() {
        server.expect(requestTo(BASE_URL + "/worldcups/404?userId=7"))
                .andRespond(withStatus(HttpStatus.NOT_FOUND));
        server.expect(requestTo(BASE_URL + "/worldcups/9?userId=7"))
                .andRespond(withServerError());

        assertThat(client.findWorldcup(404L, 7L)).isEmpty();
        assertThatThrownBy(() -> client.findWorldcup(9L, 7L)).isInstanceOf(RestClientException.class);
        server.verify();
    }

    @Test
    void passesTheFailureOnWhenTheProductServiceIsDown() {
        server.expect(requestTo(BASE_URL + "/wishlists/check?userId=7&itemId=55"))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.isWishlisted(7L, 55L)).isInstanceOf(RestClientException.class);
        server.verify();
    }
}
