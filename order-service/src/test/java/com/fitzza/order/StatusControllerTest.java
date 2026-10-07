package com.fitzza.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class StatusControllerTest {
    private final OrderServiceApplication.StatusController controller =
            new OrderServiceApplication.StatusController();
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @Test
    void returnsServiceIdentityAndCurrentTimestampOnEachCall() {
        for (int call = 0; call < 2; call++) {
            Instant before = Instant.now();
            Map<String, Object> response = controller.status();
            Instant after = Instant.now();

            assertThat(response).containsOnlyKeys("service", "status", "timestamp");
            assertThat(response).containsEntry("service", "order-service").containsEntry("status", "UP");
            assertThat(response.get("timestamp")).isInstanceOf(Instant.class);
            assertThat((Instant) response.get("timestamp")).isBetween(before, after);
        }
    }

    @Test
    void servesStatusAsJsonAtThePublicRoute() throws Exception {
        mockMvc.perform(get("/api/v1/orders/status"))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.length()").value(3))
                .andExpect(jsonPath("$.service").value("order-service"))
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.timestamp").exists());
    }

    @Test
    void rejectsPostToTheReadOnlyStatusEndpoint() throws Exception {
        mockMvc.perform(post("/api/v1/orders/status"))
                .andExpect(status().isMethodNotAllowed());
    }

    @Test
    void returnsNotFoundForAnUnknownEndpoint() throws Exception {
        mockMvc.perform(get("/api/v1/orders/missing"))
                .andExpect(status().isNotFound());
    }
}
