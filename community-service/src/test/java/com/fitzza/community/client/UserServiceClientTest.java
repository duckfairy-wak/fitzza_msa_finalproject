package com.fitzza.community.client;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class UserServiceClientTest {

    private static final String NICKNAME_API = "https://user-service/internal/users";
    private static final String INTERNAL_TOKEN = "test-internal-token";

    private MockRestServiceServer server;
    private UserServiceClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        client = new UserServiceClient(builder, "https://user-service", INTERNAL_TOKEN);
    }

    @Test
    void returnsNicknamesKeyedByUserId() {
        server.expect(requestTo(startsWith(NICKNAME_API + "?userIds=")))
                .andExpect(method(HttpMethod.GET))
                .andExpect(header(UserServiceClient.INTERNAL_TOKEN_HEADER, INTERNAL_TOKEN))
                .andRespond(withSuccess(
                        "[{\"userId\":7,\"nickname\":\"fitzza\"},{\"userId\":8,\"nickname\":\"coordi\"}]",
                        MediaType.APPLICATION_JSON));

        Map<Long, String> nicknames = client.findNicknames(Arrays.asList(7L, 8L, 7L, null));

        assertThat(nicknames).containsOnly(Map.entry(7L, "fitzza"), Map.entry(8L, "coordi"));
        server.verify();
    }

    @Test
    void returnsNothingInsteadOfFailingWhenUserServiceIsDown() {
        server.expect(requestTo(startsWith(NICKNAME_API))).andRespond(withServerError());

        Map<Long, String> nicknames = client.findNicknames(List.of(7L));

        assertThat(nicknames).isEmpty();
        server.verify();
    }

    @Test
    void doesNotCallUserServiceWhenThereIsNobodyToLookUp() {
        Map<Long, String> nicknames = client.findNicknames(List.of());

        assertThat(nicknames).isEmpty();
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {"http://user-service", "http://user-service:8081", "//user-service", "user-service",
            "https:///internal/users", "https://token@user-service", "https://user-service#fragment"})
    void refusesToStartWithAnUnsafeServiceUrl(String baseUrl) {
        assertThatThrownBy(() -> new UserServiceClient(RestClient.builder(), baseUrl, INTERNAL_TOKEN))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void refusesToStartWithoutAnInternalToken() {
        assertThatThrownBy(() -> new UserServiceClient(RestClient.builder(), "https://user-service", " "))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
