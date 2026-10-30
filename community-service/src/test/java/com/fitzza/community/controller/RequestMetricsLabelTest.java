package com.fitzza.community.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import com.fitzza.community.service.PostService;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tag;
import io.micrometer.core.instrument.observation.DefaultMeterObservationHandler;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import io.micrometer.observation.ObservationRegistry;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.filter.ServerHttpObservationFilter;

// 요청 메트릭 라벨은 경로 템플릿·메서드·상태 같은 제한된 값만 가져야 한다(FITZZA-314).
// 게시글 ID나 사용자 ID가 라벨에 들어가면 시계열이 끝없이 늘어난다.
class RequestMetricsLabelTest {

    private final MeterRegistry meters = new SimpleMeterRegistry();
    private final MockMvc mockMvc;

    RequestMetricsLabelTest() {
        ObservationRegistry observations = ObservationRegistry.create();
        observations.observationConfig().observationHandler(new DefaultMeterObservationHandler(meters));
        mockMvc = MockMvcBuilders.standaloneSetup(new PostController(mock(PostService.class)))
                .addFilters(new ServerHttpObservationFilter(observations))
                .build();
    }

    @Test
    void postDetailIsRecordedByItsRouteTemplateNotItsId() throws Exception {
        mockMvc.perform(get("/api/community/posts/987654321").header("X-User-Id", "123456789"));

        List<Tag> tags = meters.get("http.server.requests").timer().getId().getTags();
        assertThat(tags).extracting(Tag::getKey)
                .contains("method", "uri", "status")
                .isSubsetOf("method", "uri", "status", "outcome", "exception", "error");
        assertThat(tags).contains(Tag.of("uri", "/api/community/posts/{postId}"), Tag.of("method", "GET"));
        assertThat(tags).extracting(Tag::getValue).noneMatch(value -> value.contains("987654321"))
                .noneMatch(value -> value.contains("123456789"));
    }
}
